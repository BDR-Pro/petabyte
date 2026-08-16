#!/usr/bin/env python3
"""Take a disaster-recovery backup of the platform database and upload it to S3.

Designed to be driven by cron or a systemd timer on the API host, where DATABASE_URL and the
S3_* credentials are already in the environment:

    # /etc/cron.d/petabyte-db-backup  — hourly, with the app's env file
    0 * * * *  petabyte  . /etc/lumaris/lumaris.env && \
        /opt/petabyte/venv/bin/python /opt/petabyte/scripts/backup_database.py >> /var/log/petabyte-backup.log 2>&1

Exits 0 on success, non-zero on failure (so cron / the timer records the failure and a
'no successful backup in N hours' alert can fire off the recorded status=failed row + the
petabyte_db_backup_last_age_seconds gauge). Set S3_STUB=true to dry-run against a local dir.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Back up the platform database to S3.")
    ap.add_argument("--retention", type=int, default=None,
                    help="keep only the newest N successful backups (default: BACKUP_RETENTION or 30)")
    ap.add_argument("--verify", action="store_true",
                    help="after uploading, download the object and re-check its SHA-256")
    ap.add_argument("--check-fresh", action="store_true",
                    help="don't back up — just check the newest successful backup is within the "
                         "RPO (BACKUP_RPO_SECONDS). Exits non-zero when stale, for monitoring/cron.")
    args = ap.parse_args()

    import db as dbmod          # noqa: E402 — after sys.path setup
    import backup as bk         # noqa: E402

    if not bk.backups_enabled():
        sys.stderr.write("database backups are disabled (BACKUP_ENABLED=false)\n")
        return 2

    if args.check_fresh:
        s = dbmod.SessionLocal()
        try:
            fresh = bk.backup_freshness(s)
        finally:
            s.close()
        print(json.dumps(fresh, sort_keys=True))
        if not fresh.get("fresh"):
            sys.stderr.write(f"BACKUP STALE: {fresh.get('reason')}\n")
            return 4
        return 0

    s = dbmod.SessionLocal()
    try:
        summary = bk.create_backup(s, retention=args.retention)
        if args.verify:
            summary["verify"] = bk.verify_backup(s, summary["backup_id"])
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"BACKUP FAILED: {e}\n")
        return 1
    finally:
        s.close()

    print(json.dumps(summary, sort_keys=True))
    if args.verify and not summary.get("verify", {}).get("ok"):
        sys.stderr.write("BACKUP VERIFY FAILED — object hash mismatch\n")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
