"""reverify_test.py — a random fraction of REAL deterministic jobs is re-executed on other
nodes and their signed content hashes compared (quorum on real work).

Offline, no GPU: we open a re-verification for a completed render job, then simulate the shadow
nodes reporting hashes and assert the outcome —
  * honest: shadows match the original -> AGREED, nobody frozen;
  * faker:  the original's hash diverges from the honest majority -> the ORIGINAL is frozen;
  * sampling gate: rate 0 never opens; a task that is itself a replica is never re-verified.

Run: python reverify_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./reverify_test.db"   # forced isolated SQLite
os.environ["SECRET_KEY"] = "t"
from cryptography.fernet import Fernet   # noqa: E402
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for _f in ("reverify_test.db", "reverify_test.db-wal", "reverify_test.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)

import db as dbmod   # noqa: E402
dbmod.init_db()
import reverify   # noqa: E402
import quorum      # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _seller(db, name):
    u = dbmod.create_user(db, name, "hunter2-correct-horse")
    s = dbmod.SellerSpec(user_id=u.id, cpu=8, ram=16, price_per_hour=2.0, duration=24,
                         provider=name, gpu_model="RTX 4090", attested=True, status="online")
    db.add(s); db.commit(); db.refresh(s)
    return u, s


def _completed_render(db, spec, content_hash):
    t = dbmod.Task(spec_id=spec.id, task_type="render", status="completed",
                   result_content_hash=content_hash, template_params='{"blend_ref":"x"}')
    db.add(t); db.commit(); db.refresh(t)
    return t


def _submit(db, task_id, h):
    quorum.record_submission(db, task_id, h)


# ---------------------------------------------------------------- eligibility + sampling gate
db = dbmod.SessionLocal()
uA, sA = _seller(db, "revA"); uB, sB = _seller(db, "revB"); uC, sC = _seller(db, "revC")

nb = dbmod.Task(spec_id=sA.id, task_type="notebook", status="completed", result_content_hash="h")
db.add(nb); db.commit(); db.refresh(nb)
ok("a non-deterministic notebook job is NOT eligible for re-verification", not reverify.eligible(nb))

r0 = _completed_render(db, sA, "H")
ok("a completed render WITH a content hash IS eligible", reverify.eligible(r0))
ok("sampling at rate 0 never opens a re-verification", reverify.sample_and_open(db, r0, rate=0.0) is None)

# ---------------------------------------------------------------- HONEST: shadows agree
chk = reverify.open_reverify(db, r0, others=[sB, sC])
import json as _json
subs = _json.loads(chk.submissions)
ok("re-verification seeds the ORIGINAL node's hash", subs[str(uA.id)]["hash"] == "H")
ok("re-verification dispatches a shadow re-run to each other node (2)",
   sum(1 for v in subs.values() if v["hash"] is None) == 2)
_shadow_tasks = [v["task_id"] for k, v in subs.items() if v["hash"] is None]
ok("shadow tasks are real pending re-runs on other nodes",
   all(db.query(dbmod.Task).filter(dbmod.Task.id == tid).first().status == "pending"
       for tid in _shadow_tasks))
for tid in _shadow_tasks:
    _submit(db, tid, "H")                                  # both honest nodes reproduce H
db.refresh(chk)
ok("all agree -> quorum AGREED", chk.status == "AGREED" and chk.agreed_hash == "H")
ok("an honest original node is NOT frozen", dbmod.payout_hold_active(db, uA.id) is False)
ok("honest shadow nodes are NOT frozen",
   not dbmod.payout_hold_active(db, uB.id) and not dbmod.payout_hold_active(db, uC.id))

# ---------------------------------------------------------------- FAKER: original diverges
uX, sX = _seller(db, "revX"); uY, sY = _seller(db, "revY"); uZ, sZ = _seller(db, "revZ")
rfake = _completed_render(db, sX, "FAKE")                  # X reported a bogus hash
chk2 = reverify.open_reverify(db, rfake, others=[sY, sZ])
subs2 = _json.loads(chk2.submissions)
for tid in [v["task_id"] for k, v in subs2.items() if v["hash"] is None]:
    _submit(db, tid, "REAL")                               # both honest re-runs produce REAL
db.refresh(chk2)
ok("2 honest re-runs outvote the faker -> AGREED on the real hash", chk2.status == "AGREED" and chk2.agreed_hash == "REAL")
ok("the ORIGINAL node whose hash diverged is FROZEN for fraud", dbmod.payout_hold_active(db, uX.id) is True)
ok("the honest re-run nodes are NOT frozen",
   not dbmod.payout_hold_active(db, uY.id) and not dbmod.payout_hold_active(db, uZ.id))

# ---------------------------------------------------------------- no infinite fan-out
shadow_task = db.query(dbmod.Task).filter(dbmod.Task.id == _shadow_tasks[0]).first()
shadow_task.status = "completed"; shadow_task.result_content_hash = "H"
db.add(shadow_task); db.commit()
ok("a task that is itself a quorum replica is never re-verified (no fan-out)",
   reverify.sample_and_open(db, shadow_task, rate=1.0) is None)

db.close()
print(f"\n=== reverify: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
