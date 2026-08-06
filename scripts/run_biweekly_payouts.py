#!/usr/bin/env python3
"""Biweekly seller payout run.

Aggregates every seller's MATURED earnings — past the PAYOUT_HOLD_DAYS risk hold
(default 14 days) and NOT under a report/payout hold — into ONE payout per seller and
sends it on the seller's selected rail. Idempotent: a re-run never double-pays.

Schedule this every two weeks (systemd timer / cron). Example — 1st and 15th, noon UTC:

    0 12 1,15 * *  cd /opt/petabyte && python scripts/run_biweekly_payouts.py

(An admin can also trigger a run on demand: POST /admin/payouts/run.)
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lumaris_api"))

from db import SessionLocal            # noqa: E402
import payout_routing as pr            # noqa: E402


def main():
    db = SessionLocal()
    try:
        batches = pr.run_scheduled_payouts(db)
        total = sum(b.total_amount_minor for b in batches)
        print(f"biweekly payouts: {len(batches)} batch(es), total {total} minor units")
        for b in batches:
            print(f"  {b.public_id} seller={b.seller_id} "
                  f"{b.total_amount_minor} {b.source_currency} {b.state} via {b.rail_type}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
