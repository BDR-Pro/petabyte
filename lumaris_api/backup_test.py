"""backup_test.py — the platform database disaster-recovery backup to S3 is real and honest.

Proves, offline (forced SQLite + S3_STUB local dir, no AWS):
  * a backup dumps the DB, gzips it, and writes ONE object to S3 (the stub dir);
  * a DatabaseBackup row records the reference + SHA-256 of the compressed object;
  * the dump actually contains the schema (round-trips real data, not an empty file);
  * verify_backup re-downloads and confirms the SHA-256 (integrity), and CATCHES tampering;
  * retention prunes the oldest successful backups AND deletes their S3 objects;
  * backup_status reports a fresh age + counts (feeds the Prometheus gauge);
  * a missing S3_BUCKET fails loudly (no silent no-op);
  * BACKUP_ENABLED=false refuses to run.

Run: python backup_test.py
"""
import os
import shutil
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///./backup_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["S3_STUB"] = "true"
os.environ["S3_BUCKET"] = "petabyte-backup-test"
os.environ["ENVIRONMENT"] = "development"
os.environ.pop("BACKUP_ENABLED", None)

for f in ("backup_test.db", "backup_test.db-wal", "backup_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
# clean any prior stub objects for this bucket
_STUB_ROOT = os.path.join(tempfile.gettempdir(), "petabyte-s3-stub", "petabyte-backup-test")
shutil.rmtree(_STUB_ROOT, ignore_errors=True)

import db as dbmod        # noqa: E402
import backup as bk       # noqa: E402
import utils              # noqa: E402

dbmod.init_db()

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# Seed a recognisable row so the dump has real content to protect.
s = dbmod.SessionLocal()
u = dbmod.create_user(s, "backup_canary_user", "pw-correct-horse-battery")
s.close()

# ---- a backup runs end to end ----
s = dbmod.SessionLocal()
res = bk.create_backup(s)
ok("create_backup reports success", res["ok"] is True and res["backup_id"] > 0)
ok("backup uses the sqlite engine here", res["engine"] == "sqlite")
ok("the compressed object is smaller than nothing-claimed (non-empty)", res["compressed_bytes"] > 0)
ok("the raw dump is larger than the gzip (it compressed real bytes)", res["raw_bytes"] >= res["compressed_bytes"])
ok("backup key is namespaced by prefix + environment", res["s3_key"].startswith("db-backups/development/"))
ok("backup key ends .sql.gz", res["s3_key"].endswith(".sql.gz"))

# a DatabaseBackup row was recorded with the integrity hash
rows = dbmod.list_database_backups(s)
ok("exactly one backup row recorded", len(rows) == 1 and rows[0].status == "ok")
ok("row carries the sha256 + s3 uri", bool(rows[0].sha256) and rows[0].s3_uri.startswith("s3://"))

# the object really exists in object storage (the stub dir) and matches the recorded hash
blob = utils.s3_get_bytes(res["s3_key"])
import hashlib  # noqa: E402
ok("stored object hash matches the recorded sha256", hashlib.sha256(blob).hexdigest() == res["sha256"])

# the dump has real schema/content (round-trips the canary), not an empty file
import gzip  # noqa: E402
dump_text = gzip.decompress(blob).decode("utf-8", "replace")
ok("dump contains the users table schema", "users" in dump_text.lower())
ok("dump contains the seeded canary row", "backup_canary_user" in dump_text)

# ---- verify_backup: integrity pass, and tamper detection ----
v = bk.verify_backup(s, res["backup_id"])
ok("verify passes for an untampered backup", v["ok"] is True and v["decompresses"] is True)
ok("verify reports matching hashes", v["expected_sha256"] == v["actual_sha256"])

# corrupt the stored object and re-verify -> must FAIL
utils.s3_put_bytes(res["s3_key"], b"corrupted-not-a-gzip")
v2 = bk.verify_backup(s, res["backup_id"])
ok("verify FAILS when the object is tampered with", v2["ok"] is False)
ok("verify surfaces the hash mismatch", v2["actual_sha256"] != v2["expected_sha256"])
s.close()

# ---- retention prunes oldest successful backups + deletes their objects ----
s = dbmod.SessionLocal()
# make several more backups (each is a distinct object; keep only 2)
for _ in range(3):
    bk.create_backup(s, retention=1000)     # don't prune yet
all_rows = dbmod.list_database_backups(s, limit=100)
ok("multiple backups accumulate", len(all_rows) >= 4)
keys_before = {r.s3_key for r in all_rows if r.status == "ok"}

removed = bk.prune(s, retention=2)
kept = dbmod.list_database_backups(s, limit=100)
kept_ok = [r for r in kept if r.status == "ok"]
ok("retention keeps exactly the newest N", len(kept_ok) == 2)
ok("prune removed the surplus rows", len(removed) == (len(keys_before) - 2))
# the pruned objects are gone from storage
_still = set(utils.s3_list_keys("db-backups/"))
ok("pruned backups' S3 objects are deleted", all(k not in _still for (_id, k) in removed))
ok("kept backups' S3 objects remain", all(r.s3_key in _still for r in kept_ok))

# ---- backup_status feeds the gauge honestly ----
st = bk.backup_status(s)
ok("status reports the retained ok count", st["ok_count"] == 2)
ok("status reports a fresh last-backup age (seconds)", st["last_backup_age_seconds"] is not None and st["last_backup_age_seconds"] >= 0)
ok("status carries a failed_count field", "failed_count" in st)
s.close()

# ---- restore DRILL: a backup restores into a FRESH scratch DB and the money ledger balances ----
# (a backup you have never restored is not a backup — this is the tested-recovery half of DR)
s = dbmod.SessionLocal()
drill = bk.run_restore_drill(s)
ok("restore drill succeeds end to end (backup -> restore -> verify)", drill["ok"] is True)
ok("the RESTORED database reports the money ledger balanced", drill["restored_ledger_balanced"] is True)
ok("restored row counts match the source (users + ledger_entries)",
   drill["restored_counts"]["users"] == drill["source_counts"]["users"]
   and drill["restored_counts"]["ledger_entries"] == drill["source_counts"]["ledger_entries"])
ok("drill restored the sqlite engine here", drill["engine"] == "sqlite")
# the drill must NOT touch the live DB — the canary is still present after it
ok("the drill left the live database intact (canary still present)",
   dbmod.get_user_by_username(s, "backup_canary_user") is not None)
s.close()

# ---- freshness (RPO): a just-made backup is fresh; one older than the RPO reports STALE ----
import datetime as _dt   # noqa: E402
s = dbmod.SessionLocal()
fresh = bk.backup_freshness(s)
ok("a just-created backup is within the default RPO (fresh)",
   fresh["fresh"] is True and fresh["age_seconds"] is not None and fresh["rpo_seconds"] > 0)
# age EVERY successful backup past the default RPO (7200s / 2h) -> the freshness gate must fire
from sqlalchemy import update as _upd   # noqa: E402
s.execute(_upd(dbmod.DatabaseBackup).values(
    created_at=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=3)))
s.commit()
stale = bk.backup_freshness(s)
ok("a backup older than the RPO reports STALE — the monitoring gate fires",
   stale["fresh"] is False and "exceeds RPO" in stale["reason"])
s.close()

# ---- guardrails: misconfig fails loudly, disabled refuses ----
s = dbmod.SessionLocal()
_bucket = os.environ.pop("S3_BUCKET")
raised = False
try:
    bk.create_backup(s)
except Exception:
    raised = True
os.environ["S3_BUCKET"] = _bucket
# a failed attempt still records a status=failed row (alertable) — the upload couldn't run
ok("missing S3_BUCKET raises (no silent success)", raised)
ok("a failed backup is recorded as status=failed",
   any(r.status == "failed" for r in dbmod.list_database_backups(s, limit=100)))

os.environ["BACKUP_ENABLED"] = "false"
_disabled_raised = False
try:
    bk.create_backup(s)
except Exception:
    _disabled_raised = True
os.environ["BACKUP_ENABLED"] = "true"
ok("BACKUP_ENABLED=false refuses to run", _disabled_raised)
s.close()

shutil.rmtree(_STUB_ROOT, ignore_errors=True)
for f in ("backup_test.db", "backup_test.db-wal", "backup_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== backup: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
