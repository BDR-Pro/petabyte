"""Financial reconciliation CLI — `make reconcile`.

Compares internal ComputeTransaction records + the double-entry ledger against the
Stripe gateway (test-mode fake by default, or the real SDK when configured) and reports
any mismatch. Exit code 0 = consistent; non-zero = STOP and investigate.

Detects: captured != PaymentIntent amount_received, transferred/reversed != Stripe
transfer state, refunded > captured, and the captured == fee + net identity, plus
ledger balance.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "reconcile")
os.environ.setdefault("SERVER_PRIVATE_KEY", "reconcile")

import db as dbmod              # noqa: E402
import stripe_connect as sc     # noqa: E402


def main():
    dbmod.init_db()             # ensure the schema exists (idempotent create_all)
    s = dbmod.SessionLocal()
    try:
        rep = sc.reconcile_all(s)
    finally:
        s.close()
    print(f"reconcile: {rep['transactions_checked']} transactions checked")
    print(f"  ledger_balanced: {rep['ledger_balanced']}")
    if rep["broken_ledger_tx"]:
        print(f"  broken ledger tx: {rep['broken_ledger_tx']}")
    if rep["mismatches"]:
        print(f"  MISMATCHES ({len(rep['mismatches'])}):")
        for m in rep["mismatches"]:
            print(f"    {m['transaction_id']} [{m['status']}]: {'; '.join(m['problems'])}")
    else:
        print("  no mismatches")
    print("RESULT:", "OK" if rep["ok"] else "FAILED")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
