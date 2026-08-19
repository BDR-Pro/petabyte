#!/usr/bin/env python3
"""Disaster-recovery RESTORE DRILL — prove a backup can actually be restored.

A backup you have never restored is not a backup. This takes a fresh backup, restores it into a
FRESH scratch database (never the live one), and verifies the restore is usable: the money ledger
still balances and row counts match the source. Exits non-zero if the restore is broken — wire it
into CI and/or a periodic timer so a silently-corrupt backup is caught BEFORE you need it.

    # against the live DB's engine (SQLite dev, or Postgres if DATABASE_URL is set)
    python scripts/restore_drill.py

    # CI (Postgres): point at a dedicated scratch DB so nothing production-shaped is touched
    RESTORE_DRILL_TARGET_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/drill \
        python scripts/restore_drill.py

Env: S3_STUB=true restores from a local dir (offline). RESTORE_DRILL_TARGET_URL overrides the
scratch target (else: a temp SQLite file, or a `<db>_restore_drill` Postgres DB created via psql).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a DR restore drill (backup -> restore -> verify).")
    ap.add_argument("--keep", action="store_true", help="keep the scratch DB after the drill (debug)")
    ap.add_argument("--target-url", default=None, help="explicit scratch DB URL (else auto)")
    args = ap.parse_args()

    import db as dbmod          # noqa: E402 — after sys.path setup
    import backup as bk         # noqa: E402

    if not bk.backups_enabled():
        sys.stderr.write("database backups are disabled (BACKUP_ENABLED=false)\n")
        return 2

    s = dbmod.SessionLocal()
    try:
        report = bk.run_restore_drill(s, keep=args.keep, target_url=args.target_url)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"RESTORE DRILL FAILED: {e}\n")
        return 1
    finally:
        s.close()

    print(json.dumps(report, sort_keys=True))
    if not report.get("ok"):
        sys.stderr.write("RESTORE DRILL FAILED — restored DB did not verify "
                         "(ledger imbalance or row-count mismatch)\n")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
