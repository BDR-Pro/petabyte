"""vm_dns_test.py — the STABLE per-VM address contract that docs/dynamic_dns.md relies on.

This is the fast, gateway-free companion to lumaris_gateway/tunnel_test.py. tunnel_test proves the
network path end to end (a buyer reaches a NAT'd, loopback-only workload by handle, and the same
handle survives the node dying). THIS test pins the naming/DNS contract behind that — the reason a
backup can take over WITHOUT the buyer ever handling a new IP:

  * a VM's buyer-facing address is derived ONLY from its stable, opaque id (vm-<id>@<domain> and
    <id>.<domain>) — never from the node's IP;
  * the buyer endpoint NEVER leaks which node/IP currently hosts the VM (no per-VM DNS churn, no
    placement disclosure);
  * on failover the id — and therefore every address the buyer holds — is byte-identical, while the
    gateway-only /vm/{id}/route flips to the NEW node's IP. One static wildcard DNS record forever;
    the control plane, not DNS, follows the VM.

Run: python vm_dns_test.py
"""
import base64
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta

os.environ["SECRET_KEY"] = "t"
os.environ["DATABASE_URL"] = "sqlite:///./vm_dns_test.db"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["BASE_DOMAIN"] = "petabyte.market"
os.environ["VM_DNS_ZONE"] = "vm.petabyte.market"     # per-VM subdomain zone (one wildcard record)
os.environ["GATEWAY_TOKEN"] = "gw-secret-token"
os.environ["REAPER_DISABLED"] = "true"
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for f in ("vm_dns_test.db", "vm_dns_test.db-wal", "vm_dns_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import db as dbmod  # noqa: E402
from db import SessionLocal, SellerSpec, get_vm_route  # noqa: E402

c = TestClient(main.app)
SK = Ed25519PrivateKey.generate()
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _sign(p):
    return base64.b64encode(SK.sign(json.dumps(p, sort_keys=True,
                            separators=(",", ":")).encode())).decode()


def _tok(u):
    return {"Authorization": "Bearer " + c.post(
        "/login", data={"username": u, "password": "pw-correct-horse-battery"}).json()["access_token"]}


def mkseller(nm, price):
    c.post("/register_user", json={"username": nm, "password": "pw-correct-horse-battery"})
    h = _tok(nm)
    c.post("/change_role", headers=h, json={"role": "seller"})
    sid = c.post("/register_specs", headers=h, json={
        "cpu": 8, "ram": 32, "gpu_model": "L4", "duration": 48,
        "price_per_hour": price, "provider": nm, "units": 2}).json()["spec_id"]
    at = {"cpu": 8, "ram": 32, "gpu_model": "L4", "nonce": nm, "ts": int(time.time())}
    c.post("/prove", headers=h, json={
        "spec_id": sid, "attestation": at, "signature": _sign(at),
        "pubkey": base64.b64encode(SK.public_key().public_bytes_raw()).decode()})
    key = c.post("/create_api_key", headers=h).json()["api_key"]
    c.post("/heartbeat", headers={"X-API-KEY": key}, json={"spec_id": sid})
    return h, sid, key


# two nodes (A cheaper so /launch lands on it), one funded buyer
ah, aspec, akey = mkseller("dnsA", 1.0)
bh, bspec, bkey = mkseller("dnsB", 2.0)
c.post("/register_user", json={"username": "dnsbuyer", "password": "pw-correct-horse-battery"})
BH = _tok("dnsbuyer")
c.post("/deposit", headers=BH, json={"amount": 50})

# ---- launch a VM: the buyer gets a STABLE, node-independent address ----
lv = c.post("/launch", headers=BH, json={"template": "comfyui", "hours": 2}).json()
vm_id = lv["vm_id"]
url = lv["url"]
ok("launch returns a stable opaque VM id (not a node id / not an IP)",
   isinstance(vm_id, str) and len(vm_id) >= 8 and not _IP_RE.search(vm_id))
ok("the CANONICAL address is the per-VM subdomain <id>.vm.<domain> (id is the HOST)",
   url["hostname"] == f"{vm_id}.vm.petabyte.market"
   and url["ssh"] == f"ssh root@{vm_id}.vm.petabyte.market")
# THE MULTI-USER POINT: the id is in the HOST, so the SSH username is FREE — the same VM is
# reachable as root@, app@, ubuntu@, jupyter@, ... The hostname bakes in NO user.
ok("the hostname carries NO login user — <user>@<host> works for ANY user (root/app/ubuntu/...)",
   "@" not in url["hostname"] and "root" not in url["hostname"]
   and all(f"ssh {u}@{url['hostname']}".endswith(f"@{vm_id}.vm.petabyte.market")
           for u in ("root", "app", "ubuntu", "jupyter")))
ok("the HTTP address is the same per-VM subdomain (one wildcard cert covers it)",
   url["http"] == f"https://{vm_id}.vm.petabyte.market")
# The fallback exists but CANNOT carry a login user: the id IS the username, so a second user
# (root vs app) would need its own handle. This is why the subdomain is canonical.
ok("username-routing fallback puts the id in the USERNAME slot (so it can't also carry a user)",
   url["ssh_username_fallback"] == f"ssh vm-{vm_id}@petabyte.market")
ok("the buyer-facing address contains NO node IP (backup can move nodes without a new address)",
   not _IP_RE.search(json.dumps(url)))

# ---- the buyer endpoint never leaks WHERE the VM currently runs ----
mine = c.get(f"/vm/{vm_id}", headers=BH).json()
ok("GET /vm/{id} exposes the stable url but NOT the node ip / tunnel port (no placement leak)",
   mine["url"]["ssh"] == url["ssh"]
   and "node_ip" not in mine and "tunnel_port" not in mine
   and not _IP_RE.search(json.dumps(mine)))

# ---- the node registers its tunnel; the gateway (token-gated) can resolve id -> current node ----
d = SessionLocal(); vm = get_vm_route(d, vm_id); landed = vm.current_spec_id; d.close()
ok("the VM landed on the cheaper node A", landed == aspec)
c.post("/vm/register_tunnel", headers={"X-API-KEY": akey},
       json={"vm_id": vm_id, "tunnel_port": 40001, "ip_address": "10.0.0.1"})
no_tok = c.get(f"/vm/{vm_id}/route")
ok("resolving id -> node is GATEWAY-ONLY (a buyer can't enumerate node placement) — 403 w/o token",
   no_tok.status_code == 403)
route_a = c.get(f"/vm/{vm_id}/route", headers={"X-Gateway-Token": "gw-secret-token"}).json()
ok("the gateway resolves the stable id to node A's current placement",
   route_a["current_spec_id"] == aspec and route_a["node_ip"] == "10.0.0.1")

# ---- THE PAYOFF: node A dies -> failover to B -> SAME address, new IP behind it ----
d = SessionLocal()
spa = d.query(SellerSpec).filter(SellerSpec.id == aspec).first()
spa.last_seen = datetime.now(timezone.utc) - timedelta(seconds=999)
d.add(spa); d.commit(); d.close()
d = SessionLocal(); _reaped, migrated = dbmod.reap_and_failover(d); d.close()
ok("the reaper failed the VM over to another node when A went down", migrated == 1)

d = SessionLocal(); vm = get_vm_route(d, vm_id); now_on, migs = vm.current_spec_id, vm.migrations; d.close()
ok("the VM now runs on node B (a different machine / IP)", now_on == bspec)
# node B registers ITS tunnel (new IP) for the SAME vm id
c.post("/vm/register_tunnel", headers={"X-API-KEY": bkey},
       json={"vm_id": vm_id, "tunnel_port": 40002, "ip_address": "10.0.0.2"})
route_b = c.get(f"/vm/{vm_id}/route", headers={"X-Gateway-Token": "gw-secret-token"}).json()
ok("behind the scenes the gateway now points the SAME id at node B's new IP",
   route_b["current_spec_id"] == bspec and route_b["node_ip"] == "10.0.0.2")

# the buyer's address is BYTE-IDENTICAL — no new IP to handle, no DNS change
after = c.get(f"/vm/{vm_id}", headers=BH).json()
ok("the buyer's SSH/HTTP address is byte-identical after failover (no new IP to handle)",
   after["url"] == url and after["migrations"] == 1)
ok("the failover is visible in the VM's own words (created -> migrated)",
   {"created", "migrated"} <= {e["event"] for e in c.get(f"/vm/{vm_id}/events", headers=BH).json()["events"]})

for f in ("vm_dns_test.db", "vm_dns_test.db-wal", "vm_dns_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== vm dns/stable-address: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
