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
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

import db as dbmod
from db import (PayoutObligation, PayoutBatch, ComplianceDecision, PayoutMethodRail,
                get_user_by_id)
import payout_capabilities as cap
from payout_rails import (PayoutRailType, RecipientType, get_rail, CapabilityStatus,
                          NotImplementedRail, PayoutRailError, PayoutRailUnknownState)

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
def create_and_send_batch(db, seller, *, currency: str = "usd",
                          min_threshold_minor: int = 0,
                          consent_stablecoin: bool = False,
                          execute: bool = True) -> PayoutBatch | None:
    """Aggregate a seller's AVAILABLE obligations into one batch on the selected rail,
    then (optionally) execute it. Returns the batch, or None if below threshold / no
    obligations. One obligation is included in at most one batch."""
    obligations = dbmod.available_obligations(db, seller.id, currency)
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

    # Deterministic idempotency key over the exact requested obligation set, but
    # FIXED-WIDTH: a raw comma-join grows with the obligation count and blows past
    # Stripe's 255-char idempotency limit. Hash the id list, keep a readable prefix.
    obl_ids = sorted(o.id for o in obligations)
    digest = hashlib.sha256(",".join(map(str, obl_ids)).encode()).hexdigest()[:32]
    key = f"petabyte:batch:{seller.id}:{currency}:{digest}"
    existing = db.query(PayoutBatch).filter(PayoutBatch.idempotency_key == key).first()
    if existing:
        return existing

    batch = PayoutBatch(seller_id=seller.id, rail_type=rt.value, provider=rt.value.split("_")[0],
                        source_currency=currency, destination_currency=currency,
                        total_amount_minor=total, idempotency_key=key,
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
    # claim the obligations for THIS batch (guard: only ones still unbatched+available)
    claimed = []
    for o in obligations:
        res = db.execute(dbmod.update(PayoutObligation)
                         .where(PayoutObligation.id == o.id,
                                PayoutObligation.batch_id.is_(None),
                                PayoutObligation.state == "available")
                         .values(batch_id=batch.id, state="batched"))
        if res.rowcount == 1:
            claimed.append(o.id)
    if not claimed:
        batch.state = "failed"; batch.failure_reason = "no obligations could be claimed"
        db.add(batch); db.commit()
        return batch
    # RECOMPUTE the batch total from what we ACTUALLY claimed. A concurrent batch can
    # win a subset of the obligations, so the pre-claim `total` can overstate what this
    # batch owns; sending it would over-transfer and double-pay the lost obligations.
    claimed_set = set(claimed)
    claimed_total = sum(o.net_amount_minor for o in obligations if o.id in claimed_set)
    batch.total_amount_minor = claimed_total
    db.add(batch); db.commit()

    if not execute:
        return batch

    return execute_batch(db, batch)


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
    db.add(batch); db.commit()
    return batch


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
    db.add(batch); db.commit()
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
    buckets = {"accrued": 0, "available": 0, "batched": 0, "paid": 0, "reversed": 0, "failed": 0}
    rows = (db.query(PayoutObligation.state,
                     func.coalesce(func.sum(PayoutObligation.net_amount_minor), 0))
            .filter(PayoutObligation.seller_id == seller_id)
            .group_by(PayoutObligation.state).all())
    for state, total in rows:
        buckets[state] = int(total or 0)
    return {
        "pending_minor": buckets["accrued"],          # in risk hold
        "available_minor": buckets["available"],
        "in_transit_minor": buckets["batched"],
        "paid_minor": buckets["paid"],
        "reversed_minor": buckets["reversed"],
        "failed_minor": buckets["failed"],
    }
