"""Platform-initiated seller integrity audits + fraud escalation.

Sellers run on hardware we don't control, so we treat them as adversarial and VERIFY
rather than trust. Beyond the always-on checks —
  * every result is Ed25519-signed by the key attested at /prove (binds the result to
    the attested hardware; a forged/expired signature is rejected),
  * known-answer test jobs whose expected value is computed server-side (a seller that
    doesn't actually compute can't produce the right hash),
  * numeric/manifest validation for deterministic jobs (matmul_validation): server
    nonce/seed binding, container-digest allowlist, numeric tolerance, runtime bounds,
    telemetry consistency, duplicate detection,
  * the 14-day payout hold + report→hold (a window to catch fraud before money leaves) —
this module adds RANDOM spot-check audits of live sellers and freezes a seller's payouts
the moment there is hard fraud evidence.
"""
from __future__ import annotations

import logging
import os
import random

import db as dbmod
from db import SellerSpec, spec_is_live, get_user_by_id

logger = logging.getLogger("petabyte.audit")

AUDIT_SAMPLE_RATE = float(os.getenv("SELLER_AUDIT_SAMPLE_RATE", "0.25"))
FRAUD_PENALTY = int(os.getenv("SELLER_FRAUD_PENALTY", "40"))


def _bookable_specs(db):
    """Live, attested specs whose owner can currently take paid work."""
    out = []
    for s in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(s):
            continue
        owner = get_user_by_id(db, s.user_id)
        if owner and owner.can_accept_paid_jobs:
            out.append(s)
    return out


def run_spot_checks(db, *, difficulty: str = "easy", sample_rate: float = None,
                    max_audits: int = 100) -> list:
    """Randomly dispatch server-seeded known-answer challenges to live, bookable sellers.
    The seller's agent must claim the task and return the correct hash (verified in
    /jobs/result). A seller who isn't really running work on the claimed GPU fails —
    which drops their reputation and, on a failed audit, freezes their payouts.

    Returns the audits dispatched: [{spec_id, seller_id, task_id}]."""
    rate = AUDIT_SAMPLE_RATE if sample_rate is None else float(sample_rate)
    specs = _bookable_specs(db)
    dispatched = []
    for s in specs:
        if len(dispatched) >= max_audits:
            break
        if rate < 1.0 and random.random() > rate:      # noqa: S311 (not crypto)
            continue
        task, _tw = dbmod.create_test_task(db, s, difficulty=difficulty, trigger="audit")
        dispatched.append({"spec_id": s.id, "seller_id": s.user_id, "task_id": task.id})
    logger.info("seller spot-checks: dispatched %d audit(s) over %d bookable spec(s)",
                len(dispatched), len(specs))
    return dispatched


def freeze_for_fraud(db, spec, reason: str, *, seller_id: int = None,
                     penalty: int = None) -> None:
    """Hard fraud evidence (forged signature, failed platform audit, invalid result):
    record the fraud, penalize reputation (which can drop can_accept_paid_jobs below the
    gate), and FREEZE the seller's payouts pending review so nothing is disbursed. All
    best-effort and idempotent enough to call from the result path."""
    sid = seller_id if seller_id is not None else (spec.user_id if spec is not None else None)
    if spec is not None:
        try:
            dbmod.note_fraud(db, spec, reason)
        except Exception:
            logger.exception("note_fraud failed")
    if sid is not None:
        seller = get_user_by_id(db, sid)
        if seller is not None:
            try:
                dbmod.penalize_user(db, seller, penalty if penalty is not None else FRAUD_PENALTY)
            except Exception:
                logger.exception("penalize_user failed")
        try:
            dbmod.place_payout_hold(db, sid, reason=f"fraud: {reason}"[:200])
        except Exception:
            logger.exception("place_payout_hold failed")
        logger.warning("seller %s frozen for fraud: %s", sid, reason)
