"""Provider-agnostic seller payout readiness — the SINGLE place that answers
"may this seller accept paid jobs?".

Core business rule (this replaces "Stripe Connect account is payout-ready"):

    a seller may accept paid jobs
        IF
    the seller has >= 1 verified, enabled, payout-ready payout RAIL.

Marketplace logic must NOT know how any provider works. Instead of scattered checks like
``if connected_account.charges_enabled`` or ``if stripe_account_id``, every call site asks:

    payout_readiness.get_seller_payout_readiness(db, seller)   # structured result
    payout_readiness.is_seller_payout_ready(db, seller_id)     # bool convenience

Today the only IMPLEMENTED rail is Stripe Connect (``ConnectedAccount``). Future rails
(Stripe Global Payouts, stablecoin, …) plug in by adding a resolver to ``_RAIL_RESOLVERS`` —
NO marketplace call site changes. The Connect rail keeps its FULL capability requirements
(``charges_enabled AND payouts_enabled AND transfers_capability == "active"`` via
``ConnectedAccount.payout_ready()``); this module never weakens them and never trusts a
frontend value or a return URL — readiness comes only from authoritative provider-synced state.
"""
from __future__ import annotations

import json


def _connect_rail_readiness(db, seller_id: int) -> dict | None:
    """Readiness contributed by the Stripe Connect rail, or None when the seller has no Connect
    account at all. Uses the SAME capability gate as before (ConnectedAccount.payout_ready())."""
    import db as _dbm
    ca = (db.query(_dbm.ConnectedAccount)
          .filter(_dbm.ConnectedAccount.user_id == seller_id).first())
    if ca is None:
        return None
    ready = bool(ca.payout_ready())
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
    if ca.disabled_reason:
        reason_code = "restricted"
    elif not ca.details_submitted:
        reason_code = "verification_required"
    else:
        reason_code = "capabilities_pending"
    return {
        "ready": ready,
        "provider": "stripe",
        "rail": "stripe_connect",
        "country": ca.country,
        "reason": None if ready else reason_code,
        "why_blocked": None if ready else (" ".join(reasons) or "Onboarding incomplete."),
        "requirements_due": json.loads(ca.requirements_due or "[]"),
        "requirements_past_due": json.loads(ca.requirements_past_due or "[]"),
    }


# Ordered registry of rail-readiness resolvers. Each takes (db, seller_id) and returns a
# readiness dict, or None when the seller has no such rail configured. Add future rails here;
# the marketplace never learns their names.
_RAIL_RESOLVERS = (_connect_rail_readiness,)


def get_seller_payout_readiness(db, seller) -> dict:
    """The one function marketplace logic calls. `seller` may be a User or a seller_id.

    Returns a structured, provider-neutral result::

        {"ready": bool, "provider": str|None, "rail": str|None, "country": str|None,
         "reason": str|None, "why_blocked": str|None,
         "requirements_due": [...], "requirements_past_due": [...]}

    A seller is ready iff ANY configured rail is usable. The first READY rail wins; otherwise
    the first configured-but-not-ready rail is reported (so the seller sees what to finish); if
    no rail is configured at all, `reason="no_payout_rail"`."""
    seller_id = getattr(seller, "id", seller)
    candidates = []
    for resolve in _RAIL_RESOLVERS:
        r = resolve(db, seller_id)
        if r is not None:
            candidates.append(r)
    for r in candidates:
        if r.get("ready"):
            return r
    if candidates:
        return candidates[0]
    return {"ready": False, "provider": None, "rail": None, "country": None,
            "reason": "no_payout_rail", "why_blocked": "No payout method set up.",
            "requirements_due": [], "requirements_past_due": []}


def is_seller_payout_ready(db, seller_id) -> bool:
    """Boolean convenience over get_seller_payout_readiness — for callers that only need the
    flag (e.g. the buyer quote and the authorize gate)."""
    return bool(get_seller_payout_readiness(db, seller_id).get("ready"))
