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
