"""Offline tests for seller integrity audits + fraud->freeze.

Drives a real seller node over HTTP (attest with the agent's Ed25519 key, heartbeat),
then:
  * an honest answer to a platform audit -> passes, NO payout hold;
  * a WRONG answer to a platform audit -> payouts frozen;
  * a forged signature -> 401 AND payouts frozen.

Run: python seller_audit_test.py
"""
import os
import sys
import time
import base64
import json
import tempfile

from cryptography.fernet import Fernet

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./seller_audit_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "w"
os.environ["ADMIN_USERS"] = "admin1"
os.environ["HEARTBEAT_TIMEOUT_S"] = "120"
os.environ["REAPER_DISABLED"] = "true"
os.environ["NOTIFY_STUB"] = "true"

for f in ("seller_audit_test.db", "seller_audit_test.db-wal", "seller_audit_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

# agent signing identity (same crypto the real node uses)
_kd = tempfile.mkdtemp(prefix="pb-agent-")
os.environ["PETABYTE_AGENT_KEY"] = os.path.join(_kd, "agent.key")
# APPEND (not insert) so lumaris_api modules (e.g. 'main') still win over the agent's.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lumaris_agent"))
import crypto as agent_crypto  # noqa: E402  (lumaris_agent/crypto.py)

from fastapi.testclient import TestClient  # noqa: E402
import db as dbmod  # noqa: E402
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()
import main  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def signed(output_hash):
    proof = {"output_hash": output_hash, "ts": int(time.time())}
    return {"proof": proof, "signature": agent_crypto.sign_proof(proof)}


# ---- onboard admin + a real seller node ----
for u in ("admin1", "sellerA"):
    c.post("/register_user", json={"username": u, "password": "pw-correct-horse-1"})
admin_t = c.post("/login", data={"username": "admin1", "password": "pw-correct-horse-1"}).json()["access_token"]
seller_t = c.post("/login", data={"username": "sellerA", "password": "pw-correct-horse-1"}).json()["access_token"]
AT = {"Authorization": f"Bearer {admin_t}"}
ST = {"Authorization": f"Bearer {seller_t}"}
c.post("/change_role", headers=ST, json={"role": "seller"})
api_key = c.post("/create_api_key?days=90&scopes=node,jobs", headers=ST).json()["api_key"]
SK = {"X-API-KEY": api_key}
spec_id = c.post("/register_specs", headers=ST, json={"cpu": 8, "ram": 32, "duration": 24,
    "price_per_hour": 1.5, "provider": "local", "gpu_model": "NVIDIA L4", "gpu_count": 1,
    "vram_gb": 24, "units": 1}).json()["spec_id"]
att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(), "ts": int(time.time())}
c.post("/prove", headers=ST, json={"spec_id": spec_id, "attestation": att,
    "signature": agent_crypto.sign_proof(att), "pubkey": agent_crypto.public_key_b64()})
c.post("/heartbeat", headers=SK, json={"spec_id": spec_id})

sid = dbmod.SessionLocal()
seller_uid = main.get_user_by_username(sid, "sellerA").id
sid.close()


def run_audit_and_claim():
    """Trigger an audit for all bookable sellers, then claim the test task as the node."""
    disp = c.post("/admin/audits/run?sample_rate=1", headers=AT).json()
    assert disp["dispatched"] >= 1, disp
    claim = c.get("/jobs/next", headers=SK).json()
    assert claim.get("task_type") == "test", claim
    return claim


def hold_active():
    s = dbmod.SessionLocal()
    try:
        return dbmod.payout_hold_active(s, seller_uid)
    finally:
        s.close()


# ---- 1) admin can dispatch a spot-check audit ----
j = run_audit_and_claim()
ok("audit: platform dispatches a known-answer challenge to a live seller",
   "size" in j and "seed" in j)

# ---- 2) honest correct answer passes, NO freeze ----
correct = agent_crypto.compute_test_hash(int(j["size"]), int(j["seed"]))
r = c.post("/jobs/result", headers=SK, json={"task_id": j["task_id"], "status": "completed", **signed(correct)})
ok("audit: correct answer passes", r.json().get("test_passed") is True)
ok("audit: an honest pass does NOT freeze payouts", hold_active() is False)

# ---- 3) WRONG answer to a platform audit -> payouts frozen ----
j2 = run_audit_and_claim()
wrong = agent_crypto.compute_test_hash(int(j2["size"]), int(j2["seed"]) + 1)   # wrong on purpose
r2 = c.post("/jobs/result", headers=SK, json={"task_id": j2["task_id"], "status": "completed", **signed(wrong)})
ok("audit: wrong answer is recorded as failed", r2.json().get("test_passed") is False)
ok("audit: failing a platform audit FREEZES the seller's payouts", hold_active() is True)

# release the hold for the next case
sid = dbmod.SessionLocal(); dbmod.clear_payout_hold(sid, seller_uid); sid.close()
ok("hold can be released after review", hold_active() is False)

# ---- 4) forged signature -> 401 AND payouts frozen ----
j3 = run_audit_and_claim()
good_hash = agent_crypto.compute_test_hash(int(j3["size"]), int(j3["seed"]))
proof = {"output_hash": good_hash, "ts": int(time.time())}
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
bad_sig = base64.b64encode(Ed25519PrivateKey.generate().sign(
    json.dumps(proof, sort_keys=True, separators=(",", ":")).encode())).decode()
r3 = c.post("/jobs/result", headers=SK, json={"task_id": j3["task_id"], "status": "completed",
                                              "proof": proof, "signature": bad_sig})
ok("fraud: a forged signature is rejected (401)", r3.status_code == 401)
ok("fraud: a forged signature FREEZES the seller's payouts", hold_active() is True)

print(f"\n=== seller-audit: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
for f in ("seller_audit_test.db", "seller_audit_test.db-wal", "seller_audit_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
raise SystemExit(1 if _fail else 0)
