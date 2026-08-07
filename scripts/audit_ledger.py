#!/usr/bin/env python3
"""Audit the double-entry ledger and cross-check it against bookings + payouts.

Read-only. Exits non-zero on ANY discrepancy so it can gate a release (`make audit-ledger`).

Checks:
  #34 integrity   — every ledger transaction balances (debits == credits) and the whole
                    ledger sums to zero; no orphan entry (an entry with no parent LedgerTx).
  #35 vs bookings — every captured ComputeTransaction has compute_capture legs on the
                    external-payments account whose sum equals its captured_amount.
  #36 vs payouts  — every transferred ComputeTransaction has compute_transfer legs whose
                    sum equals its transferred_amount; every PayoutObligation points at a
                    real transaction and carries a non-negative net amount.

Run:
    python scripts/audit_ledger.py           # uses DATABASE_URL (sqlite:///./_audit.db default)
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./_audit.db")
os.environ.setdefault("SECRET_KEY", "audit")
os.environ.setdefault("SERVER_PRIVATE_KEY", "audit")

import db as d  # noqa: E402

problems: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def audit(session) -> None:
    # ---- #34 integrity: per-tx balance + global zero-sum ----
    ok_bal, broken = d.ledger_is_balanced(session)
    if not ok_bal:
        if broken:
            fail(f"[integrity] {len(broken)} unbalanced ledger tx (debits != credits): "
                 f"{broken[:20]}{'…' if len(broken) > 20 else ''}")
        else:
            fail("[integrity] ledger does not sum to zero across all entries")

    # orphan entries: an entry whose tx_id has no parent LedgerTx row.
    tx_ids = {t.id for t in session.query(d.LedgerTx).all()}
    orphans = [e.id for e in session.query(d.LedgerEntry).all() if e.tx_id not in tx_ids]
    if orphans:
        fail(f"[integrity] {len(orphans)} orphan ledger entries (no parent tx): "
             f"{orphans[:20]}{'…' if len(orphans) > 20 else ''}")

    # index legs by (reference_id, entry_type, account) -> summed signed-by-direction amount
    def legs_sum(reference_id: str, entry_type: str, account: str) -> Decimal:
        rows = (session.query(d.LedgerEntry)
                .join(d.LedgerTx, d.LedgerEntry.tx_id == d.LedgerTx.id)
                .filter(d.LedgerTx.reference_id == str(reference_id),
                        d.LedgerEntry.entry_type == entry_type,
                        d.LedgerEntry.account == account).all())
        return sum((d.D(r.amount) for r in rows), Decimal(0))

    # ---- #35 ledger vs bookings ----
    captured_txs = (session.query(d.ComputeTransaction)
                    .filter(d.ComputeTransaction.captured_amount > 0).all())
    for tx in captured_txs:
        got = legs_sum(tx.public_id, "compute_capture", d.EXTERNAL_PAYMENTS)
        if got != Decimal(tx.captured_amount):
            fail(f"[vs-bookings] tx {tx.public_id}: captured_amount={tx.captured_amount} "
                 f"but compute_capture ledger legs sum to {got}")

    # ---- #36 ledger vs payouts ----
    transferred_txs = (session.query(d.ComputeTransaction)
                       .filter(d.ComputeTransaction.transferred_amount > 0).all())
    for tx in transferred_txs:
        got = legs_sum(tx.public_id, "compute_transfer", d.acct_stripe_payouts())
        if got != Decimal(tx.transferred_amount):
            fail(f"[vs-payouts] tx {tx.public_id}: transferred_amount={tx.transferred_amount} "
                 f"but compute_transfer ledger legs sum to {got}")

    valid_tx_ids = {t.id for t in session.query(d.ComputeTransaction).all()}
    for ob in session.query(d.PayoutObligation).all():
        if ob.compute_tx_id is not None and ob.compute_tx_id not in valid_tx_ids:
            fail(f"[vs-payouts] payout obligation {ob.id} references missing "
                 f"compute_tx_id={ob.compute_tx_id}")
        if (ob.net_amount_minor or 0) < 0:
            fail(f"[vs-payouts] payout obligation {ob.id} has negative net "
                 f"({ob.net_amount_minor})")

    counts = {
        "ledger_tx": session.query(d.LedgerTx).count(),
        "ledger_entries": session.query(d.LedgerEntry).count(),
        "compute_tx": session.query(d.ComputeTransaction).count(),
        "captured_tx": len(captured_txs),
        "transferred_tx": len(transferred_txs),
        "payout_obligations": session.query(d.PayoutObligation).count(),
    }
    print("=== ledger audit ===")
    print("  " + " · ".join(f"{k}={v}" for k, v in counts.items()))


def main() -> int:
    d.init_db()
    session = d.SessionLocal()
    try:
        audit(session)
    finally:
        session.close()
    if problems:
        for p in problems:
            print(f"::error::{p}", file=sys.stderr)
        print(f"\nAUDIT FAILED: {len(problems)} discrepancy(ies).")
        return 1
    print("\nOK: ledger balances; bookings and payouts reconcile with the ledger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
