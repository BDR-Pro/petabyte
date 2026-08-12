"""disk_rental_test.py — rent SPARE DISK to a web3/BitTorrent storage network for extra earnings.

The disk analogue of idle mining. Proves the whole loop, hermetically (TestClient, offline):
  * a seller opts a node in, picks a provider (storj/btfs/sia), and sets a GB cap — and can limit,
    disable, or DELETE it; the GB cap is clamped to a safety ceiling and bad providers are rejected;
  * each node contributes under a UNIQUE node name (pbdisk-<spec_id>) — the attribution key — so a
    settled payout maps 1:1 to one seller's unified balance (no per-seller storage wallet);
  * the heartbeat carries the disk config so the agent can start/limit/stop/wipe the storage node;
  * reconcile credits the seller (1-take) + platform (take), attributes by node name, and is
    idempotent per (node, period);
  * a foreign seller can't touch another's node.

Also unit-checks the agent's pure launch logic (lumaris_agent/disk_node.py): the docker command,
the GB cap wired into the provider flag, and the platform-wallet (not per-seller) attribution.

Run: python disk_rental_test.py
"""
import os
import sys

os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///./disk_rental_test.db"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["REAPER_DISABLED"] = "true"
os.environ["MAX_DISK_ALLOC_GB"] = "1000"          # low ceiling to prove the clamp
os.environ["STORAGE_TAKE_RATE"] = "0.10"

for f in ("disk_rental_test.db", "disk_rental_test.db-wal", "disk_rental_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import db as dbm  # noqa: E402

# the agent's pure launch module (different package; unique module name -> safe to import)
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lumaris_agent"))
import disk_node as dn  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def make_seller(idx):
    """A seller with a spec, a JWT (owner actions) and an agent API key (report)."""
    c.post("/register_user", json={"username": f"dsk{idx}", "password": "pw-correct-horse-1"})
    jwt = c.post("/login", data={"username": f"dsk{idx}", "password": "pw-correct-horse-1"}).json()["access_token"]
    JH = {"Authorization": "Bearer " + jwt}
    s = dbm.SessionLocal()
    u = dbm.get_user_by_username(s, f"dsk{idx}")
    dbm.set_role(s, u.username, "seller")
    spec = dbm.save_specs(s, u, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.0,
                                 "provider": f"dsk{idx}", "gpu_model": "RTX 4090",
                                 "gpu_count": 1, "vram_gb": 24, "units": 1})
    spec.attested = True; spec.attest_pubkey = "k"; spec.status = "online"
    spec.last_seen = dbm._utcnow()
    s.add_all([u, spec]); s.commit()
    uid, spec_id = u.id, spec.id
    key, jti = main.gen_secure_api_key(u.username, 90, ["node", "jobs"])
    dbm.record_issued_key(s, uid, jti, "agent", ["node", "jobs"], 90)
    s.close()
    return {"idx": idx, "user_id": uid, "spec_id": spec_id, "jh": JH, "kh": {"X-API-KEY": key}}


def _balances(uid):
    s = dbm.SessionLocal()
    earn = float(dbm.get_user_by_id(s, uid).earnings)
    rev = float(dbm.get_or_create_platform(s).revenue)
    s.close()
    return earn, rev


A = make_seller(1)
B = make_seller(2)

# ---- ENABLING REQUIRES EXPLICIT ARGS (not an idle/fallback toggle) ----
none_provider = c.post("/nodes/disk", headers=A["jh"],
                       json={"spec_id": A["spec_id"], "enabled": True, "alloc_gb": 100})
ok("enabling WITHOUT a provider is refused (422) — disk rental always needs args",
   none_provider.status_code == 422)
none_alloc = c.post("/nodes/disk", headers=A["jh"],
                    json={"spec_id": A["spec_id"], "enabled": True, "provider": "storj"})
ok("enabling WITHOUT a GB cap is refused (422) — disk rental always needs args",
   none_alloc.status_code == 422)

# ---- explicit config + GB cap + provider validation ----
r = c.post("/nodes/disk", headers=A["jh"],
           json={"spec_id": A["spec_id"], "enabled": True, "provider": "storj", "alloc_gb": 5000})
j = r.json()
ok("a seller enables disk rental with an explicit provider + GB cap",
   r.status_code == 200 and j["disk"]["enabled"] is True and j["disk"]["provider"] == "storj")
ok("the GB cap is clamped to the safety ceiling (5000 -> MAX_DISK_ALLOC_GB=1000)",
   j["disk"]["alloc_gb"] == 1000)
ok("each node gets a UNIQUE contribution name pbdisk-<spec_id> (the attribution key)",
   j["disk"]["node_name"] == f"pbdisk-{A['spec_id']}")
bad = c.post("/nodes/disk", headers=A["jh"],
             json={"spec_id": A["spec_id"], "enabled": True, "provider": "dropbox", "alloc_gb": 10})
ok("an unsupported provider is rejected (422)", bad.status_code == 422)

# two different nodes -> two different attribution names (no collision)
rb = c.post("/nodes/disk", headers=B["jh"],
            json={"spec_id": B["spec_id"], "enabled": True, "provider": "btfs", "alloc_gb": 200}).json()
ok("a second node contributes under its OWN distinct name",
   rb["disk"]["node_name"] == f"pbdisk-{B['spec_id']}"
   and rb["disk"]["node_name"] != j["disk"]["node_name"])

# ---- the heartbeat carries the disk config so the agent can act on it ----
hb = c.post("/heartbeat", headers=A["kh"], json={"spec_id": A["spec_id"]}).json()
ok("the heartbeat delivers the disk config to the agent (enabled/provider/cap/node name)",
   hb["disk"]["enabled"] is True and hb["disk"]["provider"] == "storj"
   and hb["disk"]["alloc_gb"] == 1000 and hb["disk"]["node_name"] == f"pbdisk-{A['spec_id']}")

# ---- agent report + status ----
rep = c.post("/nodes/disk_report", headers=A["kh"],
             json={"spec_id": A["spec_id"], "provider": "storj", "used_gb": 12.5, "est_daily_usd": 0.05})
ok("the agent reports usage + an estimated trickle", rep.status_code == 200)
st = c.get(f"/nodes/{A['spec_id']}/disk", headers=A["jh"]).json()
ok("status shows the config, usage, node name, and credited-to-date",
   st["enabled"] is True and st["used_gb"] == 12.5
   and st["node_name"] == f"pbdisk-{A['spec_id']}" and st["credited_total_usd"] == 0.0)

# ---- providers catalog ----
prov = c.get("/disk/providers").json()
ok("the providers catalog lists the web3/bittorrent adapters + a take rate",
   {p["id"] for p in prov["providers"]} == {"storj", "btfs", "sia"} and "take_rate" in prov)

# ---- reconcile: settled earnings credit the seller's unified balance, attributed by node name ----
node_a = f"pbdisk-{A['spec_id']}"
earn0, rev0 = _balances(A["user_id"])
s = dbm.SessionLocal()
res = dbm.reconcile_disk_earnings(
    s, {node_a: {"period": "2026-08-01", "amount": 10.0, "provider": "storj"}}, 0.10)
s.close()
earn1, rev1 = _balances(A["user_id"])
ok("settled storage earnings credit the RIGHT seller (attributed by node name)",
   res["credited_nodes"] == 1 and abs((earn1 - earn0) - 9.0) < 1e-9)
ok("the platform take (10%) is booked as revenue", abs((rev1 - rev0) - 1.0) < 1e-9)
ok("credited-to-date now reflects the settlement",
   c.get(f"/nodes/{A['spec_id']}/disk", headers=A["jh"]).json()["credited_total_usd"] == 9.0)

# idempotent per (node, period): running the same settlement again credits nothing more
s = dbm.SessionLocal()
res2 = dbm.reconcile_disk_earnings(
    s, {node_a: {"period": "2026-08-01", "amount": 10.0, "provider": "storj"}}, 0.10)
s.close()
earn2, _ = _balances(A["user_id"])
ok("reconcile is idempotent per (node, period) — no double credit",
   res2["credited_nodes"] == 0 and abs(earn2 - earn1) < 1e-9)

# ---- ownership: a foreign seller can't touch another's node ----
ok("a foreign seller can't toggle another's node (404)",
   c.post("/nodes/disk", headers=B["jh"],
          json={"spec_id": A["spec_id"], "enabled": False}).status_code == 404)
ok("a foreign agent key can't report for another's node (404)",
   c.post("/nodes/disk_report", headers=B["kh"],
          json={"spec_id": A["spec_id"], "provider": "storj"}).status_code == 404)

# ---- limit change, then DELETE (cancel + wipe signal) ----
lim = c.post("/nodes/disk", headers=A["jh"],
             json={"spec_id": A["spec_id"], "enabled": True, "provider": "storj", "alloc_gb": 50}).json()
ok("the seller can LOWER the cap at any time", lim["disk"]["alloc_gb"] == 50)
dele = c.delete(f"/nodes/{A['spec_id']}/disk", headers=A["jh"]).json()
ok("DELETE cancels the contribution: disabled + config cleared (agent then wipes)",
   dele["disk"]["enabled"] is False and dele["disk"]["provider"] is None)
hb2 = c.post("/heartbeat", headers=A["kh"], json={"spec_id": A["spec_id"]}).json()
ok("after delete the heartbeat signals disabled + no provider (the agent removes + wipes the node)",
   hb2["disk"]["enabled"] is False and hb2["disk"]["provider"] is None)

# ---- the agent's PURE launch logic (lumaris_agent/disk_node.py) ----
cmd = dn.build_disk_cmd(provider="storj", node_name=node_a, alloc_gb=500,
                        data_dir="/var/lib/petabyte/disk/" + node_a, wallet="0xPLATFORM")
cs = " ".join(cmd)
ok("the storage node launches as its unique named container",
   f"petabyte-disk-{node_a}" in cs and cmd[:3] == ["docker", "run", "-d"])
ok("the seller's GB cap is wired into the provider's max-storage flag",
   "STORAGE=500GB" in cs and "PB_ALLOC_GB=500" in cs)
ok("attribution: the node name is passed, and the PLATFORM wallet (not a per-seller wallet) is set",
   f"PB_NODE_NAME={node_a}" in cs and "WALLET=0xPLATFORM" in cs)
try:
    dn.build_disk_cmd(provider="storj", node_name=node_a, alloc_gb=0, data_dir="/x")
    ok("a zero/negative GB pledge is refused", False)
except ValueError:
    ok("a zero/negative GB pledge is refused", True)
ok("the pre-commit earnings estimate scales with pledged TB (planning figure, not a payout)",
   dn.est_daily_usd(1000, 1.5) == round(1.5 / 30.0, 4))

for f in ("disk_rental_test.db", "disk_rental_test.db-wal", "disk_rental_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== disk rental: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
