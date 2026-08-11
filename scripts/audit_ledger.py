#!/usr/bin/env python3
"""Audit the double-entry ledger and cross-check it against bookings + payouts.

Read-only. Never creates or migrates schema, so it is safe to point at a production
read-only replica. Exits non-zero on ANY discrepancy so it can gate a release
(`make audit-ledger`).

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

    # Sum the matching legs SIGNED so the EXPECTED direction is positive: a leg posted in the
    # wrong direction subtracts instead of adds, so it can never reconcile by magnitude alone.
    # (A plain magnitude sum would let a mis-directed capture/transfer leg pass whenever its
    # absolute amount happened to match the transaction's captured/transferred amount.)
    def legs_sum(reference_id: str, entry_type: str, account: str,
                 expected_direction: str) -> Decimal:
        rows = (session.query(d.LedgerEntry)
                .join(d.LedgerTx, d.LedgerEntry.tx_id == d.LedgerTx.id)
                .filter(d.LedgerTx.reference_id == str(reference_id),
                        d.LedgerEntry.entry_type == entry_type,
                        d.LedgerEntry.account == account).all())
        total = Decimal(0)
        for r in rows:
            amt = d.D(r.amount)
            total += amt if r.direction == expected_direction else -amt
        return total

    # ---- #35 ledger vs bookings ----
    # A capture DEBITS external:payments by captured_amount (money leaving the card processor
    # into the platform), so the signed sum must equal +captured_amount.
    captured_txs = (session.query(d.ComputeTransaction)
                    .filter(d.ComputeTransaction.captured_amount > 0).all())
    for tx in captured_txs:
        got = legs_sum(tx.public_id, "compute_capture", d.EXTERNAL_PAYMENTS, d.DEBIT)
        if got != Decimal(tx.captured_amount):
            fail(f"[vs-bookings] tx {tx.public_id}: captured_amount={tx.captured_amount} "
                 f"but signed compute_capture legs on {d.EXTERNAL_PAYMENTS} sum to {got} "
                 f"(a wrong-direction leg subtracts here)")

    # ---- #36 ledger vs payouts ----
    # A transfer CREDITS external:stripe_transfers by the net (money sent to the connected
    # account), so the signed sum must equal +transferred_amount.
    transferred_txs = (session.query(d.ComputeTransaction)
                       .filter(d.ComputeTransaction.transferred_amount > 0).all())
    for tx in transferred_txs:
        got = legs_sum(tx.public_id, "compute_transfer", d.acct_stripe_payouts(), d.CREDIT)
        if got != Decimal(tx.transferred_amount):
            fail(f"[vs-payouts] tx {tx.public_id}: transferred_amount={tx.transferred_amount} "
                 f"but signed compute_transfer legs on {d.acct_stripe_payouts()} sum to {got} "
                 f"(a wrong-direction leg subtracts here)")

    # ---- #37 ledger vs batch payouts: a PAID batch discharges its seller_payable liability ----
    # A settled batch payout must post a payout_settled DEBIT on the seller's seller_payable equal
    # to the batch total. Without it the batch marks obligations 'paid' but never debits the
    # ledger — the split-brain that let the seller-liability account grow forever.
    paid_batches = [b for b in session.query(d.PayoutBatch).all() if b.state == "paid"]
    for b in paid_batches:
        total = int(getattr(b, "total_amount_minor", 0) or 0)
        if total <= 0:
            continue
        got = legs_sum(b.public_id, "payout_settled", d.acct_seller_payable(b.seller_id), d.DEBIT)
        if got != Decimal(total):
            fail(f"[vs-payouts] paid batch {b.public_id}: total_amount_minor={total} but "
                 f"payout_settled seller_payable DEBIT legs sum to {got} (batch marked paid "
                 f"without debiting the ledger — seller-liability split-brain)")

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
    # READ-ONLY: never call init_db() here. init_db() runs _ensure_columns() (ALTER TABLE /
    # CREATE INDEX), which fails on a read-only replica and mutates the very books we are
    # auditing. The audit must be safe to point at a production replica, so it only reads.
    from sqlalchemy import inspect as _sa_inspect
    have = set(_sa_inspect(d.engine).get_table_names())
    required = {"ledger", "ledger_tx", "compute_transactions", "payout_obligations"}
    missing = required - have
    if missing:
        print(f"::error::ledger schema not present (missing tables: {sorted(missing)}); "
              f"point DATABASE_URL at a populated database", file=sys.stderr)
        print("\nAUDIT NOT RUN: ledger schema absent (this tool is read-only and never "
              "creates schema).")
        return 1
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
