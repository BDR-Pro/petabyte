#!/usr/bin/env python3
"""
Petabyte gateway — reverse tunnel + stable-handle routing.

THE PROBLEM THIS SOLVES
    A seller's GPU sits behind a home router. It has no public IP and no open
    inbound ports. A buyer must still reach it at a stable address that survives
    the machine dying and the VM being moved to a different machine.

HOW IT WORKS (the same shape as frp, in ~200 lines so we can test it end to end)
    1. The NODE dials OUT to the gateway (outbound connections traverse NAT
       freely — this is the whole trick) and says "I am node N".
    2. The gateway holds that control connection open.
    3. A BUYER connects to the gateway and names a VM handle.
    4. The gateway asks the Petabyte API: which node currently hosts this handle?
       -> GET /vm/{handle}/route  (X-Gateway-Token)
    5. The gateway sends "open a data channel" down the node's control connection.
    6. The node dials OUT again (a data connection) and bridges it to the local
       container port.
    7. The gateway splices buyer <-> data connection. Bytes flow. No inbound port
       was ever opened on the node.

    On failover the API returns a DIFFERENT node for the SAME handle. The buyer's
    address never changes.

PRODUCTION
    Use frp (github.com/fatedier/frp) + sshpiper instead of this — they are
    battle-tested, handle TLS/multiplexing/reconnect properly, and the configs are
    in docs/vm-runbook.md. This module exists to (a) prove OUR control-plane wiring
    end to end in CI, and (b) be a readable reference for what the gateway must do.

RUN
    gateway:  python gateway.py serve --control-port 7000 --buyer-port 2222
    node:     python gateway.py node --gateway 1.2.3.4:7000 --node-id N --local-port 22
"""
import argparse
import json
import os
import selectors
import socket
import struct
import sys
import threading
import time
import urllib.request

API_BASE = os.getenv("PETABYTE_API_URL", "http://127.0.0.1:8000").rstrip("/")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")

# ---------------------------------------------------------------------------
# tiny framing: [4-byte big-endian length][json]
# ---------------------------------------------------------------------------


def send_msg(sock, obj: dict) -> None:
    body = json.dumps(obj).encode()
    sock.sendall(struct.pack(">I", len(body)) + body)


def recv_msg(sock, timeout=None) -> dict | None:
    if timeout:
        sock.settimeout(timeout)
    try:
        hdr = _recv_exact(sock, 4)
        if not hdr:
            return None
        (n,) = struct.unpack(">I", hdr)
        if n > 1 << 20:
            return None
        body = _recv_exact(sock, n)
        return json.loads(body) if body else None
    except (socket.timeout, OSError, ValueError):
        return None
    finally:
        if timeout:
            try:
                sock.settimeout(None)
            except OSError:
                pass


def _recv_exact(sock, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def splice(a: socket.socket, b: socket.socket) -> None:
    """Pump bytes both ways until either side closes."""
    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ, b)
    sel.register(b, selectors.EVENT_READ, a)
    try:
        while True:
            for key, _ in sel.select(timeout=300):
                src, dst = key.fileobj, key.data
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)
    except OSError:
        return
    finally:
        sel.close()
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# GATEWAY
# ---------------------------------------------------------------------------

class Gateway:
    def __init__(self, control_port: int, buyer_port: int, resolver=None):
        self.control_port = control_port
        self.buyer_port = buyer_port
        self.nodes: dict[str, socket.socket] = {}        # node_id -> control conn
        self.pending: dict[str, socket.socket] = {}      # ticket  -> buyer conn
        self.lock = threading.Lock()
        # resolver(handle) -> node_id. Defaults to asking the Petabyte API.
        self.resolve = resolver or self._resolve_via_api
        self.log = lambda *a: print("[gateway]", *a, flush=True)

    def _resolve_via_api(self, handle: str) -> str | None:
        """Ask the control plane which node currently hosts this VM handle.
        This is the ONLY thing that changes on failover — same handle, new node."""
        req = urllib.request.Request(
            f"{API_BASE}/vm/{handle}/route",
            headers={"X-Gateway-Token": GATEWAY_TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
            return str(data.get("node_id") or data.get("spec_id") or "")
        except Exception as e:
            self.log(f"resolve failed for {handle}: {e}")
            return None

    # --- node side: hold the outbound control connections ---
    def _serve_control(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.control_port))
        srv.listen(64)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self._handle_node, args=(conn,), daemon=True).start()

    def _handle_node(self, conn: socket.socket):
        hello = recv_msg(conn, timeout=10)
        if not hello:
            conn.close()
            return
        kind = hello.get("type")

        if kind == "register":          # a node's control channel
            node_id = str(hello.get("node_id"))
            with self.lock:
                old = self.nodes.get(node_id)
                self.nodes[node_id] = conn
            if old:
                try:
                    old.close()
                except OSError:
                    pass
            self.log(f"node {node_id} connected (outbound; no inbound port opened)")
            send_msg(conn, {"type": "registered"})
            # hold it open; the node answers "open" requests on it
            while recv_msg(conn) is not None:
                pass
            with self.lock:
                if self.nodes.get(node_id) is conn:
                    del self.nodes[node_id]
            self.log(f"node {node_id} disconnected")

        elif kind == "data":            # a node's data channel for one buyer
            ticket = str(hello.get("ticket"))
            with self.lock:
                buyer = self.pending.pop(ticket, None)
            if not buyer:
                conn.close()
                return
            self.log(f"bridging ticket {ticket}")
            splice(buyer, conn)
        else:
            conn.close()

    # --- buyer side ---
    def _serve_buyers(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.buyer_port))
        srv.listen(64)
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=self._handle_buyer, args=(conn,), daemon=True).start()

    def _handle_buyer(self, conn: socket.socket):
        """Buyer says which handle it wants (stands in for the SSH username
        `vm-<handle>` that sshpiper reads in production)."""
        hello = recv_msg(conn, timeout=10)
        if not hello or hello.get("type") != "connect":
            conn.close()
            return
        handle = str(hello.get("handle", ""))
        node_id = self.resolve(handle)
        if not node_id:
            send_msg(conn, {"type": "error", "error": "no route for handle"})
            conn.close()
            return
        with self.lock:
            node = self.nodes.get(node_id)
        if not node:
            send_msg(conn, {"type": "error", "error": f"node {node_id} not connected"})
            conn.close()
            return
        ticket = os.urandom(8).hex()
        with self.lock:
            self.pending[ticket] = conn
        self.log(f"handle {handle} -> node {node_id} (ticket {ticket})")
        try:
            send_msg(node, {"type": "open", "ticket": ticket, "handle": handle})
        except OSError:
            with self.lock:
                self.pending.pop(ticket, None)
            send_msg(conn, {"type": "error", "error": "node went away"})
            conn.close()
            return
        send_msg(conn, {"type": "connected", "node_id": node_id})
        # the node now dials in with this ticket; _handle_node splices them.

    def serve(self):
        threading.Thread(target=self._serve_control, daemon=True).start()
        threading.Thread(target=self._serve_buyers, daemon=True).start()
        self.log(f"control :{self.control_port}  buyers :{self.buyer_port}")


# ---------------------------------------------------------------------------
# NODE (runs on the seller's machine, behind NAT)
# ---------------------------------------------------------------------------

class Node:
    def __init__(self, gateway: str, node_id: str, local_port: int):
        self.host, self.port = gateway.split(":")
        self.port = int(self.port)
        self.node_id = str(node_id)
        self.local_port = int(local_port)
        self.log = lambda *a: print(f"[node {self.node_id}]", *a, flush=True)
        self._stop = threading.Event()

    def _open_data_channel(self, ticket: str):
        """Dial OUT to the gateway again, then bridge to the local workload."""
        try:
            g = socket.create_connection((self.host, self.port), timeout=10)
            send_msg(g, {"type": "data", "ticket": ticket})
            local = socket.create_connection(("127.0.0.1", self.local_port), timeout=10)
        except OSError as e:
            self.log(f"data channel failed: {e}")
            return
        self.log(f"serving ticket {ticket} from local:{self.local_port}")
        splice(g, local)

    def run(self):
        while not self._stop.is_set():
            try:
                # OUTBOUND connection — this is what beats NAT. No inbound port.
                ctl = socket.create_connection((self.host, self.port), timeout=10)
                send_msg(ctl, {"type": "register", "node_id": self.node_id})
                ack = recv_msg(ctl, timeout=10)
                if not ack:
                    raise OSError("no ack")
                self.log(f"connected to gateway {self.host}:{self.port} (outbound)")
                while not self._stop.is_set():
                    msg = recv_msg(ctl)
                    if msg is None:
                        break
                    if msg.get("type") == "open":
                        threading.Thread(target=self._open_data_channel,
                                         args=(msg["ticket"],), daemon=True).start()
            except OSError as e:
                if not self._stop.is_set():
                    self.log(f"disconnected ({e}); retrying in 2s")
            if not self._stop.is_set():
                time.sleep(2)

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------------
# buyer helper
# ---------------------------------------------------------------------------

def buyer_connect(gateway: str, handle: str, timeout=10) -> socket.socket:
    """Connect to a VM by its STABLE handle. Stands in for
    `ssh vm-<handle>@petabyte.market`."""
    host, port = gateway.split(":")
    s = socket.create_connection((host, int(port)), timeout=timeout)
    send_msg(s, {"type": "connect", "handle": handle})
    reply = recv_msg(s, timeout=timeout)
    if not reply or reply.get("type") != "connected":
        err = (reply or {}).get("error", "unknown")
        s.close()
        raise ConnectionError(f"gateway refused: {err}")
    return s


def main():
    ap = argparse.ArgumentParser(description="Petabyte reverse-tunnel gateway")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("serve")
    g.add_argument("--control-port", type=int, default=7000)
    g.add_argument("--buyer-port", type=int, default=2222)
    n = sub.add_parser("node")
    n.add_argument("--gateway", required=True)
    n.add_argument("--node-id", required=True)
    n.add_argument("--local-port", type=int, required=True)
    a = ap.parse_args()
    if a.cmd == "serve":
        Gateway(a.control_port, a.buyer_port).serve()
        threading.Event().wait()
    else:
        Node(a.gateway, a.node_id, a.local_port).run()


if __name__ == "__main__":
    main()
