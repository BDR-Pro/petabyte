#!/usr/bin/env python3
"""Credit settled NiceHash idle-mining earnings into sellers' unified balances.
Run on a timer (e.g. daily). Idempotent per (worker, period)."""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import SessionLocal, reconcile_idle_earnings
from nicehash import get_worker_earnings

TAKE = float(os.getenv("NICEHASH_TAKE_RATE", "0.10"))


def main():
    period = datetime.date.today().isoformat()
    earnings = get_worker_earnings(period)
    db = SessionLocal()
    try:
        res = reconcile_idle_earnings(db, earnings, TAKE)
        print(f"idle reconcile {period}: {res}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
