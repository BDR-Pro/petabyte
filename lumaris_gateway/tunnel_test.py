"""
tunnel_test.py — prove the reachable-VM loop end to end, in process.

This is the test for the thing that has never been proven: that a workload on a
machine with NO inbound ports open is reachable at a STABLE address, and that the
address survives the machine dying.

What it actually does (no mocks in the path that matters):
  * starts the real Petabyte API
  * starts the real gateway (lumaris_gateway/gateway.py)
  * starts TWO nodes that dial OUT to the gateway (simulating NAT — the test never
    connects to a node directly; it CANNOT, the node has no listening socket)
  * runs a real TCP service on each node, bound to LOOPBACK only
  * a buyer connects through the gateway using only the VM handle
  * kills node A, lets the reaper fail the VM over to node B
  * the buyer reconnects with the SAME handle and lands on node B

Run:  python tunnel_test.py
"""
import base64
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lumaris_api"))
sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tunnel.db")
os.environ.setdefault("SECRET_KEY", "t")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("GOOGLE_OAUTH_STUB", "true")
os.environ.setdefault("BASE_DOMAIN", "petabyte.market")
os.environ.setdefault("GATEWAY_TOKEN", "gw-secret-token")
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for f in ("tunnel.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import main
import db as dbmod
from db import SessionLocal, SellerSpec, get_vm_route
from gateway import Gateway, Node, buyer_connect, send_msg, recv_msg

c = TestClient(main.app)
SK = Ed25519PrivateKey.generate()
PASS = FAIL = 0


def ok(label, cond):
    global PASS, FAIL
    cond = bool(cond)
    PASS += cond
    FAIL += (not cond)
    print(("PASS " if cond else "FAIL ") + label, flush=True)


def sign(p):
    return base64.b64encode(SK.sign(json.dumps(p, sort_keys=True,
                            separators=(",", ":")).encode())).decode()


def tok(u):
    return {"Authorization": "Bearer " + c.post(
        "/login", data={"username": u, "password": "pw12345678"}).json()["access_token"]}


# ---------------------------------------------------------------------------
# a real TCP "workload" — stands in for the container's sshd / app port.
# Bound to 127.0.0.1 ONLY: nothing outside the machine can reach it directly.
# ---------------------------------------------------------------------------
class Workload(threading.Thread):
    def __init__(self, name):
        super().__init__(daemon=True)
        self.name = name
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))        # loopback only, random port
        self.port = self.sock.getsockname()[1]
        self.sock.listen(8)
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            data = conn.recv(1024)
            if data:
                conn.sendall(f"{self.name} received: {data.decode().strip()}".encode())
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def talk(sock, msg: str) -> str:
    """Send a line through the tunnel and read the workload's answer."""
    sock.sendall(msg.encode())
    sock.settimeout(5)
    return sock.recv(4096).decode()


# ---------------------------------------------------------------------------
# seed: two sellers (A cheaper so /launch picks it), one buyer
# ---------------------------------------------------------------------------
def mkseller(nm, price):
    c.post("/register_user", json={"username": nm, "password": "pw12345678"})
    h = tok(nm)
    c.post("/change_role", headers=h, json={"role": "seller"})
    sid = c.post("/register_specs", headers=h, json={
        "cpu": 8, "ram": 32, "gpu_model": "L4", "duration": 48,
        "price_per_hour": price, "provider": nm, "units": 2}).json()["spec_id"]
    at = {"cpu": 8, "ram": 32, "gpu_model": "L4", "nonce": nm, "ts": int(time.time())}
    c.post("/prove", headers=h, json={
        "spec_id": sid, "attestation": at, "signature": sign(at),
        "pubkey": base64.b64encode(SK.public_key().public_bytes_raw()).decode()})
    key = c.post("/create_api_key", headers=h).json()["api_key"]
    c.post("/heartbeat", headers={"X-API-KEY": key}, json={"spec_id": sid})
    return h, sid, key


print("\n=== setup ===", flush=True)
ah, aspec, akey = mkseller("tunnelA", 1.0)
bh, bspec, bkey = mkseller("tunnelB", 2.0)
c.post("/register_user", json={"username": "tunnelbuyer", "password": "pw12345678"})
buyer_h = tok("tunnelbuyer")
c.post("/deposit", headers=buyer_h, json={"amount": 50})

# the gateway resolves a handle -> the spec currently hosting it, by asking the API
def resolve(handle):
    d = SessionLocal()
    vm = get_vm_route(d, handle)
    d.close()
    return str(vm.current_spec_id) if vm else None


gw = Gateway(control_port=0, buyer_port=0, resolver=resolve)
# bind ephemeral ports so the test never collides
import socket as _s
_c = _s.socket(); _c.bind(("127.0.0.1", 0)); CTRL = _c.getsockname()[1]; _c.close()
_b = _s.socket(); _b.bind(("127.0.0.1", 0)); BUY = _b.getsockname()[1]; _b.close()
gw.control_port, gw.buyer_port = CTRL, BUY
gw.serve()
time.sleep(0.3)
GW = f"127.0.0.1:{BUY}"
CTRL_ADDR = f"127.0.0.1:{CTRL}"

# workloads: one per node, loopback-only
wl_a = Workload("node-A"); wl_a.start()
wl_b = Workload("node-B"); wl_b.start()

# nodes dial OUT to the gateway. Note: nothing ever listens for inbound on a node.
node_a = Node(CTRL_ADDR, node_id=str(aspec), local_port=wl_a.port)
node_b = Node(CTRL_ADDR, node_id=str(bspec), local_port=wl_b.port)
threading.Thread(target=node_a.run, daemon=True).start()
threading.Thread(target=node_b.run, daemon=True).start()
time.sleep(0.8)

ok("both nodes established OUTBOUND control channels (NAT traversed)",
   len(gw.nodes) == 2)

# ---------------------------------------------------------------------------
print("\n=== phase A: reach a NAT'd workload through a stable handle ===", flush=True)
# ---------------------------------------------------------------------------
lv = c.post("/launch", headers=buyer_h, json={"template": "comfyui", "hours": 2}).json()
handle = lv["vm_id"]
print(f"launched vm: {handle}  ->  {lv['url']['ssh']}", flush=True)

d = SessionLocal(); vm = get_vm_route(d, handle); landed_on = vm.current_spec_id; d.close()
ok("VM landed on the cheaper node (A)", landed_on == aspec)

# the node reports its tunnel to the control plane (the agent does this in prod)
rt = c.post("/vm/register_tunnel", headers={"X-API-KEY": akey},
            json={"vm_id": handle, "tunnel_port": BUY, "ip_address": "127.0.0.1"})
ok("node registered its tunnel with the API", rt.status_code == 200)

# THE MOMENT OF TRUTH: a buyer reaches the workload knowing ONLY the handle.
sock = buyer_connect(GW, handle)
reply = talk(sock, "hello from buyer")
sock.close()
print("buyer <- ", reply, flush=True)
ok("buyer reached the workload through the tunnel using only the handle",
   "node-A received: hello from buyer" == reply)

# prove the node really is unreachable directly (i.e. we didn't cheat)
direct = socket.socket()
direct.settimeout(2)
try:
    # the workload is bound to loopback:port — from "outside" (a different host) this
    # would be unreachable. In-process we can only assert it isn't publicly bound.
    host_bound = wl_a.sock.getsockname()[0]
finally:
    direct.close()
ok("workload is bound to loopback only (no public listener on the node)",
   host_bound == "127.0.0.1")

# ---------------------------------------------------------------------------
print("\n=== phase B: node A dies -> failover -> SAME handle, node B ===", flush=True)
# ---------------------------------------------------------------------------
node_a.stop()
wl_a.stop()
time.sleep(0.3)

# make A's heartbeat stale, then run the real reaper
d = SessionLocal()
spa = d.query(SellerSpec).filter(SellerSpec.id == aspec).first()
spa.last_seen = datetime.now(timezone.utc) - timedelta(seconds=999)
d.add(spa); d.commit(); d.close()

d = SessionLocal()
reaped, migrated = dbmod.reap_and_failover(d)
d.close()
print(f"reaper: reaped {reaped} spec(s), migrated {migrated} vm(s)", flush=True)
ok("reaper migrated the VM off the dead node", migrated == 1)

d = SessionLocal(); vm = get_vm_route(d, handle)
now_on, migrations, status = vm.current_spec_id, vm.migrations, vm.status
d.close()
ok("VM now points at node B", now_on == bspec)
ok("migration counted", migrations == 1)

# node B's agent registers the tunnel for the same VM
rt2 = c.post("/vm/register_tunnel", headers={"X-API-KEY": bkey},
             json={"vm_id": handle, "tunnel_port": BUY, "ip_address": "127.0.0.1"})
ok("node B registered the tunnel for the same VM", rt2.status_code == 200)

# THE PAYOFF: same handle, no client change, now served by a different machine
sock2 = buyer_connect(GW, handle)
reply2 = talk(sock2, "hello again")
sock2.close()
print("buyer <- ", reply2, flush=True)
ok("SAME handle now reaches node B (address never changed)",
   "node-B received: hello again" == reply2)

# and the URL the buyer was given at launch is byte-identical
vm_now = c.get(f"/vm/{handle}", headers=buyer_h).json()
ok("the buyer's connection string is unchanged after failover",
   vm_now["url"]["ssh"] == lv["url"]["ssh"])

# the timeline records what happened, in the buyer's words
ev = c.get(f"/vm/{handle}/events", headers=buyer_h).json()["events"]
kinds = [e["event"] for e in ev]
print("timeline:", " -> ".join(kinds), flush=True)
ok("event timeline shows created -> migrated (failover is visible)",
   "created" in kinds and "migrated" in kinds)

print(f"\n=== tunnel: {PASS} passed, {FAIL} failed ===", flush=True)
for f in ("tunnel.db",):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass
sys.exit(1 if FAIL else 0)
