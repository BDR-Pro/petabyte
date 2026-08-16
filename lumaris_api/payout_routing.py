"""Payout routing + aggregation.

Chooses the appropriate, legally-available rail for a seller AT DISBURSEMENT TIME and
aggregates many small obligations into one external payout. Provider-neutral: it reads
the capability dataset and the rail adapters, never hardcoded assumptions.

Guarantees:
  * Sanctioned countries are blocked.
  * A payout never runs without an APPROVED, current compliance decision (fail closed).
  * Stablecoin is never auto-selected — it requires explicit seller consent.
  * One obligation is paid by at most one batch (batched-state guard + FK).
  * The rail choice + reason are stored on the batch (routing_explanation).
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import db as dbmod
from db import (PayoutObligation, PayoutBatch, ComplianceDecision, PayoutMethodRail)
import payout_capabilities as cap
from payout_rails import (PayoutRailType, get_rail, NotImplementedRail, PayoutRailError,
                          PayoutRailUnknownState)

logger = logging.getLogger(__name__)

# Rail send outcomes that mean the money has actually settled to the seller (vs merely
# accepted/queued). Only these move obligations to 'paid'.
_SETTLED_STATUSES = {"paid", "succeeded", "confirmed"}

# Preference order (task's example priority). Stablecoin is gated on consent below.
RAIL_PRIORITY = [
    PayoutRailType.STRIPE_CONNECT,
    PayoutRailType.STRIPE_GLOBAL_PAYOUTS,
    PayoutRailType.STRIPE_STABLECOIN,
    PayoutRailType.CIRCLE_STABLECOIN,
    PayoutRailType.MANUAL_REVIEW,
]
_STABLECOIN = {PayoutRailType.STRIPE_STABLECOIN, PayoutRailType.CIRCLE_STABLECOIN}


class RoutingError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _seller_country(db, seller_id: int):
    """The seller's authoritative payout jurisdiction lives on their ConnectedAccount
    (User has no country column). Returns None when unknown -> select_rail fails closed."""
    ca = (db.query(dbmod.ConnectedAccount)
          .filter(dbmod.ConnectedAccount.user_id == seller_id).first())
    return getattr(ca, "country", None) if ca else None


def compliance_ok(db, seller_id: int) -> tuple[bool, str]:
    """Fail-closed compliance gate. Requires an APPROVED, unexpired sanctions decision.
    Returns (ok, reason)."""
    d = (db.query(ComplianceDecision)
         .filter(ComplianceDecision.seller_id == seller_id,
                 ComplianceDecision.screening_type == "sanctions")
         .order_by(ComplianceDecision.id.desc()).first())
    if not d:
        return False, "no sanctions screening on record (fail closed)"
    if d.decision != "APPROVED":
        return False, f"sanctions decision is {d.decision}"
    exp = d.expires_at
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < _now():
            return False, "sanctions screening expired; rescreen required"
    return True, "approved"


def select_rail(db, seller, *, amount_minor: int, currency: str,
                consent_stablecoin: bool = False) -> dict:
    """Pick the rail for this seller/amount/currency and explain why. Returns a dict
    with rail_type (or None), status, explanation, and blocked reason if any."""
    country = (getattr(seller, "payout_country", None)
               or getattr(seller, "country", None)
               or _seller_country(db, seller.id))
    recipient_type = (getattr(seller, "recipient_type", None) or "individual")

    # 0) FAIL CLOSED on an unknown country. Defaulting to "US" would let a seller with
    # no recorded jurisdiction bypass the sanctions block (the check would never see
    # their real country). No verified country -> no payout.
    if not country:
        return {"rail_type": None, "status": "blocked",
                "explanation": ("Seller has no recorded payout country; blocked until a "
                                "verified country is on file (fail closed)."),
                "blocked": True}

    # 1) hard blocks first
    if cap.is_sanctioned(country):
        return {"rail_type": None, "status": "blocked",
                "explanation": f"Country {country} is sanctioned/prohibited; no payout is permitted.",
                "blocked": True}
    ok, why = compliance_ok(db, seller.id)
    if not ok:
        return {"rail_type": None, "status": "blocked",
                "explanation": f"Compliance not satisfied: {why}.", "blocked": True}

    considered = []
    for rt in RAIL_PRIORITY:
        rail = get_rail(rt)
        c = rail.get_country_capability(country, recipient_type, currency)
        considered.append((rt, c))
        if not c.usable:
            continue
        if c.min_amount_minor and amount_minor < c.min_amount_minor:
            continue
        if c.max_amount_minor and amount_minor > c.max_amount_minor:
            continue
        if rt in _STABLECOIN:
            # never auto-switch a seller to stablecoin
            if not consent_stablecoin:
                continue
            method = (db.query(PayoutMethodRail).filter(
                PayoutMethodRail.seller_id == seller.id,
                PayoutMethodRail.rail_type == rt.value,
                PayoutMethodRail.active == True).first())   # noqa: E712
            if not method or not method.consented_at or method.verification_state != "verified":
                continue
        runner_up = next((cc for r2, cc in considered if cc.usable and r2 != rt), None)
        expl = _explain(rt, c, country, currency, considered)
        return {"rail_type": rt, "status": "active", "capability": c,
                "explanation": expl, "blocked": False}

    # nothing usable
    statuses = "; ".join(f"{rt.value}={c.status.value}" for rt, c in considered)
    return {"rail_type": None, "status": "unsupported",
            "explanation": (f"No active payout rail for {country}/{currency}. "
                            f"Seller is on the waitlist. Rail states: {statuses}."),
            "blocked": False}


def _explain(rt, c, country, currency, considered) -> str:
    skipped = []
    for r2, cc in considered:
        if r2 == rt:
            break
        skipped.append(f"{r2.value} ({cc.status.value})")
    parts = [f"Selected {rt.value} for {country}/{currency}"]
    if skipped:
        parts.append("after skipping " + ", ".join(skipped))
    parts.append(f"bank={c.bank} stablecoin={c.stablecoin}")
    if c.estimated_delivery:
        parts.append(f"est. {c.estimated_delivery}")
    return "; ".join(parts) + "."


# --------------------------------------------------------------- aggregation
def _autonet_clawback_enabled() -> bool:
    """Opt-in flag for clawback auto-netting (read at call time so ops can flip it without a
    redeploy, and tests can toggle it). Default OFF: a recoverable debt stays manual-review, as
    before — turning it on is a founder policy decision (net-against-earnings vs collections)."""
    return os.getenv("PAYOUT_AUTONET_CLAWBACK", "false").strip().lower() in ("1", "true", "yes", "on")


def _apply_clawback_recovery(db, seller_id: int, recovered_minor: int) -> int:
    """After a netted batch SETTLES, mark the seller's batch-path refund clawbacks recovered: the
    recoverable seller_payable debt has now been recouped by paying the seller less. Flips those
    txs from `needs_review` to `reconciled` (the batch-clawback signature is a needs_review tx with
    a refund but no reversible transfer — see stripe_connect.refund) and logs the recovery. The
    ledger was already balanced by the reduced payout DEBIT; this clears the operator flag."""
    txs = (db.query(dbmod.ComputeTransaction)
           .filter(dbmod.ComputeTransaction.seller_id == seller_id,
                   dbmod.ComputeTransaction.reconciliation_status == "needs_review",
                   dbmod.ComputeTransaction.refunded_amount > 0,
                   dbmod.ComputeTransaction.stripe_transfer_id.is_(None))
           .all())
    for t in txs:
        t.reconciliation_status = "reconciled"
        db.add(t)
    db.commit()
    logger.info("clawback auto-netting: recovered %s minor from seller %s's payout; cleared %d "
                "needs_review clawback tx(s)", recovered_minor, seller_id, len(txs))
    return len(txs)


def create_and_send_batch(db, seller, *, currency: str = "usd",
                          min_threshold_minor: int = 0,
                          consent_stablecoin: bool = False,
                          execute: bool = True) -> PayoutBatch | None:
    """Aggregate a seller's AVAILABLE obligations into one batch on the selected rail,
    then (optionally) execute it. Returns the batch, or None if below threshold / no
    obligations. One obligation is included in at most one batch."""
    # Resolve the payment MODE exactly once and use it end to end: obligation filter,
    # batch.mode, and rail execution. TEST and LIVE money never mix in a batch.
    mode = dbmod.payments_mode()
    obligations = dbmod.available_obligations(db, seller.id, currency, mode=mode)
    if not obligations:
        return None
    total = sum(o.net_amount_minor for o in obligations)
    if total < max(min_threshold_minor, 0):
        return None

    decision = select_rail(db, seller, amount_minor=total, currency=currency,
                           consent_stablecoin=consent_stablecoin)
    if decision["blocked"] or not decision["rail_type"]:
        raise RoutingError(decision["explanation"])
    rt = decision["rail_type"]

    # Deterministic idempotency key over the exact requested obligation set + mode, but
    # FIXED-WIDTH (hash) so hundreds of ids can't exceed Stripe's 255-char limit.
    obl_ids = sorted(o.id for o in obligations)
    digest = hashlib.sha256(",".join(map(str, obl_ids)).encode()).hexdigest()[:32]
    base = f"petabyte:batch:{seller.id}:{currency}:{mode}:{digest}"
    # A 'failed' batch is TERMINAL (its obligations were released) — NEVER return it as an
    # idempotent replay, or the released earnings could be aggregated elsewhere while this
    # code hands back a dead batch. Only a non-failed prior batch is a true replay. A
    # legitimate retry re-claims and gets a NEW attempt key so Stripe sees a new request.
    # 'failed' AND 'aborted' are BOTH terminal: their obligations were released, so the
    # batch no longer owns anything and must never be returned as a live idempotent
    # replay. Only a non-terminal prior batch is a true replay. Order deterministically
    # (by id) so live[0] is stable, and count both terminal states toward the attempt no.
    _TERMINAL = ("failed", "aborted")
    prior = (db.query(PayoutBatch)
             .filter(PayoutBatch.idempotency_key.like(base + "%"))
             .order_by(PayoutBatch.id).all())
    live = [b for b in prior if b.state not in _TERMINAL]
    if live:
        return live[0]
    attempt = sum(1 for b in prior if b.state in _TERMINAL)
    key = base if attempt == 0 else f"{base}:r{attempt}"

    batch = PayoutBatch(seller_id=seller.id, rail_type=rt.value, provider=rt.value.split("_")[0],
                        source_currency=currency, destination_currency=currency,
                        total_amount_minor=total, idempotency_key=key, mode=mode,
                        routing_explanation=decision["explanation"], state="created")
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent creator won the unique idempotency_key. Return their batch rather
        # than creating a duplicate / erroring.
        db.rollback()
        existing = db.query(PayoutBatch).filter(PayoutBatch.idempotency_key == key).first()
        if existing:
            return existing
        raise
    db.refresh(batch)
    # claim obligations for THIS batch: only still-available, same mode, unbatched.
    claimed = []
    for o in obligations:
        res = db.execute(dbmod.update(PayoutObligation)
                         .where(PayoutObligation.id == o.id,
                                PayoutObligation.batch_id.is_(None),
                                PayoutObligation.state == "available",
                                PayoutObligation.mode == mode)
                         .values(batch_id=batch.id, state="batched"))
        if res.rowcount == 1:
            claimed.append(o.id)
    if not claimed:
        batch.state = "failed"; batch.failure_reason = "no obligations could be claimed"
        db.add(batch); db.commit()
        return batch
    # RECOMPUTE the total from what we ACTUALLY claimed (a concurrent batch may have won a
    # subset); persist before any send so we can never over-transfer.
    claimed_set = set(claimed)
    claimed_total = sum(o.net_amount_minor for o in obligations if o.id in claimed_set)
    batch.total_amount_minor = claimed_total
    db.add(batch); db.commit()

    # CLAWBACK AUTO-NETTING (opt-in via PAYOUT_AUTONET_CLAWBACK): if a past refund/chargeback on
    # an already-paid job left the seller owing the platform (a recoverable negative seller_payable
    # balance — audit killer #6 recovery), recover it by paying the seller LESS this round instead
    # of waiting for a manual operator. We recover the FULL debt only when this payout can absorb it
    # AND still clear the rail threshold, so a real disbursement always goes out and the ledger's
    # seller_payable settles to zero (the reduced DEBIT posted at settlement clears the debt);
    # otherwise we leave it to accrue against a larger future payout. Default OFF = prior behavior.
    recovered = 0
    if execute and _autonet_clawback_enabled():
        debt = dbmod.seller_recoverable_debt_minor(db, seller.id)
        net_send = claimed_total - debt
        if debt > 0 and net_send >= max(min_threshold_minor, 1):
            recovered = debt
            claimed_total = net_send
            batch.total_amount_minor = claimed_total
            batch.routing_explanation = (
                (batch.routing_explanation or "") +
                f" | auto-netted {recovered} minor of recoverable clawback debt")[:500]
            db.add(batch); db.commit()

    # REVALIDATE eligibility against claimed_total BEFORE sending. If a concurrent claim
    # dropped us below the threshold or the rail's minimum/eligibility, release the
    # claimed obligations and abort WITHOUT calling the rail.
    ineligible = None
    if claimed_total < max(min_threshold_minor, 0):
        ineligible = (f"claimed_total {claimed_total} below threshold {min_threshold_minor} "
                      f"after concurrent claim")
    else:
        recheck = select_rail(db, seller, amount_minor=claimed_total, currency=currency,
                              consent_stablecoin=consent_stablecoin)
        if recheck["blocked"] or recheck["rail_type"] != rt:
            ineligible = (f"rail no longer eligible at claimed_total {claimed_total}: "
                          f"{recheck['explanation']}")
    if ineligible:
        db.execute(dbmod.update(PayoutObligation)
                   .where(PayoutObligation.batch_id == batch.id)
                   .values(batch_id=None, state="available"))
        batch.state = "aborted"; batch.failure_reason = ineligible[:300]
        db.add(batch); db.commit()
        return batch

    if not execute:
        return batch

    result = execute_batch(db, batch)
    # Only mark the clawback recovered once the batch has actually SETTLED (ledger DEBIT posted) —
    # if it aborted/failed and released its obligations, the debt was never recovered.
    if recovered and result is not None and result.state == "paid":
        _apply_clawback_recovery(db, seller.id, recovered)
    return result


def execute_batch(db, batch: PayoutBatch) -> PayoutBatch:
    """Send a created batch via its rail. Idempotent: an already-sent/paid batch is not
    re-sent. Failure handling is outcome-aware:

      * NotImplementedRail / definite PayoutRailError (pre-flight, no money moved):
        release the obligations back to 'available' for a later retry.
      * PayoutRailUnknownState (timeout/network — the send MAY have succeeded): DO NOT
        release. Keep the obligations claimed to this batch and mark it
        'needs_reconciliation'; a retry of the SAME idempotency key is deduped by the
        provider, whereas a different batch would double-pay.
    """
    if batch.state in ("sent", "paid"):
        return batch
    rail = get_rail(PayoutRailType(batch.rail_type))
    carrier = _BatchObligation(batch)
    try:
        ext = rail.send_payout(db, carrier, batch.idempotency_key)
    except PayoutRailUnknownState as e:
        # Ambiguous: money may or may not have moved. Preserve for reconciliation; never
        # release the obligations (that is how the same earnings get paid twice).
        batch.state = "needs_reconciliation"; batch.failure_reason = str(e)[:300]
        db.add(batch); db.commit()
        logger.error("payout batch %s outcome UNKNOWN; left claimed for reconciliation: %s",
                     batch.public_id, e)
        return batch
    except (NotImplementedRail, PayoutRailError) as e:
        # Deterministic failure, no money moved -> safe to release for another attempt.
        batch.state = "failed"; batch.failure_reason = str(e)[:300]
        db.execute(dbmod.update(PayoutObligation)
                   .where(PayoutObligation.batch_id == batch.id)
                   .values(batch_id=None, state="available"))
        db.add(batch); db.commit()
        return batch
    batch.external_id = ext.external_id
    batch.provider_fee_minor = ext.raw.get("provider_fee_minor", 0) if isinstance(ext.raw, dict) else 0
    settled = (ext.status or "").lower() in _SETTLED_STATUSES
    # Batch + obligation state move together in ONE transaction: a crash can never leave
    # the batch advanced while its obligations lag (or vice-versa). Obligations become
    # 'paid' ONLY when the rail reports settlement; otherwise they stay 'batched'
    # (in-transit) until confirm_batch() runs on provider confirmation.
    batch.state = "paid" if settled else "sent"
    db.execute(dbmod.update(PayoutObligation)
               .where(PayoutObligation.batch_id == batch.id)
               .values(state="paid" if settled else "batched"))
    db.add(batch)
    # If the rail settled synchronously, the seller_payable liability is discharged now: add the
    # DEBIT leg to THIS transaction and commit both together, so the ledger can never lag the
    # obligation state after a crash (split-brain fix, now atomic). A batch that only 'sent' posts
    # its leg later in confirm_batch when settlement is confirmed.
    if settled:
        _add_batch_payout_ledger(db, batch)
    _commit_payout_atomic(db, batch, "paid" if settled else "sent",
                          "paid" if settled else "batched")
    return batch


def _add_batch_payout_ledger(db, batch) -> bool:
    """ADD (flush, do NOT commit) the DOUBLE-ENTRY leg for a SETTLED batch payout to the CURRENT
    transaction: DEBIT the seller's seller_payable (the liability recorded at capture) and CREDIT
    the payout clearing account. Mirrors the admin transfer_to_seller post so BOTH payout paths
    keep the ledger's seller-liability truthful. The CALLER commits it in the SAME transaction as
    the paid-state write, so a crash can never leave a 'paid' batch without its ledger entry
    (atomic — this used to be a second, separate commit). Idempotent: returns False (adds nothing)
    if the per-batch leg was already posted. Returns True if it added the leg."""
    total = int(getattr(batch, "total_amount_minor", 0) or 0)
    if total <= 0:
        return False
    key = f"payout_settled:{batch.public_id}"
    if db.query(dbmod.LedgerTx).filter(dbmod.LedgerTx.idempotency_key == key).first():
        return False                      # already posted -> nothing to add (idempotent)
    dbmod.post(db, "payout_batch", legs=[
        (dbmod.acct_seller_payable(batch.seller_id), dbmod.DEBIT, total, batch.seller_id),
        (dbmod.acct_stripe_payouts(),               dbmod.CREDIT, total),
    ], reference_id=batch.public_id, idempotency_key=key,
       description="batch payout settled to seller", entry_type="payout_settled")
    return True                           # flushed, NOT committed — caller commits atomically


def _commit_payout_atomic(db, batch, batch_state: str, obl_state: str) -> None:
    """Commit the paid-state write AND the settled ledger leg TOGETHER (atomic). On the rare
    duplicate-key race — a concurrent settle already posted the idempotent leg — roll back and
    re-apply just the state so the batch still reaches its paid state. Never 500, never a
    ledger/obligation split-brain."""
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.warning("atomic payout commit retried for batch %s (concurrent settle race)",
                       getattr(batch, "public_id", "?"))
        db.query(PayoutBatch).filter(PayoutBatch.id == batch.id).update({"state": batch_state})
        db.execute(dbmod.update(PayoutObligation)
                   .where(PayoutObligation.batch_id == batch.id).values(state=obl_state))
        db.commit()


def confirm_batch(db, batch: PayoutBatch) -> PayoutBatch:
    """Mark a 'sent' batch (and its obligations) 'paid' once the provider confirms
    settlement (webhook / reconciliation). Idempotent; a single transaction."""
    if batch.state == "paid":
        return batch
    if batch.state != "sent":
        raise RoutingError(f"cannot confirm batch in state {batch.state}")
    batch.state = "paid"
    db.execute(dbmod.update(PayoutObligation)
               .where(PayoutObligation.batch_id == batch.id)
               .values(state="paid"))
    db.add(batch)
    # Money actually left to the seller -> add the seller_payable DEBIT to THIS transaction and
    # commit both together (atomic split-brain fix; was a separate best-effort commit).
    _add_batch_payout_ledger(db, batch)
    _commit_payout_atomic(db, batch, "paid", "paid")
    return batch


class _BatchObligation:
    """Adapts a PayoutBatch to the shape a rail's send_payout expects."""
    def __init__(self, batch: PayoutBatch):
        self.id = batch.public_id
        self.batch_id = batch.id
        self.seller_id = batch.seller_id
        self.currency = batch.source_currency
        self.net_amount_minor = batch.total_amount_minor


def seller_balances(db, seller_id: int) -> dict:
    """Pending / available / in-transit / paid / failed, in minor units, for the UI.
    Aggregated in SQL (GROUP BY) rather than loading every obligation into Python."""
    buckets = {"accrued": 0, "available": 0, "batched": 0, "transferring": 0,
               "reconciling": 0, "paid": 0, "reversed": 0, "failed": 0}
    # Scope to the CURRENT payment mode so TEST funds are never shown as LIVE batchable
    # earnings (and vice-versa) — the same mode create_and_send_batch aggregates by.
    mode = dbmod.payments_mode()
    rows = (db.query(PayoutObligation.state,
                     func.coalesce(func.sum(PayoutObligation.net_amount_minor), 0))
            .filter(PayoutObligation.seller_id == seller_id,
                    PayoutObligation.mode == mode)
            .group_by(PayoutObligation.state).all())
    for state, total in rows:
        buckets[state] = buckets.get(state, 0) + int(total or 0)
    return {
        "pending_minor": buckets["accrued"],          # in risk hold
        "available_minor": buckets["available"],
        # claimed by a batch or a direct transfer, or awaiting provider reconciliation:
        # all NON-batchable and in-flight.
        "in_transit_minor": buckets["batched"] + buckets["transferring"] + buckets["reconciling"],
        "paid_minor": buckets["paid"],
        "reversed_minor": buckets["reversed"],
        "failed_minor": buckets["failed"],
    }


def run_scheduled_payouts(db, *, currency: str = "usd", min_threshold_minor: int = 0,
                          consent_stablecoin: bool = False, execute: bool = True) -> list:
    """The biweekly payout run. For every seller with matured, available earnings (past
    the risk hold and NOT under an open report/payout hold), aggregate ALL of them into
    ONE payout and send it. Returns the PayoutBatch objects created.

    This is what turns "hold each job's earnings for 14 days, then pay the accumulated
    total once" into a single scheduled action. Idempotent per obligation set (a re-run
    on the same day returns the same live batch, never a second payout)."""
    mode = dbmod.payments_mode()
    dbmod.promote_due_obligations(db)          # mature everything due (hold-aware)
    seller_ids = [r[0] for r in (db.query(PayoutObligation.seller_id)
                  .filter(PayoutObligation.state == "available",
                          PayoutObligation.batch_id.is_(None),
                          PayoutObligation.mode == mode)
                  .distinct().all())]
    batches = []
    for sid in seller_ids:
        if dbmod.payout_hold_active(db, sid):   # belt-and-suspenders (promote already skips)
            continue
        seller = dbmod.get_user_by_id(db, sid)
        if not seller:
            continue
        try:
            b = create_and_send_batch(db, seller, currency=currency,
                                      min_threshold_minor=min_threshold_minor,
                                      consent_stablecoin=consent_stablecoin, execute=execute)
            if b is not None:
                batches.append(b)
        except RoutingError as e:
            logger.warning("scheduled payout skipped seller %s: %s", sid, e)
    logger.info("scheduled payouts: %d batch(es) across %d seller(s) with available earnings",
                len(batches), len(seller_ids))
    return batches
