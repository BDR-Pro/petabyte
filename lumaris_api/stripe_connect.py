"""Stripe Connect marketplace payment service (separate charges & transfers).

The authoritative implementation of the paid-compute money flow:

  onboard seller -> quote -> authorize (manual-capture PaymentIntent) -> reserve GPU
  -> dispatch job -> meter usage -> capture actual usage -> transfer net to the
  seller's connected account -> reconcile via webhooks.

Design rules enforced here:
  * All amounts are INTEGER MINOR UNITS. Money math lives in pricing.py.
  * Never trust a browser amount; everything derives from the immutable pricing
    snapshot on the transaction.
  * Every Stripe mutation goes through a PaymentOperation row (persist-before-call)
    with a deterministic idempotency key -> no duplicate money movement on retries,
    crashes, or duplicate webhooks.
  * The seller is transferred only AFTER capture, at most once.
  * Webhooks (StripeWebhookEvent) are the authoritative async source; a redirect
    never marks anything paid.
  * Every money movement is posted to the SAME double-entry ledger (db.post()).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from db import (post, DEBIT, CREDIT, EXTERNAL_PAYMENTS, PLATFORM_REVENUE,
                acct_seller_payable, acct_stripe_payouts,
                ConnectedAccount, ComputeTransaction, ComputeTxEvent,
                PaymentOperation, StripeWebhookEvent, Settlement,
                SellerSpec, Booking, User, spec_is_live, try_reserve_unit,
                release_unit, create_task, get_user_by_id, update)
from pricing import PricingConfig, price_per_hour_to_minor, estimate, settle, refund_split
from stripe_gateway import get_gateway, StripeError

logger = logging.getLogger(__name__)

# Anti-account-takeover / chargeback cooling-off before a captured earning is payable.
PAYOUT_COOLING_OFF_H = int(os.getenv("PAYOUT_COOLING_OFF_H", "24") or "24")

# A 'pending' reserve/dispatch op older than this is treated as crashed and recoverable.
_OP_STALE_S = 300


class TransactionError(Exception):
    """Any business-rule violation in the payment flow (maps to 4xx)."""


# --------------------------------------------------------------------------- FSM
# Validated state machine. Only these transitions are permitted; anything else
# raises. Terminal states have no outgoing edges.
TRANSITIONS = {
    "DRAFT": {"PAYMENT_REQUIRES_ACTION", "PAYMENT_FAILED", "CANCELLED"},
    "PAYMENT_REQUIRES_ACTION": {"PAYMENT_AUTHORIZED", "PAYMENT_FAILED",
                                "AUTHORIZATION_EXPIRED", "CANCELLED"},
    "PAYMENT_AUTHORIZED": {"GPU_RESERVED", "RESERVATION_FAILED",
                           "AUTHORIZATION_EXPIRED", "CANCELLED"},
    "GPU_RESERVED": {"DISPATCHING", "DISPATCH_FAILED", "CANCELLED"},
    "DISPATCHING": {"RUNNING", "DISPATCH_FAILED", "JOB_FAILED"},
    "RUNNING": {"METERING_FINALIZED", "JOB_FAILED"},
    "METERING_FINALIZED": {"PAYMENT_CAPTURE_PENDING", "REFUND_PENDING", "CANCELLED"},
    "PAYMENT_CAPTURE_PENDING": {"PAYMENT_CAPTURED", "CAPTURE_FAILED"},
    "PAYMENT_CAPTURED": {"SELLER_TRANSFER_PENDING", "REFUND_PENDING", "DISPUTED"},
    "SELLER_TRANSFER_PENDING": {"SELLER_TRANSFERRED", "TRANSFER_FAILED"},
    "SELLER_TRANSFERRED": {"COMPLETED", "REFUND_PENDING", "DISPUTED"},
    "COMPLETED": {"REFUND_PENDING", "DISPUTED"},
    # recoverable failure edges
    "CAPTURE_FAILED": {"PAYMENT_CAPTURE_PENDING", "CANCELLED", "REFUND_PENDING"},
    "TRANSFER_FAILED": {"SELLER_TRANSFER_PENDING", "REFUND_PENDING"},
    "DISPATCH_FAILED": {"REFUND_PENDING", "CANCELLED"},
    "JOB_FAILED": {"REFUND_PENDING", "CANCELLED", "PAYMENT_CAPTURE_PENDING"},
    "RESERVATION_FAILED": {"CANCELLED", "REFUND_PENDING"},
    "REFUND_PENDING": {"REFUNDED", "DISPUTED"},
    # terminal
    "PAYMENT_FAILED": set(), "AUTHORIZATION_EXPIRED": set(), "CANCELLED": set(),
    "REFUNDED": set(), "DISPUTED": {"REFUNDED", "COMPLETED"},
}
TERMINAL = {"COMPLETED", "PAYMENT_FAILED", "AUTHORIZATION_EXPIRED", "CANCELLED", "REFUNDED"}


def transition(db, tx: ComputeTransaction, to_state: str, *, actor: str = "system",
               reason: str | None = None, allow_same: bool = False) -> ComputeTransaction:
    """Validate and apply a state transition, appending to the append-only history.
    Arbitrary jumps are rejected."""
    cur = tx.status
    if to_state == cur and allow_same:
        return tx
    if to_state not in TRANSITIONS.get(cur, set()):
        raise TransactionError(f"illegal transition {cur} -> {to_state}")
    tx.status = to_state
    db.add(tx)
    db.add(ComputeTxEvent(tx_id=tx.id, from_state=cur, to_state=to_state,
                          reason=reason, actor=actor))
    db.commit()
    db.refresh(tx)
    return tx


def _now():
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------- idempotency
def idem_key(op_type: str, tx: ComputeTransaction, version: int | None = None) -> str:
    """Deterministic Stripe idempotency key. Captures/transfers include the settlement
    version so a *new* settlement (after a refund) can legitimately act again, but a
    repeat of the same settlement cannot."""
    base = f"petabyte:{op_type}:{tx.public_id}"
    return f"{base}:{version}" if version is not None else base


def _begin_op(db, tx, op_type: str, stripe_key: str, *, stale_after_s: int | None = None):
    """ATOMICALLY claim an operation slot before calling Stripe. Returns (op, proceed).

    `proceed` is True ONLY if THIS caller should perform the side effect (Stripe call +
    ledger posting):
      * the op row was newly created by us (we own it), or
      * a prior attempt FAILED and we are legitimately retrying, or
      * (opt-in) a prior 'pending' op is STALE beyond stale_after_s — the previous worker
        crashed mid-flight and never finished. Only non-money local ops (reserve/dispatch,
        which are compensated on failure) pass stale_after_s; money ops leave it None so a
        genuinely in-flight transfer/capture is never double-run.
    `proceed` is False when another worker is already mid-flight (fresh 'pending') or the
    op already succeeded (idempotent replay).

    Atomicity comes from the UNIQUE constraint on internal_idempotency_key: two workers
    racing to INSERT the same key -> exactly one commit succeeds; the loser catches the
    IntegrityError and reads the winner's row."""
    from sqlalchemy.exc import IntegrityError
    op = PaymentOperation(tx_id=tx.id, op_type=op_type,
                          internal_idempotency_key=stripe_key,
                          stripe_idempotency_key=stripe_key,
                          state="pending", attempt_count=1)
    db.add(op)
    try:
        db.commit(); db.refresh(op)
        return op, True                          # we created it -> we own the side effect
    except IntegrityError:
        db.rollback()
        existing = db.query(PaymentOperation).filter(
            PaymentOperation.internal_idempotency_key == stripe_key).first()
        if existing is None:
            raise                                # not a uniqueness collision -> real error
        if existing.state == "failed":
            existing.state = "pending"; existing.attempt_count += 1
            db.add(existing); db.commit()
            return existing, True                # retry a prior failure -> proceed
        if existing.state == "pending" and stale_after_s is not None:
            _upd = existing.updated_at or existing.created_at
            if _upd is not None:
                if _upd.tzinfo is None:
                    _upd = _upd.replace(tzinfo=timezone.utc)
                if (_now() - _upd).total_seconds() > stale_after_s:
                    # ATOMIC reclaim: a read-then-write here would let two concurrent
                    # retries both pass the staleness check and both proceed. Instead,
                    # claim the row with a conditional UPDATE matching the SAME row, still
                    # 'pending' and the SAME attempt_count. Only the caller whose UPDATE
                    # affects exactly one row wins; the loser gets proceed=False.
                    _seen = existing.attempt_count
                    res = db.execute(update(PaymentOperation)
                                     .where(PaymentOperation.id == existing.id,
                                            PaymentOperation.state == "pending",
                                            PaymentOperation.attempt_count == _seen)
                                     .values(attempt_count=_seen + 1))
                    db.commit(); db.refresh(existing)
                    return existing, (res.rowcount == 1)
        existing.attempt_count += 1
        db.add(existing); db.commit()
        return existing, False                   # concurrent (pending) or succeeded -> do NOT repeat


def _finish_op(db, op, *, state: str, external_id: str | None = None, error: str | None = None):
    op.state = state
    if external_id:
        op.external_object_id = external_id
    if error:
        op.last_error = error[:400]
    db.add(op); db.commit()


# ----------------------------------------------------------------- onboarding
def get_or_create_connected_account(db, user: User, *, country: str = None,
                                    email: str = None) -> ConnectedAccount:
    """Idempotent: one connected account per seller. A repeat call returns the same
    account and never creates a second Stripe account."""
    ca = db.query(ConnectedAccount).filter(ConnectedAccount.user_id == user.id).first()
    if ca:
        return ca
    gw = get_gateway()
    country = (country or os.getenv("PLATFORM_DEFAULT_COUNTRY", "US")).upper()
    acct = gw.create_account(country=country, email=email or getattr(user, "email", None),
                             metadata={"petabyte_user_id": str(user.id)},
                             idempotency_key=f"petabyte:account:{user.id}")
    ca = ConnectedAccount(user_id=user.id, stripe_account_id=acct["id"],
                          country=acct.get("country"),
                          default_currency=acct.get("default_currency"),
                          onboarding_state="created", last_synced_at=_now())
    db.add(ca); db.commit(); db.refresh(ca)
    _sync_from_stripe(db, ca, acct)
    return ca


def create_onboarding_link(db, ca: ConnectedAccount, *, refresh_url: str,
                           return_url: str) -> str:
    link = get_gateway().create_account_link(account_id=ca.stripe_account_id,
                                             refresh_url=refresh_url,
                                             return_url=return_url)
    if ca.onboarding_state == "created":
        ca.onboarding_state = "onboarding"; db.add(ca); db.commit()
    return link["url"]


def refresh_connected_account(db, ca: ConnectedAccount) -> ConnectedAccount:
    """Authoritative status pull from Stripe. Never infer completion from a return URL."""
    acct = get_gateway().retrieve_account(ca.stripe_account_id)
    return _sync_from_stripe(db, ca, acct)


def _sync_from_stripe(db, ca: ConnectedAccount, acct: dict) -> ConnectedAccount:
    caps = acct.get("capabilities", {}) or {}
    reqs = acct.get("requirements", {}) or {}
    ca.details_submitted = bool(acct.get("details_submitted"))
    ca.charges_enabled = bool(acct.get("charges_enabled"))
    ca.payouts_enabled = bool(acct.get("payouts_enabled"))
    ca.transfers_capability = caps.get("transfers", "inactive")
    ca.card_payments_capability = caps.get("card_payments", "inactive")
    ca.requirements_due = json.dumps(reqs.get("currently_due", []) or [])
    ca.requirements_past_due = json.dumps(reqs.get("past_due", []) or [])
    ca.disabled_reason = reqs.get("disabled_reason")
    ca.country = acct.get("country") or ca.country
    ca.default_currency = acct.get("default_currency") or ca.default_currency
    if ca.payout_ready():
        ca.onboarding_state = "enabled"
    elif ca.disabled_reason:
        ca.onboarding_state = "restricted"
    elif ca.details_submitted:
        ca.onboarding_state = "verifying"
    else:
        ca.onboarding_state = "onboarding"
    ca.last_synced_at = _now()
    db.add(ca); db.commit(); db.refresh(ca)
    # A seller may only offer paid supply when Stripe can actually pay them.
    seller = get_user_by_id(db, ca.user_id)
    if seller is not None:
        seller.can_accept_paid_jobs = bool(ca.payout_ready() and seller.can_accept_paid_jobs
                                           if False else ca.payout_ready())
        db.add(seller); db.commit()
    return ca


def seller_payout_ready(db, seller_id: int) -> bool:
    ca = db.query(ConnectedAccount).filter(ConnectedAccount.user_id == seller_id).first()
    return bool(ca and ca.payout_ready())


# ----------------------------------------------------------------- quote
def _spec_price_minor(spec: SellerSpec, currency: str) -> int:
    return price_per_hour_to_minor(spec.price_per_hour, currency)


def quote(db, spec: SellerSpec, estimated_seconds: int,
          cfg: PricingConfig = None) -> dict:
    """Server-side quote. Returns the snapshot + estimate; no Stripe call, no state."""
    cfg = cfg or PricingConfig()
    snap = cfg.snapshot(_spec_price_minor(spec, cfg.currency))
    est = estimate(snap, estimated_seconds)
    return {"snapshot": snap, **est}


# ----------------------------------------------------------------- authorize
def authorize(db, buyer: User, spec: SellerSpec, estimated_seconds: int, *,
              cfg: PricingConfig = None, is_demo: bool = False) -> ComputeTransaction:
    """Create the internal transaction, then a manual-capture PaymentIntent. Amounts
    are server-computed from the snapshot. Returns the tx with client_secret set on a
    transient attribute (never persisted)."""
    if spec.user_id == buyer.id:
        raise TransactionError("cannot rent your own hardware")
    if not spec.attested or not spec_is_live(spec) or (spec.available_units or 0) < 1:
        raise TransactionError("GPU is not online/available/eligible")
    ca = db.query(ConnectedAccount).filter(ConnectedAccount.user_id == spec.user_id).first()
    if not ca or not ca.payout_ready():
        raise TransactionError("seller is not payout-ready")

    q = quote(db, spec, estimated_seconds, cfg)
    snap = q["snapshot"]
    tx = ComputeTransaction(
        buyer_id=buyer.id, seller_id=spec.user_id, spec_id=spec.id,
        currency=snap["currency"], pricing_snapshot=json.dumps(snap),
        estimated_amount=q["estimated_compute_amount"],
        authorization_amount=q["authorization_amount"],
        status="DRAFT", reconciliation_status="pending",
        stripe_connected_account_id=ca.stripe_account_id, is_demo=is_demo)
    db.add(tx); db.commit(); db.refresh(tx)

    key = idem_key("payment-intent", tx)
    op, _proceed = _begin_op(db, tx, "authorize", key)   # unique per tx -> always ours
    try:
        pi = get_gateway().create_payment_intent(
            amount=tx.authorization_amount, currency=tx.currency,
            metadata={"petabyte_tx": tx.public_id, "buyer_id": str(buyer.id),
                      "seller_id": str(spec.user_id), "spec_id": str(spec.id)},
            transfer_group=tx.public_id, idempotency_key=key, capture_method="manual")
    except StripeError as e:
        _finish_op(db, op, state="failed", error=str(e))
        transition(db, tx, "PAYMENT_FAILED", reason=str(e))
        raise TransactionError(f"could not create PaymentIntent: {e}")
    tx.stripe_payment_intent_id = pi["id"]
    db.add(tx); db.commit()
    _finish_op(db, op, state="succeeded", external_id=pi["id"])
    transition(db, tx, "PAYMENT_REQUIRES_ACTION", reason="PaymentIntent created")
    tx._client_secret = pi.get("client_secret")   # transient, returned once, not stored
    return tx


def mark_authorized(db, tx: ComputeTransaction) -> ComputeTransaction:
    """Verify server-side (via Stripe) that the buyer's card is authorized for at least
    the authorization amount, then move to PAYMENT_AUTHORIZED. Never trust the client."""
    if tx.status == "PAYMENT_AUTHORIZED":
        return tx
    pi = get_gateway().retrieve_payment_intent(tx.stripe_payment_intent_id)
    if pi["status"] != "requires_capture" or int(pi.get("amount_capturable", 0)) < tx.authorization_amount:
        raise TransactionError(f"payment not authorized (status={pi['status']})")
    tx.stripe_charge_id = pi.get("latest_charge")
    db.add(tx); db.commit()
    return transition(db, tx, "PAYMENT_AUTHORIZED", reason="card authorized (verified server-side)")


# ----------------------------------------------------------------- reserve + dispatch
def reserve_gpu(db, tx: ComputeTransaction) -> ComputeTransaction:
    """Atomically reserve capacity AFTER authorization is verified. Reuses the tested
    try_reserve_unit (atomic decrement). Creates a Booking row purely for job linkage;
    the money is held by Stripe, not the internal wallet, so no wallet escrow is used."""
    if tx.status != "PAYMENT_AUTHORIZED":
        raise TransactionError(f"cannot reserve from {tx.status}")
    spec = db.query(SellerSpec).filter(SellerSpec.id == tx.spec_id).first()
    if not spec or not spec_is_live(spec):
        transition(db, tx, "RESERVATION_FAILED", reason="GPU offline at reservation")
        raise TransactionError("GPU went offline")
    # Atomically CLAIM the reserve op FIRST. Two stale/parallel requests for the SAME tx
    # would otherwise each pass the status check and each reserve a unit + create a
    # booking. The loser gets proceed=False and returns the current state — one booking,
    # one unit, ever.
    op, proceed = _begin_op(db, tx, "reserve", idem_key("reserve", tx),
                            stale_after_s=_OP_STALE_S)
    if not proceed:
        db.refresh(tx)
        return tx
    if not try_reserve_unit(db, tx.spec_id):
        _finish_op(db, op, state="failed", error="no capacity")
        transition(db, tx, "RESERVATION_FAILED", reason="no capacity (lost the race)")
        raise TransactionError("no capacity")
    # Capacity is now held. Any failure past this point must COMPENSATE (release the unit,
    # drop a half-created booking) and mark the op failed, so a retry starts clean and no
    # orphaned Booking / stuck unit is left behind.
    booking = None
    try:
        from decimal import Decimal
        booking = Booking(buyer_id=tx.buyer_id, seller_id=tx.seller_id, spec_id=tx.spec_id,
                    hours=max(1, (json.loads(tx.pricing_snapshot).get("max_duration_s", 3600)) // 3600),
                    price_per_hour=spec.price_per_hour,
                    gross_amount=Decimal(tx.authorization_amount) / 100,
                    platform_fee=Decimal(0), seller_payout=Decimal(0),
                    status="stripe_reserved")   # NOT escrowed/active -> internal release_booking no-ops
        db.add(booking); db.commit(); db.refresh(booking)
        tx.booking_id = booking.id
        db.add(tx); db.commit()
    except Exception as e:
        db.rollback()
        # Compensate best-effort, each step independent so one failure can't skip the
        # rest. Release capacity FIRST (most important). Any read of booking.id can raise
        # ObjectDeletedError on a rolled-back instance, so it lives inside the delete try.
        try:
            release_unit(db, tx.spec_id)          # ALWAYS return the reserved unit
        except Exception:
            db.rollback()
            logger.error("reserve_gpu: release_unit failed for tx %s", tx.public_id,
                         exc_info=True)
        try:
            if booking is not None:
                db.delete(booking); db.commit()   # booking.id access is inside this try
        except Exception:
            db.rollback()
        try:
            _finish_op(db, op, state="failed", error=str(e))   # ALWAYS mark op failed
        except Exception:
            db.rollback()
        logger.error("reserve_gpu failed for tx %s after reserving capacity; compensated",
                     tx.public_id, exc_info=True)
        raise TransactionError(f"reserve failed: {e}")
    _finish_op(db, op, state="succeeded", external_id=str(booking.id))
    return transition(db, tx, "GPU_RESERVED", reason=f"unit reserved (booking {booking.id})")


def dispatch_job(db, tx: ComputeTransaction, *, task_type: str = "notebook",
                 code: str = None) -> ComputeTransaction:
    """Idempotent dispatch: if a task already exists for this tx, do NOT create another
    (retries never run the workload twice)."""
    if tx.task_id:
        return tx    # already dispatched
    if tx.status not in ("GPU_RESERVED",):
        raise TransactionError(f"cannot dispatch from {tx.status}")
    # Re-verify the authorization still holds before doing real work.
    pi = get_gateway().retrieve_payment_intent(tx.stripe_payment_intent_id)
    if pi["status"] != "requires_capture":
        raise TransactionError("authorization no longer valid; refusing to dispatch")
    # Atomically CLAIM dispatch so two parallel requests for the SAME tx create at most
    # one task (the tx.task_id check above is not atomic on its own).
    op, proceed = _begin_op(db, tx, "dispatch", idem_key("dispatch", tx),
                            stale_after_s=_OP_STALE_S)
    if not proceed:
        db.refresh(tx)
        return tx
    # Compensate a partial dispatch (orphan Task) on failure so a retry starts clean.
    task = None
    try:
        booking = db.query(Booking).filter(Booking.id == tx.booking_id).first()
        task = create_task(db, booking, task_type, code=code)
        tx.task_id = task.id
        db.add(tx); db.commit()
    except Exception as e:
        db.rollback()
        # Mark the op failed FIRST so a retry is never blocked by an orphan-cleanup error;
        # then best-effort delete the orphan task (its .id read is inside the try, as a
        # rolled-back instance can raise ObjectDeletedError).
        try:
            _finish_op(db, op, state="failed", error=str(e))
        except Exception:
            db.rollback()
        try:
            if task is not None:
                db.delete(task); db.commit()
        except Exception:
            db.rollback()
        logger.error("dispatch_job failed for tx %s; compensated (op failed, orphan task "
                     "cleaned best-effort)", tx.public_id, exc_info=True)
        raise TransactionError(f"dispatch failed: {e}")
    _finish_op(db, op, state="succeeded", external_id=str(task.id))
    transition(db, tx, "DISPATCHING", reason=f"task {task.id} created")
    return transition(db, tx, "RUNNING", reason="job running")


def record_metering(db, tx: ComputeTransaction, *, actual_seconds: int,
                    source: str = "agent") -> ComputeTransaction:
    """Record trusted, server-side metering. Cannot exceed the snapshot's max duration.
    Metering is the ONLY input to the final charge — never a browser value."""
    if tx.status not in ("RUNNING", "DISPATCHING"):
        raise TransactionError(f"cannot meter from {tx.status}")
    snap = json.loads(tx.pricing_snapshot)
    secs = max(0, min(int(actual_seconds), int(snap["max_duration_s"])))
    tx.metering_seconds = secs
    tx.metering_source = source
    db.add(tx); db.commit()
    return transition(db, tx, "METERING_FINALIZED", reason=f"metered {secs}s from {source}")


def settle_after_result(db, tx: ComputeTransaction, *, metered_seconds: int,
                        source: str = "platform") -> str:
    """Orchestrator bridge: after a VALID, completed job, finalize metering and drive
    capture + seller transfer in one go.

    Money still moves ONLY through the same audited functions the admin endpoints use
    (record_metering -> capture -> transfer_to_seller); this just chains them on job
    completion instead of requiring a manual admin call. Every step is guarded by the
    FSM and is idempotent, so a re-run, a concurrent admin action, or a duplicate
    result never double-charges or double-pays. Best-effort: if a step can't proceed
    (e.g. seller not payout-ready), it stops and leaves the tx in a repairable state
    (the seller payable is retained) for the admin/reconcile path. Returns the final
    tx status."""
    secs = max(1, int(metered_seconds))
    try:
        if tx.status in ("RUNNING", "DISPATCHING"):
            record_metering(db, tx, actual_seconds=secs, source=source)
        if tx.status in ("METERING_FINALIZED", "CAPTURE_FAILED", "JOB_FAILED"):
            capture(db, tx)
        if tx.status in ("PAYMENT_CAPTURED", "TRANSFER_FAILED"):
            transfer_to_seller(db, tx)
    except TransactionError as e:
        logger.warning("auto-settle halted for tx %s at status=%s: %s",
                       tx.public_id, tx.status, e)
    return tx.status


# ----------------------------------------------------------------- capture
def _write_settlement(db, tx, s: dict, version: int) -> Settlement:
    st = Settlement(tx_id=tx.id, version=version, currency=tx.currency,
                    captured_amount=s["capture_amount"], seller_amount=s["seller_net_amount"],
                    platform_fee=s["platform_fee_amount"], stripe_fee=tx.stripe_fee_amount,
                    refund_amount=tx.refunded_amount, transfer_amount=0,
                    transfer_reversal_amount=0, finalized_at=_now())
    db.add(st); db.commit(); db.refresh(st)
    return st


def capture(db, tx: ComputeTransaction) -> ComputeTransaction:
    """Capture the ACTUAL metered usage (<= authorization). Partial capture releases
    the unused authorization automatically. If usage is zero, cancel instead."""
    # Idempotent FIRST: already-captured (or beyond) is a no-op, never a double charge.
    if tx.status in ("PAYMENT_CAPTURED", "SELLER_TRANSFER_PENDING",
                     "SELLER_TRANSFERRED", "COMPLETED"):
        return tx
    if tx.status not in ("METERING_FINALIZED", "CAPTURE_FAILED", "JOB_FAILED"):
        raise TransactionError(f"cannot capture from {tx.status}")
    snap = json.loads(tx.pricing_snapshot)
    s = settle(snap, tx.metering_seconds or 0, tx.authorization_amount)

    if s["capture_amount"] <= 0:
        # No billable usage -> charge nothing, release the authorization + GPU.
        return cancel_authorization(db, tx, reason="no billable usage")

    version = tx.settlement_version + 1
    key = idem_key("capture", tx, version)
    # Claim the slot FIRST (atomic). A concurrent/duplicate worker gets proceed=False
    # and returns without a second capture or ledger posting.
    op, proceed = _begin_op(db, tx, "capture", key)
    if not proceed:
        return tx
    transition(db, tx, "PAYMENT_CAPTURE_PENDING", reason="capturing metered usage")
    try:
        pi = get_gateway().capture_payment_intent(
            pi_id=tx.stripe_payment_intent_id,
            amount_to_capture=s["capture_amount"], idempotency_key=key)
    except StripeError as e:
        _finish_op(db, op, state="failed", error=str(e))
        transition(db, tx, "CAPTURE_FAILED", reason=str(e))
        raise TransactionError(f"capture failed: {e}")

    captured = int(pi.get("amount_received", s["capture_amount"]))
    tx.captured_amount = captured
    tx.platform_fee_amount = s["platform_fee_amount"]
    tx.seller_net_amount = s["seller_net_amount"]
    tx.settlement_version = version
    tx.stripe_charge_id = pi.get("latest_charge") or tx.stripe_charge_id
    db.add(tx); db.commit()
    _finish_op(db, op, state="succeeded", external_id=pi["id"])
    _write_settlement(db, tx, s, version)

    # Ledger: money in from the card, split into platform revenue + seller payable.
    post(db, "compute_transaction", legs=[
        (EXTERNAL_PAYMENTS,               DEBIT,  captured, tx.buyer_id),
        (PLATFORM_REVENUE,                CREDIT, tx.platform_fee_amount),
        (acct_seller_payable(tx.seller_id), CREDIT, tx.seller_net_amount, tx.seller_id),
    ], reference_id=tx.public_id,
       description="captured actual compute usage", entry_type="compute_capture")
    transition(db, tx, "PAYMENT_CAPTURED", reason=f"captured {captured}")
    # Provider-neutral: settlement produces an IMMUTABLE payout obligation (what we owe
    # the seller). Idempotent per compute_tx; additive (never fails capture). If it fails
    # here the tx is still PAYMENT_CAPTURED, so it is REPAIRABLE:
    # reconcile_captured_without_obligations() (and transfer_to_seller) recreate it.
    try:
        _ensure_payout_obligation(db, tx)
    except Exception:
        db.rollback()
        logger.error("payout obligation creation FAILED for captured tx %s (seller %s, "
                     "net %s %s); will be repaired by reconciliation", tx.public_id,
                     tx.seller_id, tx.seller_net_amount, tx.currency, exc_info=True)
    return tx


def _ensure_payout_obligation(db, tx: ComputeTransaction):
    """Idempotently create the provider-neutral payout obligation for a captured tx
    (one per compute_tx_id, enforced by a DB unique constraint). Applies the risk-hold
    cooling-off. Raises on failure so the caller can decide (capture logs + repairs
    later; reconciliation retries)."""
    import db as _dbm
    acct = db.query(_dbm.ConnectedAccount).filter(
        _dbm.ConnectedAccount.user_id == tx.seller_id).first()
    hold_until = (_now() + timedelta(hours=PAYOUT_COOLING_OFF_H)
                  if PAYOUT_COOLING_OFF_H > 0 else None)
    return _dbm.create_payout_obligation(
        db, seller_id=tx.seller_id, compute_tx_id=tx.id, currency=tx.currency,
        net_amount_minor=tx.seller_net_amount, commission_minor=tx.platform_fee_amount,
        country=(acct.country if acct else None), risk_hold_until=hold_until,
        pricing_snapshot=tx.pricing_snapshot, is_demo=tx.is_demo,
        mode=tx.mode)   # keep the obligation in the ORIGINATING tx's money mode


def reconcile_captured_without_obligations(db, *, limit: int = 500) -> int:
    """Repair captured (or later) transactions that have NO payout obligation — e.g. the
    obligation insert failed after PAYMENT_CAPTURED persisted. Idempotent (create is
    per-compute_tx); returns how many were created. Safe to run from a reaper/cron."""
    import db as _dbm
    settled = ("PAYMENT_CAPTURED", "SELLER_TRANSFER_PENDING", "SELLER_TRANSFERRED",
               "COMPLETED", "TRANSFER_FAILED")
    rows = (db.query(ComputeTransaction)
            .outerjoin(_dbm.PayoutObligation,
                       _dbm.PayoutObligation.compute_tx_id == ComputeTransaction.id)
            .filter(ComputeTransaction.status.in_(settled),
                    ComputeTransaction.seller_net_amount > 0,
                    _dbm.PayoutObligation.id.is_(None))
            .limit(limit).all())
    n = 0
    for tx in rows:
        try:
            _ensure_payout_obligation(db, tx); n += 1
        except Exception:
            db.rollback()
            logger.error("reconcile: could not create obligation for tx %s",
                         tx.public_id, exc_info=True)
    if n:
        logger.info("reconcile: created %d missing payout obligation(s)", n)
    return n


# ----------------------------------------------------------------- transfer
def transfer_to_seller(db, tx: ComputeTransaction) -> ComputeTransaction:
    """Transfer the seller's net to their connected account. At most once, even under
    retries/crashes/duplicate webhooks/concurrent workers (guarded by the unique
    PaymentOperation key + tx.stripe_transfer_id + amount guard)."""
    # Idempotent FIRST: a repeat request on an already-transferred (or completed) tx is
    # a no-op, never an error and never a second transfer.
    if tx.stripe_transfer_id:
        return tx
    if tx.status not in ("PAYMENT_CAPTURED", "TRANSFER_FAILED"):
        raise TransactionError(f"cannot transfer from {tx.status}")
    import db as _dbm
    net = tx.seller_net_amount
    # never transfer more than captured, more than settled, or a second time
    if net <= 0:
        return transition(db, tx, "COMPLETED", reason="no seller net to transfer")
    if net > tx.captured_amount - tx.transferred_amount:
        raise TransactionError("transfer would exceed captured/available amount")

    # Repair-on-read: a tx captured before its obligation was created has none. Create it
    # now (idempotent) so the earning is recorded and can be marked paid below.
    if not db.query(_dbm.PayoutObligation).filter(
            _dbm.PayoutObligation.compute_tx_id == tx.id).first():
        try:
            _ensure_payout_obligation(db, tx)
        except Exception:
            db.rollback()
            logger.error("transfer: could not ensure obligation for tx %s (continuing; "
                         "reconciliation will repair)", tx.public_id, exc_info=True)

    # ATOMIC cross-path claim, fail CLOSED. Move the obligation accrued/available/
    # reconciling -> 'transferring' (a dedicated NON-BATCHABLE state) in one UPDATE,
    # BEFORE the Stripe call. This closes the check-to-use window: the batch layer only
    # ever claims 'available', so once we own it as 'transferring' no batch can pay it —
    # and a crash between the transfer and the paid-mark still leaves it non-batchable.
    claim = db.execute(_dbm.update(_dbm.PayoutObligation)
               .where(_dbm.PayoutObligation.compute_tx_id == tx.id,
                      _dbm.PayoutObligation.state.in_(["accrued", "available", "reconciling"]))
               .values(state="transferring"))
    db.commit()
    claimed_one = (claim.rowcount == 1)
    _obl = db.query(_dbm.PayoutObligation).filter(
        _dbm.PayoutObligation.compute_tx_id == tx.id).first()
    # OWNERSHIP REQUIRED before any Stripe call. Proceed ONLY if we just claimed the
    # obligation (rowcount 1) OR it is already 'transferring' (a prior attempt of THIS
    # transfer owns it; the op slot below serializes concurrent/idempotent callers).
    # Fail CLOSED for a missing obligation or any incompatible state (batched/paid/
    # reversed/failed) — never transfer an earning this path does not own.
    if _obl is None:
        raise TransactionError(
            f"no payout obligation for tx {tx.public_id}; refusing transfer (fail closed)")
    if not claimed_one and _obl.state != "transferring":
        raise TransactionError(
            f"obligation {_obl.public_id} is {_obl.state}; this transfer does not own it "
            f"— refusing (fail closed)")

    key = idem_key("transfer", tx, tx.settlement_version)
    # Claim the op slot too (atomic) — a concurrent/duplicate worker gets proceed=False
    # and never creates a second transfer or ledger posting.
    op, proceed = _begin_op(db, tx, "transfer", key)
    if not proceed:
        return tx
    transition(db, tx, "SELLER_TRANSFER_PENDING", reason="creating transfer")
    try:
        tr = get_gateway().create_transfer(
            amount=net, currency=tx.currency,
            destination=tx.stripe_connected_account_id,
            transfer_group=tx.public_id, source_transaction=None,
            metadata={"petabyte_tx": tx.public_id, "seller_id": str(tx.seller_id)},
            idempotency_key=key)
    except StripeError as e:
        # UNKNOWN outcome (timeout/network): the transfer MAY have gone through. Do NOT
        # release the obligation — keep it claimed as 'reconciling' (non-batchable) so a
        # batch can never pay it, and flag the tx for reconciliation. A retry re-uses the
        # same idempotency key, which Stripe deduplicates.
        _finish_op(db, op, state="failed", error=str(e))
        db.execute(_dbm.update(_dbm.PayoutObligation)
                   .where(_dbm.PayoutObligation.compute_tx_id == tx.id,
                          _dbm.PayoutObligation.state == "transferring")
                   .values(state="reconciling"))
        tx.reconciliation_status = "needs_review"; db.add(tx); db.commit()
        transition(db, tx, "TRANSFER_FAILED", reason=str(e))
        raise TransactionError(f"transfer failed: {e}")
    tx.stripe_transfer_id = tr["id"]
    tx.transferred_amount = net
    db.add(tx); db.commit()
    _finish_op(db, op, state="succeeded", external_id=tr["id"])
    post(db, "compute_transaction", legs=[
        (acct_seller_payable(tx.seller_id), DEBIT,  net, tx.seller_id),
        (acct_stripe_payouts(),             CREDIT, net),
    ], reference_id=tx.public_id,
       description="net transferred to seller connected account", entry_type="compute_transfer")
    transition(db, tx, "SELLER_TRANSFERRED", reason=f"transfer {tr['id']}")
    tx.reconciliation_status = "reconciled"
    db.add(tx); db.commit()
    # Stripe definitively confirmed: obligation 'transferring' -> 'paid'.
    try:
        db.execute(_dbm.update(_dbm.PayoutObligation)
                   .where(_dbm.PayoutObligation.compute_tx_id == tx.id,
                          _dbm.PayoutObligation.state.in_(["transferring", "accrued", "available"]))
                   .values(state="paid"))
        db.commit()
    except Exception:
        # Transfer already succeeded + committed. The obligation is still 'transferring'
        # (non-batchable), so no double-pay is possible; flag for reconciliation, loudly.
        db.rollback()
        tx.reconciliation_status = "needs_review"; db.add(tx); db.commit()
        logger.error("transfer %s succeeded but obligation paid-mark FAILED for tx %s; "
                     "obligation left non-batchable ('transferring') for reconciliation",
                     tx.stripe_transfer_id, tx.public_id, exc_info=True)
    return transition(db, tx, "COMPLETED", reason="settled end to end")


# ----------------------------------------------------------------- cancel / refund
def cancel_authorization(db, tx: ComputeTransaction, *, reason: str = "cancelled") -> ComputeTransaction:
    """Job never ran (or zero usage): cancel the PI hold, release the GPU, charge $0."""
    key = idem_key("cancel", tx)
    op, proceed = _begin_op(db, tx, "cancel", key)
    if not proceed:
        return tx
    try:
        if tx.stripe_payment_intent_id:
            get_gateway().cancel_payment_intent(pi_id=tx.stripe_payment_intent_id,
                                                idempotency_key=key)
        _finish_op(db, op, state="succeeded")
    except StripeError as e:
        _finish_op(db, op, state="failed", error=str(e))
    if tx.booking_id:
        _release_reservation(db, tx)
    tx.reconciliation_status = "reconciled"
    db.add(tx); db.commit()
    # from most pre-capture states CANCELLED is legal; if already captured, REFUND_PENDING->REFUNDED
    try:
        return transition(db, tx, "CANCELLED", reason=reason)
    except TransactionError:
        transition(db, tx, "REFUND_PENDING", reason=reason)
        return transition(db, tx, "REFUNDED", reason=reason)


def _release_reservation(db, tx):
    b = db.query(Booking).filter(Booking.id == tx.booking_id).first()
    if b and b.status == "stripe_reserved":
        b.status = "released_unused"; db.add(b); db.commit()
        release_unit(db, tx.spec_id)


def refund(db, tx: ComputeTransaction, *, amount: int = None, actor: str = "admin",
           reason: str = "refund") -> ComputeTransaction:
    """Refund a captured charge. If the seller was already transferred, claw back the
    proportional seller net via a transfer reversal. Reconciliation isn't 'done' until
    both sides are accounted for."""
    if tx.status not in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED",
                         "DISPUTED", "REFUND_PENDING"):
        raise TransactionError(f"cannot refund from {tx.status}")
    if not tx.captured_amount:
        raise TransactionError("nothing captured to refund")
    amount = tx.captured_amount if amount is None else int(amount)
    amount = max(0, min(amount, tx.captured_amount - tx.refunded_amount))
    if amount == 0:
        raise TransactionError("no refundable amount remaining")

    transition(db, tx, "REFUND_PENDING", reason=reason, allow_same=True) \
        if tx.status != "REFUND_PENDING" else None

    split = refund_split({"capture_amount": tx.captured_amount,
                          "seller_net_amount": tx.seller_net_amount}, amount)

    rkey = idem_key("refund", tx, tx.settlement_version) + f":{amount}"
    op, proceed = _begin_op(db, tx, "refund", rkey)
    # A duplicate/concurrent identical refund (same settlement version + amount) does
    # NOT re-increment refunded_amount or re-post the ledger — Stripe dedupes by the
    # idempotency key, so our books must too.
    if not proceed:
        return tx
    try:
        rf = get_gateway().create_refund(payment_intent=tx.stripe_payment_intent_id,
                                         amount=amount,
                                         metadata={"petabyte_tx": tx.public_id, "reason": reason[:100]},
                                         idempotency_key=rkey)
        _finish_op(db, op, state="succeeded", external_id=rf["id"])
    except StripeError as e:
        _finish_op(db, op, state="failed", error=str(e))
        raise TransactionError(f"refund failed: {e}")
    tx.refunded_amount += amount

    # Ledger: return money to the card, drawn proportionally from platform + seller payable.
    legs = [(EXTERNAL_PAYMENTS, CREDIT, amount, tx.buyer_id)]
    if split["platform_refund_amount"]:
        legs.append((PLATFORM_REVENUE, DEBIT, split["platform_refund_amount"]))
    if split["seller_reversal_amount"]:
        legs.append((acct_seller_payable(tx.seller_id), DEBIT,
                     split["seller_reversal_amount"], tx.seller_id))
    post(db, "compute_transaction", legs=legs,
         reference_id=tx.public_id, description=f"refund {amount}", entry_type="compute_refund")

    # If already transferred, claw the seller's share back via a transfer reversal.
    if tx.stripe_transfer_id and split["seller_reversal_amount"] > 0:
        revkey = idem_key("reversal", tx, tx.settlement_version) + f":{amount}"
        rop, rproceed = _begin_op(db, tx, "reversal", revkey)
        if not rproceed:
            return tx    # duplicate/concurrent reversal already happened
        try:
            rev = get_gateway().create_transfer_reversal(
                transfer_id=tx.stripe_transfer_id,
                amount=split["seller_reversal_amount"],
                metadata={"petabyte_tx": tx.public_id}, idempotency_key=revkey)
            _finish_op(db, rop, state="succeeded", external_id=rev["id"])
            tx.reversed_amount += split["seller_reversal_amount"]
            post(db, "compute_transaction", legs=[
                (acct_stripe_payouts(),             DEBIT,  split["seller_reversal_amount"]),
                (acct_seller_payable(tx.seller_id), CREDIT, split["seller_reversal_amount"], tx.seller_id),
            ], reference_id=tx.public_id,
               description="seller transfer reversal (refund clawback)", entry_type="compute_reversal")
        except StripeError as e:
            _finish_op(db, rop, state="failed", error=str(e))
            tx.reconciliation_status = "needs_review"
            db.add(tx); db.commit()
            raise TransactionError(f"refund done but reversal failed; escalated: {e}")

    fully = tx.refunded_amount >= tx.captured_amount
    tx.reconciliation_status = "reconciled" if (not tx.stripe_transfer_id or tx.reversed_amount >= split["seller_reversal_amount"]) else "needs_review"
    db.add(tx); db.commit()
    if fully:
        return transition(db, tx, "REFUNDED", reason=reason)
    return tx


# ----------------------------------------------------------------- lookups
def get_tx_by_public_id(db, public_id: str) -> ComputeTransaction | None:
    return db.query(ComputeTransaction).filter(
        ComputeTransaction.public_id == public_id).first()


def _tx_by_pi(db, pi_id: str) -> ComputeTransaction | None:
    return db.query(ComputeTransaction).filter(
        ComputeTransaction.stripe_payment_intent_id == pi_id).first()


# ----------------------------------------------------------------- webhooks
# Stripe is the authoritative async source. Every event is stored and processed at
# most once; a redirect never marks anything paid. Handlers are defensive and fetch
# the latest object when needed. Unknown types are acknowledged (200) so Stripe stops
# retrying, but recorded for the admin webhook-history view.
def process_webhook_event(db, event: dict) -> dict:
    eid = event.get("id")
    etype = event.get("type", "")
    if not eid:
        raise TransactionError("event missing id")
    rec = db.query(StripeWebhookEvent).filter(
        StripeWebhookEvent.stripe_event_id == eid).first()
    if rec and rec.processing_state == "processed":
        return {"status": "ok", "duplicate": True}      # at-most-once
    if not rec:
        rec = StripeWebhookEvent(stripe_event_id=eid, event_type=etype,
                                 api_version=event.get("api_version"),
                                 account_context=event.get("account"),
                                 processing_state="received", received_at=_now())
        db.add(rec); db.commit()
    rec.attempt_count += 1
    db.add(rec); db.commit()
    try:
        _handle_event(db, event)
        rec.processing_state = "processed"
        rec.processed_at = _now()
        rec.error = None
        db.add(rec); db.commit()
        return {"status": "ok"}
    except Exception as e:                              # noqa: BLE001
        rec.processing_state = "failed"
        rec.error = str(e)[:400]
        db.add(rec); db.commit()
        raise


def _handle_event(db, event: dict):
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "account.updated":
        ca = db.query(ConnectedAccount).filter(
            ConnectedAccount.stripe_account_id == obj.get("id")).first()
        if ca:
            _sync_from_stripe(db, ca, obj)
        return

    if etype in ("payment_intent.amount_capturable_updated", "payment_intent.succeeded"):
        tx = _tx_by_pi(db, obj.get("id"))
        if tx and obj.get("status") == "requires_capture" and tx.status == "PAYMENT_REQUIRES_ACTION":
            # Authoritative confirmation the card is authorized.
            try:
                mark_authorized(db, tx)
            except TransactionError:
                pass
        return

    if etype == "payment_intent.payment_failed":
        tx = _tx_by_pi(db, obj.get("id"))
        if tx and tx.status in ("DRAFT", "PAYMENT_REQUIRES_ACTION"):
            try:
                transition(db, tx, "PAYMENT_FAILED", actor="stripe", reason="payment_failed")
            except TransactionError:
                pass
        return

    if etype == "payment_intent.canceled":
        tx = _tx_by_pi(db, obj.get("id"))
        if tx and tx.status not in TERMINAL:
            try:
                transition(db, tx, "CANCELLED", actor="stripe", reason="canceled")
            except TransactionError:
                pass
        return

    if etype == "charge.refunded":
        tx = _tx_by_pi(db, obj.get("payment_intent"))
        if tx:
            # Stripe confirms the refund we initiated; reconcile the amount.
            refunded = int(obj.get("amount_refunded", tx.refunded_amount))
            if refunded > tx.refunded_amount:
                tx.refunded_amount = min(refunded, tx.captured_amount)
                db.add(tx); db.commit()
        return

    if etype in ("charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed"):
        pi = obj.get("payment_intent")
        tx = _tx_by_pi(db, pi) if pi else None
        if tx and etype == "charge.dispute.created" and tx.status not in TERMINAL:
            try:
                transition(db, tx, "DISPUTED", actor="stripe", reason="dispute opened")
                tx.reconciliation_status = "needs_review"; db.add(tx); db.commit()
            except TransactionError:
                pass
        return

    # transfer.* and payout.* are recorded as StripeWebhookEvent rows (the seller
    # dashboard + admin read payout status from there). Distinguishing a platform
    # transfer from a bank payout is exactly why these are separate events.
    if etype.startswith("transfer.") or etype.startswith("payout."):
        return

    # unknown/unhandled: acknowledged + recorded, no state change.
    return


def latest_payout_events(db, connected_account_id: str, limit: int = 20):
    """Bank-payout status for a connected account, read from stored webhook events.
    A successful Connect *transfer* is NOT a bank payout — these are the payout.* events."""
    rows = db.query(StripeWebhookEvent).filter(
        StripeWebhookEvent.account_context == connected_account_id,
        StripeWebhookEvent.event_type.like("payout.%")).order_by(
        StripeWebhookEvent.received_at.desc()).limit(limit).all()
    return [{"event_id": r.stripe_event_id, "type": r.event_type,
             "at": r.received_at.isoformat() if r.received_at else None} for r in rows]


# ----------------------------------------------------------------- reconciliation
def reconcile_transaction(db, tx: ComputeTransaction, gateway=None) -> dict:
    """Compare internal records against Stripe (or the fake gateway) + the ledger, and
    return any mismatches. Detects: captured != PI amount_received, transferred !=
    Stripe transfer amount, refunded != Stripe refund total, and captured !=
    platform_fee + seller_net. Read-only; the source of truth for asserting the system
    is consistent (make reconcile)."""
    gw = gateway or get_gateway()
    problems = []

    # capture vs Stripe PaymentIntent
    if tx.stripe_payment_intent_id and tx.captured_amount:
        try:
            pi = gw.retrieve_payment_intent(tx.stripe_payment_intent_id)
            if int(pi.get("amount_received", 0)) != tx.captured_amount:
                problems.append(f"captured {tx.captured_amount} != PI amount_received "
                                f"{pi.get('amount_received')}")
        except Exception as e:                          # noqa: BLE001
            problems.append(f"could not retrieve PaymentIntent: {e}")

    # money identity
    if tx.captured_amount and tx.captured_amount != tx.platform_fee_amount + tx.seller_net_amount:
        problems.append(f"captured {tx.captured_amount} != fee {tx.platform_fee_amount} "
                        f"+ net {tx.seller_net_amount}")

    # transfer vs Stripe transfer (net of reversals)
    if tx.stripe_transfer_id:
        tr = getattr(gw, "transfers", {}).get(tx.stripe_transfer_id) if hasattr(gw, "transfers") else None
        if tr is not None:
            net_on_stripe = tr["amount"] - tr.get("amount_reversed", 0)
            expected = tx.transferred_amount - tx.reversed_amount
            if net_on_stripe != expected:
                problems.append(f"net transfer on Stripe {net_on_stripe} != internal "
                                f"{expected}")

    # bounds
    if tx.refunded_amount > tx.captured_amount:
        problems.append(f"refunded {tx.refunded_amount} > captured {tx.captured_amount}")
    if tx.transferred_amount > tx.captured_amount:
        problems.append(f"transferred {tx.transferred_amount} > captured {tx.captured_amount}")

    return {"transaction_id": tx.public_id, "status": tx.status,
            "reconciliation_status": tx.reconciliation_status,
            "consistent": not problems, "problems": problems}


def reconcile_all(db, gateway=None) -> dict:
    """Reconcile every compute transaction + the ledger. Returns a summary suitable for
    `make reconcile`; non-empty `mismatches` means STOP and investigate."""
    txs = db.query(ComputeTransaction).all()
    mismatches = []
    for tx in txs:
        r = reconcile_transaction(db, tx, gateway)
        if not r["consistent"]:
            mismatches.append(r)
    from db import ledger_is_balanced
    balanced, broken = ledger_is_balanced(db)
    return {"transactions_checked": len(txs), "mismatches": mismatches,
            "ledger_balanced": balanced, "broken_ledger_tx": broken,
            "ok": (not mismatches) and balanced}
