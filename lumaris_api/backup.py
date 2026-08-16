"""backup.py — platform DATABASE disaster-recovery backups to object storage (AWS S3 / S3-compatible).

This is the platform's own database (users, bookings, the money ledger, listings), NOT a buyer's
job volume — those are `Checkpoint`s uploaded by the node (see /jobs/checkpoint). Here the API,
which holds the object-storage credentials, dumps the whole database, compresses + hashes it, and
writes ONE encrypted object to S3, then prunes old backups to a retention window.

Flow:  dump (pg_dump | sqlite iterdump) -> gzip -> sha256 -> s3://<bucket>/<prefix>/<env>/<ts>-<sha8>.sql.gz
        -> record a DatabaseBackup row (reference + integrity hash) -> prune beyond BACKUP_RETENTION.

Honest properties:
  * Engine-aware: Postgres via `pg_dump` (plain SQL); SQLite via `iterdump()` (portable SQL). Both
    restore by replaying SQL — see docs/BACKUP_RUNBOOK.md.
  * Encrypted at rest by S3 (S3_SSE, default AES256). The dump is NOT additionally client-encrypted;
    the object is a full logical dump — treat the bucket as sensitive and lock it down (private,
    versioned, restricted IAM). This is a documented limitation, not a hidden one.
  * Integrity: the SHA-256 of the compressed object is stored, so a restore can be verified byte-for-byte.
  * Every attempt is recorded — a FAILED dump/upload writes a status=failed row so monitoring can
    alert on "no successful backup in N hours" (backup_status()).
  * S3_STUB writes to a local directory (utils.s3_*), so tests and offline dev need no AWS.

Trigger it from cron / a systemd timer via scripts/backup_database.py, or POST /admin/backups/run.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

import db as dbmod
import utils


def backups_enabled() -> bool:
    return os.getenv("BACKUP_ENABLED", "true").lower() != "false"


def _prefix() -> str:
    return (os.getenv("BACKUP_S3_PREFIX", "db-backups") or "db-backups").strip("/")


def _retention() -> int:
    try:
        return max(0, int(os.getenv("BACKUP_RETENTION", "30")))
    except (TypeError, ValueError):
        return 30


def _environment() -> str:
    return os.getenv("ENVIRONMENT", "development")


# ── dump ────────────────────────────────────────────────────────────────────────────────

def _pg_dump_bin() -> str | None:
    """Locate pg_dump: explicit PG_DUMP_BIN, then PATH, then the usual packaged locations."""
    explicit = os.getenv("PG_DUMP_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    found = shutil.which("pg_dump")
    if found:
        return found
    import glob
    for cand in sorted(glob.glob("/usr/lib/postgresql/*/bin/pg_dump"), reverse=True):
        return cand
    for cand in ("/usr/pgsql-16/bin/pg_dump", "/usr/local/bin/pg_dump", "/usr/bin/pg_dump"):
        if os.path.exists(cand):
            return cand
    return None


def _pg_conn_uri(url) -> str:
    """Build a libpq connection URI (postgresql://…) from the SQLAlchemy URL, dropping the
    +psycopg2 driver suffix so pg_dump accepts it."""
    from urllib.parse import quote
    user = url.username or ""
    pw = (":" + quote(str(url.password), safe="")) if url.password else ""
    auth = (quote(user, safe="") + pw + "@") if user else ""
    host = url.host or "localhost"
    port = (":" + str(url.port)) if url.port else ""
    name = url.database or ""
    return f"postgresql://{auth}{host}{port}/{name}"


def _dump_postgres(url) -> bytes:
    binp = _pg_dump_bin()
    if not binp:
        raise RuntimeError("pg_dump not found on PATH — install postgresql-client or set PG_DUMP_BIN")
    timeout = int(os.getenv("BACKUP_DUMP_TIMEOUT_S", "1800"))
    args = [binp, "--no-owner", "--no-privileges", "--format=plain", "--dbname=" + _pg_conn_uri(url)]
    proc = subprocess.run(args, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[:500]
        raise RuntimeError(f"pg_dump failed (exit {proc.returncode}): {err}")
    if not proc.stdout:
        raise RuntimeError("pg_dump produced an empty dump")
    return proc.stdout


def _dump_sqlite(url) -> bytes:
    import sqlite3
    path = url.database
    if not path or not os.path.exists(path):
        raise RuntimeError(f"sqlite database file not found: {path!r}")
    con = sqlite3.connect(path)
    try:
        return ("\n".join(con.iterdump()) + "\n").encode("utf-8")
    finally:
        con.close()


def dump_database() -> tuple[bytes, str]:
    """Return (raw_sql_dump_bytes, engine_name) for the configured database."""
    url = dbmod.engine.url
    backend = url.get_backend_name()
    if backend.startswith("postgres"):
        return _dump_postgres(url), "postgresql"
    if backend.startswith("sqlite"):
        return _dump_sqlite(url), "sqlite"
    raise RuntimeError(f"unsupported database engine for backup: {backend}")


# ── create / prune / verify / status ──────────────────────────────────────────────────────

def create_backup(db, *, retention: int = None, prefix: str = None) -> dict:
    """Dump -> gzip -> sha256 -> upload -> record -> prune. Returns a summary. On dump/upload
    failure, records a status=failed row (so 'no recent backup' alerts fire) and re-raises."""
    if not backups_enabled():
        raise RuntimeError("database backups are disabled (BACKUP_ENABLED=false)")
    env = _environment()
    pfx = (prefix if prefix is not None else _prefix()).strip("/")

    try:
        raw, engine = dump_database()
    except Exception as e:
        dbmod.record_database_backup(db, s3_key="", s3_uri=None, engine="unknown",
                                     environment=env, size_bytes=0, sha256=None,
                                     status="failed", error=f"dump failed: {e}")
        raise

    blob = gzip.compress(raw, compresslevel=6)
    sha = hashlib.sha256(blob).hexdigest()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{pfx}/{env}/{ts}-{sha[:8]}.sql.gz"

    try:
        uri = utils.s3_put_bytes(key, blob, content_type="application/gzip")
    except Exception as e:
        dbmod.record_database_backup(db, s3_key=key, s3_uri=None, engine=engine,
                                     environment=env, size_bytes=len(blob), sha256=sha,
                                     status="failed", error=f"upload failed: {e}")
        raise

    row = dbmod.record_database_backup(db, s3_key=key, s3_uri=uri, engine=engine, environment=env,
                                       size_bytes=len(blob), sha256=sha, status="ok")
    pruned = prune(db, retention)
    return {
        "ok": True, "backup_id": row.id, "s3_uri": uri, "s3_key": key, "engine": engine,
        "environment": env, "raw_bytes": len(raw), "compressed_bytes": len(blob),
        "sha256": sha, "pruned": len(pruned),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def prune(db, retention: int = None) -> list:
    """Delete DB rows + S3 objects for successful backups beyond the newest `retention`."""
    keep = retention if retention is not None else _retention()
    removed = dbmod.prune_database_backups(db, keep)
    for _id, key in removed:
        if not key:
            continue
        try:
            utils.s3_delete(key)
        except Exception:
            pass   # object already gone / transient S3 error — the DB row is the source of truth
    return removed


def verify_backup(db, backup_id: int) -> dict:
    """Download a backup object and check its SHA-256 + that it decompresses (integrity)."""
    row = db.query(dbmod.DatabaseBackup).filter(dbmod.DatabaseBackup.id == backup_id).first()
    if not row:
        raise ValueError("no such backup")
    if row.status != "ok" or not row.s3_key:
        return {"ok": False, "reason": "backup did not complete (no object to verify)",
                "backup_id": backup_id, "status": row.status}
    blob = utils.s3_get_bytes(row.s3_key)
    actual = hashlib.sha256(blob).hexdigest()
    try:
        gzip.decompress(blob)
        decompresses = True
    except Exception:
        decompresses = False
    return {"ok": bool(actual == row.sha256 and decompresses), "backup_id": backup_id,
            "expected_sha256": row.sha256, "actual_sha256": actual,
            "size_bytes": len(blob), "decompresses": decompresses}


def _rpo_seconds() -> int:
    """Recovery Point Objective: the maximum acceptable age of the newest successful backup.
    Default 7200s (2h) — 2× the documented hourly backup cadence. Alert/monitoring should fire
    when the last-backup age exceeds this."""
    try:
        return max(1, int(os.getenv("BACKUP_RPO_SECONDS", "7200")))
    except (TypeError, ValueError):
        return 7200


def backup_freshness(db, *, rpo_seconds: int = None) -> dict:
    """Is the newest successful backup within the RPO? Returns {fresh, age_seconds, rpo_seconds,
    reason}. `fresh=False` (with reason) means monitoring/CI should alert — either no backup has
    ever succeeded, or the newest is older than the RPO."""
    rpo = rpo_seconds if rpo_seconds is not None else _rpo_seconds()
    st = backup_status(db)
    age = st.get("last_backup_age_seconds")
    if age is None:
        return {"fresh": False, "age_seconds": None, "rpo_seconds": rpo,
                "reason": "no successful backup yet"}
    fresh = age <= rpo
    return {"fresh": bool(fresh), "age_seconds": age, "rpo_seconds": rpo,
            "reason": ("ok" if fresh else f"last successful backup is {int(age)}s old, exceeds RPO {rpo}s")}


# ── restore + disaster-recovery drill ──────────────────────────────────────────────────────
# A backup you have never restored is not a backup. These turn the documented manual restore into
# a *programmatic, tested* one, and a DRILL that proves recovery end to end: dump -> store ->
# restore into a FRESH scratch DB -> verify the money ledger still balances and row counts match.

def _fetch_backup_sql(db, backup_id: int = None) -> tuple[str, "dbmod.DatabaseBackup"]:
    """Download the target (or newest successful) backup, verify its SHA-256, and return
    (decompressed_sql_text, row). Refuses to restore an object whose hash doesn't match the
    recorded integrity hash."""
    B = dbmod.DatabaseBackup
    q = db.query(B).filter(B.status == "ok", B.s3_key.isnot(None))
    row = (q.filter(B.id == backup_id).first() if backup_id is not None
           else q.order_by(B.id.desc()).first())
    if not row:
        raise RuntimeError("no successful backup available to restore")
    blob = utils.s3_get_bytes(row.s3_key)
    if hashlib.sha256(blob).hexdigest() != row.sha256:
        raise RuntimeError(f"backup #{row.id} FAILED integrity check (sha256 mismatch) — refusing to restore")
    return gzip.decompress(blob).decode("utf-8", "replace"), row


def _restore_sqlite(target_path: str, sql_text: str) -> None:
    import sqlite3
    if os.path.exists(target_path):
        os.remove(target_path)          # always restore into a FRESH file
    con = sqlite3.connect(target_path)
    try:
        con.executescript(sql_text)
        con.commit()
    finally:
        con.close()


def _restore_postgres(target_url, sql_text: str) -> None:
    """Replay a plain-SQL pg_dump into an EXISTING (empty) target database via psql."""
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql not found on PATH — install postgresql-client to run a restore/drill")
    uri = _pg_conn_uri(target_url)
    timeout = int(os.getenv("BACKUP_DUMP_TIMEOUT_S", "1800"))
    proc = subprocess.run([psql, "-v", "ON_ERROR_STOP=1", "--dbname=" + uri],
                          input=sql_text.encode("utf-8"), capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"psql restore failed (exit {proc.returncode}): {err}")


def _prepare_pg_scratch():
    """(Re)create a scratch database next to the source and return its SQLAlchemy URL string.
    Honors RESTORE_DRILL_TARGET_URL if set (CI provides a dedicated scratch DB)."""
    override = os.getenv("RESTORE_DRILL_TARGET_URL")
    if override:
        return override
    from sqlalchemy.engine import make_url
    src = dbmod.engine.url
    scratch = (src.database or "petabyte") + "_restore_drill"
    admin = make_url(str(src)).set(database="postgres")
    psql = shutil.which("psql")
    if not psql:
        raise RuntimeError("psql not found on PATH — install postgresql-client or set RESTORE_DRILL_TARGET_URL")
    admin_uri = _pg_conn_uri(admin)
    for stmt in (f'DROP DATABASE IF EXISTS "{scratch}"', f'CREATE DATABASE "{scratch}"'):
        p = subprocess.run([psql, "-v", "ON_ERROR_STOP=1", "--dbname=" + admin_uri, "-c", stmt],
                           capture_output=True, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"scratch DB setup failed: {(p.stderr or b'').decode('utf-8','replace')[:300]}")
    return str(make_url(str(src)).set(database=scratch))


def _restored_integrity(target_url_str: str) -> dict:
    """Open the RESTORED database and prove it's usable: the money ledger still balances and the
    key tables carry rows. Uses a throwaway engine bound to the scratch DB (never the live one)."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker
    eng = sa.create_engine(target_url_str)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    s = Session()
    try:
        balanced, broken = dbmod.ledger_is_balanced(s)
        counts = {
            "users": s.query(dbmod.User).count(),
            "ledger_entries": s.query(dbmod.LedgerEntry).count(),
        }
        return {"ledger_balanced": bool(balanced), "broken": list(broken or []), "row_counts": counts}
    finally:
        s.close()
        eng.dispose()


def run_restore_drill(db, *, keep: bool = False, target_url: str = None) -> dict:
    """Disaster-recovery DRILL: take a fresh backup, restore it into a FRESH scratch database, and
    prove the restore is usable — the money ledger balances and row counts match the source. This
    is the tested half of DR (a backup that has never been restored is not recovery). Returns a
    report; `ok=False` means the restore is broken and must be investigated before you'd trust it.

    Non-destructive: never touches the live database — it only restores into a throwaway scratch
    DB (temp SQLite file, or a `<db>_restore_drill` Postgres DB / RESTORE_DRILL_TARGET_URL)."""
    summary = create_backup(db)                          # full chain: prove the STORED object restores
    sql_text, row = _fetch_backup_sql(db, summary["backup_id"])
    engine_name = row.engine
    src_counts = {"users": db.query(dbmod.User).count(),
                  "ledger_entries": db.query(dbmod.LedgerEntry).count()}
    src_balanced, _ = dbmod.ledger_is_balanced(db)

    cleanup_path = None
    if engine_name == "sqlite":
        if target_url is None:
            fd, path = tempfile.mkstemp(prefix="pb_restore_drill_", suffix=".db")
            os.close(fd)
            target_url = f"sqlite:///{path}"
            cleanup_path = path
        else:
            cleanup_path = target_url.replace("sqlite:///", "")
        _restore_sqlite(cleanup_path, sql_text)
    elif engine_name == "postgresql":
        target_url = target_url or _prepare_pg_scratch()
        from sqlalchemy.engine import make_url
        _restore_postgres(make_url(target_url), sql_text)
    else:
        raise RuntimeError(f"restore drill unsupported for engine: {engine_name}")

    integ = _restored_integrity(target_url)
    ok = bool(integ["ledger_balanced"]
              and integ["row_counts"]["users"] == src_counts["users"]
              and integ["row_counts"]["ledger_entries"] == src_counts["ledger_entries"])
    report = {
        "ok": ok, "engine": engine_name, "backup_id": row.id,
        "source_ledger_balanced": bool(src_balanced),
        "restored_ledger_balanced": integ["ledger_balanced"],
        "source_counts": src_counts, "restored_counts": integ["row_counts"],
        "restored_broken_tx": integ["broken"],
    }
    if cleanup_path and not keep and engine_name == "sqlite":
        try:
            os.remove(cleanup_path)
        except OSError:
            pass
    return report


def backup_status(db) -> dict:
    """Health of the backup subsystem: latest successful backup + its age, counts, total size.
    Feeds the Prometheus 'age of last successful backup' gauge and the admin view."""
    from sqlalchemy import func
    B = dbmod.DatabaseBackup
    latest = dbmod.latest_database_backup(db)
    ok_count = db.query(func.count(B.id)).filter(B.status == "ok").scalar() or 0
    failed_count = db.query(func.count(B.id)).filter(B.status == "failed").scalar() or 0
    total_bytes = db.query(func.coalesce(func.sum(B.size_bytes), 0)).filter(B.status == "ok").scalar() or 0
    age = None
    if latest and latest.created_at:
        created = latest.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - created).total_seconds())
    return {
        "enabled": backups_enabled(),
        "retention": _retention(),
        "prefix": _prefix(),
        "ok_count": int(ok_count),
        "failed_count": int(failed_count),
        "total_bytes": int(total_bytes),
        "last_backup_id": (latest.id if latest else None),
        "last_backup_at": (latest.created_at.isoformat() if latest and latest.created_at else None),
        "last_backup_engine": (latest.engine if latest else None),
        "last_backup_age_seconds": (round(age, 1) if age is not None else None),
    }
