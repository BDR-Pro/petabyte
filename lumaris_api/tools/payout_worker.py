#!/usr/bin/env python3
"""Payout worker: fire due schedules, then send queued payouts. Run on a timer
(systemd timer / cron, e.g. every 5 min)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import (SessionLocal, run_due_schedules, pending_payouts, set_payout_status,
                SellerPayoutMethod)
from payout_providers import process_payouts
import notifications


def main():
    db = SessionLocal()
    try:
        fired = run_due_schedules(db)
        def methods_by_id(mid):
            return db.query(SellerPayoutMethod).filter(SellerPayoutMethod.id == mid).first()
        def on_status(d, p, st, ref, reason):
            evt = {"confirmed": "payout.confirmed", "sent": "payout.confirmed",
                   "failed": "payout.failed"}.get(st)
            if evt:
                notifications.notify(d, p.user_id, evt, amount=p.amount_usd,
                                     kind=p.kind, ref=ref or "-", reason=reason or "")
        sent = process_payouts(db, pending_payouts(db), set_payout_status,
                               methods_by_id, on_status=on_status)
        print(f"schedules fired={fired} payouts processed={sent}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
