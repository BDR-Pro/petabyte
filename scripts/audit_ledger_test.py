#!/usr/bin/env python3
"""Offline test for scripts/audit_ledger.py — proves the reconciliation is SIGN-AWARE.

Finding #9: a plain magnitude sum of a transaction's capture/transfer legs lets a
WRONG-DIRECTION leg reconcile whenever its absolute amount happens to match the
transaction's captured/transferred amount. This test builds one correct capture and one
mis-directed capture (the external-payments leg posted CREDIT instead of DEBIT — the
transaction still BALANCES, so the balance/zero-sum checks alone would miss it) and asserts
that the audit passes the first and FAILS the second.

Run: python scripts/audit_ledger_test.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB = os.path.join(ROOT, "_audit_ledger_test.db")
# Force an isolated throwaway SQLite DB (never inherit an external DATABASE_URL).
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ.setdefault("SECRET_KEY", "audit-test")
os.environ.setdefault("SERVER_PRIVATE_KEY", "audit-test")

for _f in (_DB, _DB + "-wal", _DB + "-shm"):
    try:
        os.remove(_f)
    except OSError:
        pass

sys.path.insert(0, os.path.join(ROOT, "lumaris_api"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import db as d          # noqa: E402
import audit_ledger     # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _run_audit(session) -> list:
    """Run one audit pass and return the list of problems it recorded."""
    audit_ledger.problems = []
    audit_ledger.audit(session)
    return list(audit_ledger.problems)


# The test (unlike the read-only prod audit) is allowed to CREATE its schema.
d.init_db()
s = d.SessionLocal()

# Real parent rows: SQLite FK enforcement is ON in this codebase, so the transaction's
# buyer/seller/spec must exist.
_buyer = d.create_user(s, "audit_buyer", "pw-x")
_seller = d.create_user(s, "audit_seller", "pw-x")
_spec = d.save_specs(s, _seller, {"cpu": 4, "ram": 16, "duration": 24, "price_per_hour": 1.0,
                                  "gpu_model": "NVIDIA L4", "gpu_count": 1, "vram_gb": 24,
                                  "units": 1, "region": "us-east", "country": "US"})
s.commit()
_SELLER_PAYABLE = d.acct_seller_payable(_seller.id)


def _mk_tx(pub, captured):
    tx = d.ComputeTransaction(public_id=pub, buyer_id=_buyer.id, seller_id=_seller.id,
                              spec_id=_spec.id, pricing_snapshot="{}", captured_amount=captured,
                              status="PAYMENT_CAPTURED", mode="test")
    s.add(tx)
    s.commit()
    return tx


# ---- a CORRECT capture: external:payments DEBITED by captured_amount -> reconciles ----
_mk_tx("ctx_ok", 1000)
d.post(s, "compute_transaction", legs=[
    (d.EXTERNAL_PAYMENTS_MINOR, d.DEBIT, 1000),
    (d.PLATFORM_REVENUE_MINOR, d.CREDIT, 100),
    (_SELLER_PAYABLE, d.CREDIT, 900),
], reference_id="ctx_ok", entry_type="compute_capture")
s.commit()

problems = _run_audit(s)
ok("a correctly-directed capture reconciles (no problems)", problems == [])

# ---- a WRONG-DIRECTION capture: external:payments CREDITED (should be DEBIT) ----
# The transaction still balances (debits == credits), so the per-tx balance and global
# zero-sum checks pass; only a sign-aware reconciliation can catch it.
_mk_tx("ctx_bad", 1000)
d.post(s, "compute_transaction", legs=[
    (d.EXTERNAL_PAYMENTS_MINOR, d.CREDIT, 1000),          # <-- wrong direction, same magnitude
    (d.PLATFORM_REVENUE_MINOR, d.DEBIT, 100),
    (_SELLER_PAYABLE, d.DEBIT, 900),
], reference_id="ctx_bad", entry_type="compute_capture")
s.commit()

# sanity: the ledger as a whole still balances, so this is NOT caught by the balance check.
balanced, broken = d.ledger_is_balanced(s)
ok("the mis-directed transaction still BALANCES (balance check alone would miss it)",
   balanced and not broken)

problems = _run_audit(s)
ok("a wrong-direction capture leg is REJECTED by the sign-aware reconciliation",
   any("ctx_bad" in p and "vs-bookings" in p for p in problems))
ok("the correctly-directed capture is NOT falsely flagged",
   not any("ctx_ok" in p for p in problems))

s.close()
for _f in (_DB, _DB + "-wal", _DB + "-shm"):
    try:
        os.remove(_f)
    except OSError:
        pass

print(f"\n=== audit_ledger: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
