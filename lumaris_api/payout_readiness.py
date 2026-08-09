"""Provider-agnostic seller payout readiness — the SINGLE place that answers
"is this seller's payout side ready?".

Core business rule (this replaces "Stripe Connect account is payout-ready"):

    a seller is payout-ready
        IF
    the seller has >= 1 verified, enabled, payout-ready payout RAIL.

Marketplace logic must NOT know how any provider works. Instead of scattered checks like
``if connected_account.charges_enabled`` or ``if stripe_account_id``, callers ask:

    payout_readiness.get_seller_payout_readiness(db, seller)   # structured result
    payout_readiness.is_seller_payout_ready(db, seller_id)     # bool convenience

(For the full paid-job authorization decision — payout readiness AND reputation AND fraud AND
availability AND mode — use ``seller_eligibility.get_seller_job_eligibility``, which composes
this.)

FRESHNESS / FAIL-CLOSED: readiness is read from the DB-cached, provider-synced account state
(kept current by Stripe ``account.updated`` webhooks + on-demand refresh) — we do NOT call the
provider on the hot path. But a state we haven't confirmed within ``PAYOUT_READINESS_MAX_AGE_S``
(default 30d) is treated as UNKNOWN and fails closed (``reason="readiness_stale"``): stale
readiness can never authorize a new paid job.

Today the only IMPLEMENTED rail is Stripe Connect (``ConnectedAccount``). Future rails plug in
by adding a resolver to ``_RAIL_RESOLVERS`` — NO marketplace call site changes. The Connect rail
keeps its FULL capability gate (``charges_enabled AND payouts_enabled AND
transfers_capability == "active"``); this module never weakens it and never trusts a frontend
value or a return URL.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# A provider-synced state older than this is UNKNOWN -> fail closed. Bounded, configurable.
_MAX_AGE_S = int(os.getenv("PAYOUT_READINESS_MAX_AGE_S", str(30 * 24 * 3600)))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_fresh(synced_at, now, max_age_s) -> bool:
    if synced_at is None:
        return False
    if getattr(synced_at, "tzinfo", None) is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    if getattr(now, "tzinfo", None) is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - synced_at).total_seconds() <= max_age_s


def _connect_rail_readiness(db, seller_id, *, now, max_age_s) -> dict | None:
    """Readiness contributed by the Stripe Connect rail, or None when the seller has no Connect
    account at all. Uses the SAME capability gate as before (ConnectedAccount.payout_ready())
    and fails closed when the synced state is stale/unknown."""
    import db as _dbm
    ca = (db.query(_dbm.ConnectedAccount)
          .filter(_dbm.ConnectedAccount.user_id == seller_id).first())
    if ca is None:
        return None
    fresh = _is_fresh(ca.last_synced_at, now, max_age_s)
    capable = bool(ca.payout_ready())
    ready = capable and fresh
    reasons = []
    if not ca.details_submitted:
        reasons.append("Finish payout onboarding.")
    if not ca.charges_enabled:
        reasons.append("Charges capability not active yet.")
    if not ca.payouts_enabled:
        reasons.append("Payouts capability not active yet.")
    if (ca.transfers_capability or "inactive") != "active":
        reasons.append("Transfers capability not active yet.")
    if ca.disabled_reason:
        reasons.append(f"Account restricted: {ca.disabled_reason}.")
    if not fresh:
        # Stale/unknown provider state fails closed regardless of the last-known capabilities.
        reason_code = "readiness_stale"
        why = ("Payout status hasn't been confirmed recently enough to authorize new work "
               "(stale/unknown); it will re-sync from the provider.")
    elif capable:
        reason_code = None
        why = None
    elif ca.disabled_reason:
        reason_code = "restricted"
        why = " ".join(reasons)
    elif not ca.details_submitted:
        reason_code = "verification_required"
        why = " ".join(reasons) or "Onboarding incomplete."
    else:
        reason_code = "capabilities_pending"
        why = " ".join(reasons) or "Onboarding incomplete."
    return {
        "ready": ready,
        "provider": "stripe",
        "rail": "stripe_connect",
        "rail_mode": ca.gateway_mode,      # 'real' | 'fake' | None (legacy) — for the mode gate
        "country": ca.country,
        "stale": not fresh,
        "synced_at": ca.last_synced_at.isoformat() if ca.last_synced_at else None,
        "reason": reason_code,
        "why_blocked": None if ready else why,
        "requirements_due": json.loads(ca.requirements_due or "[]"),
        "requirements_past_due": json.loads(ca.requirements_past_due or "[]"),
    }


# Ordered registry of rail-readiness resolvers. Each takes (db, seller_id, *, now, max_age_s)
# and returns a readiness dict, or None when the seller has no such rail configured. Add future
# rails here; the marketplace never learns their names.
_RAIL_RESOLVERS = (_connect_rail_readiness,)


def get_seller_payout_readiness(db, seller, *, now=None, max_age_s=None) -> dict:
    """The one function callers use. `seller` may be a User or a seller_id.

    Returns a structured, provider-neutral result::

        {"ready": bool, "provider": str|None, "rail": str|None, "rail_mode": str|None,
         "country": str|None, "stale": bool, "synced_at": str|None,
         "reason": str|None, "why_blocked": str|None,
         "requirements_due": [...], "requirements_past_due": [...]}

    A seller is ready iff ANY configured rail is usable AND fresh. The first READY rail wins;
    otherwise the first configured-but-not-ready rail is reported (so the seller sees what to
    finish); if no rail is configured at all, `reason="no_payout_rail"`."""
    seller_id = getattr(seller, "id", seller)
    now = now or _utcnow()
    max_age_s = _MAX_AGE_S if max_age_s is None else max_age_s
    candidates = []
    for resolve in _RAIL_RESOLVERS:
        r = resolve(db, seller_id, now=now, max_age_s=max_age_s)
        if r is not None:
            candidates.append(r)
    for r in candidates:
        if r.get("ready"):
            return r
    if candidates:
        return candidates[0]
    return {"ready": False, "provider": None, "rail": None, "rail_mode": None,
            "country": None, "stale": False, "synced_at": None,
            "reason": "no_payout_rail", "why_blocked": "No payout method set up.",
            "requirements_due": [], "requirements_past_due": []}


def is_seller_payout_ready(db, seller_id, *, now=None) -> bool:
    """Boolean convenience over get_seller_payout_readiness — for callers that only need the
    flag (e.g. the buyer quote)."""
    return bool(get_seller_payout_readiness(db, seller_id, now=now).get("ready"))
