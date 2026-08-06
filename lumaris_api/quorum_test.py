"""Offline tests for quorum verification (redundant re-execution across sellers).

- compare() engine: majority agreement, divergence, 1-vs-1 split, empty.
- HTTP flow: 3 sellers run the SAME challenge; 2 agree, 1 fakes -> the faker diverges from
  the majority and is FROZEN, the honest two are not.
- INCONCLUSIVE (2-way split): nobody can be blamed -> both held for review.

Run: python quorum_test.py
"""
import os
import base64
import json
import time

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./quorum_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "w"
os.environ["ADMIN_USERS"] = "admin1"
os.environ["HEARTBEAT_TIMEOUT_S"] = "120"
os.environ["REAPER_DISABLED"] = "true"
os.environ["NOTIFY_STUB"] = "true"

for f in ("quorum_test.db", "quorum_test.db-wal", "quorum_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient  # noqa: E402
import db as dbmod  # noqa: E402
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()
import main  # noqa: E402
import quorum  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def pub_b64(priv):
    return base64.b64encode(priv.public_key().public_bytes_raw()).decode()


def sign(priv, proof):
    msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(priv.sign(msg)).decode()


def hold(uid):
    s = dbmod.SessionLocal()
    try:
        return dbmod.payout_hold_active(s, uid)
    finally:
        s.close()


# ---- pure compare engine ----
ok("compare: 2-of-3 agree -> AGREED, the odd one diverges",
   (lambda r: r["verdict"] == "AGREED" and set(r["agree"]) == {1, 2} and r["diverge"] == [3])(
       quorum.compare([{"seller_id": 1, "hash": "a"}, {"seller_id": 2, "hash": "a"},
                       {"seller_id": 3, "hash": "b"}], min_agree=2)))
ok("compare: all agree -> AGREED, none diverge",
   quorum.compare([{"seller_id": 1, "hash": "a"}, {"seller_id": 2, "hash": "a"}],
                  min_agree=2)["diverge"] == [])
ok("compare: 1-vs-1 split -> INCONCLUSIVE",
   quorum.compare([{"seller_id": 1, "hash": "a"}, {"seller_id": 2, "hash": "b"}],
                  min_agree=2)["verdict"] == "INCONCLUSIVE")
ok("compare: no submissions -> INCONCLUSIVE",
   quorum.compare([], min_agree=2)["verdict"] == "INCONCLUSIVE")

# ---- onboard admin + 3 independent sellers ----
c.post("/register_user", json={"username": "admin1", "password": "pw-correct-horse-1"})
admin_t = c.post("/login", data={"username": "admin1", "password": "pw-correct-horse-1"}).json()["access_token"]
AT = {"Authorization": f"Bearer {admin_t}"}


def onboard(name):
    c.post("/register_user", json={"username": name, "password": "pw-correct-horse-1"})
    t = c.post("/login", data={"username": name, "password": "pw-correct-horse-1"}).json()["access_token"]
    H = {"Authorization": f"Bearer {t}"}
    c.post("/change_role", headers=H, json={"role": "seller"})
    key = c.post("/create_api_key?days=90&scopes=node,jobs", headers=H).json()["api_key"]
    SK = {"X-API-KEY": key}
    spec_id = c.post("/register_specs", headers=H, json={"cpu": 8, "ram": 32, "duration": 24,
        "price_per_hour": 1.5, "provider": name, "gpu_model": "NVIDIA L4", "gpu_count": 1,
        "vram_gb": 24, "units": 1}).json()["spec_id"]
    priv = Ed25519PrivateKey.generate()
    att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(), "ts": int(time.time())}
    c.post("/prove", headers=H, json={"spec_id": spec_id, "attestation": att,
        "signature": sign(priv, att), "pubkey": pub_b64(priv)})
    c.post("/heartbeat", headers=SK, json={"spec_id": spec_id})
    s = dbmod.SessionLocal(); uid = main.get_user_by_username(s, name).id; s.close()
    return {"name": name, "SK": SK, "priv": priv, "uid": uid, "spec_id": spec_id}


sellers = {n: onboard(n) for n in ("q_honest1", "q_honest2", "q_faker")}

# ---- open a 3-way quorum and have each seller answer ----
q = c.post("/admin/quorum/run?replicas=3&difficulty=easy", headers=AT).json()
ok("quorum opened across 3 sellers", q.get("ok") and len(q.get("replicas", [])) == 3)

# map seller_id -> task_id
task_of = {r["seller_id"]: r["task_id"] for r in q["replicas"]}


def submit(sel, correct=True):
    claim = c.get("/jobs/next", headers=sel["SK"]).json()
    assert claim.get("task_type") == "test", claim
    size, seed = int(claim["size"]), int(claim["seed"])
    h = dbmod.compute_test_hash(size, seed) if correct else dbmod.compute_test_hash(size, seed + 1)
    proof = {"output_hash": h, "ts": int(time.time())}
    return c.post("/jobs/result", headers=sel["SK"],
                  json={"task_id": claim["task_id"], "status": "completed",
                        "proof": proof, "signature": sign(sel["priv"], proof)})


submit(sellers["q_honest1"], correct=True)
submit(sellers["q_honest2"], correct=True)
submit(sellers["q_faker"], correct=False)      # the 3rd submission finalizes the quorum

ok("quorum: the faker (diverges from the majority) is FROZEN", hold(sellers["q_faker"]["uid"]) is True)
ok("quorum: honest seller 1 is NOT frozen", hold(sellers["q_honest1"]["uid"]) is False)
ok("quorum: honest seller 2 is NOT frozen", hold(sellers["q_honest2"]["uid"]) is False)

# ---- INCONCLUSIVE (2-way split) holds everyone for review ----
a, b = onboard("q_split_a"), onboard("q_split_b")
s = dbmod.SessionLocal()
chk = quorum.open_check(s, [dbmod.get_spec_by_id(s, a["spec_id"]),
                            dbmod.get_spec_by_id(s, b["spec_id"])], min_agree=2)
subs = json.loads(chk.submissions)
subs[str(a["uid"])]["hash"] = "resultA"
subs[str(b["uid"])]["hash"] = "resultB"   # disagree, no majority
chk.submissions = json.dumps(subs); s.add(chk); s.commit()
quorum.finalize(s, chk)
s.close()
ok("quorum: a 2-way split is INCONCLUSIVE and holds BOTH participants",
   hold(a["uid"]) is True and hold(b["uid"]) is True)

print(f"\n=== quorum: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
for f in ("quorum_test.db", "quorum_test.db-wal", "quorum_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
raise SystemExit(1 if _fail else 0)
