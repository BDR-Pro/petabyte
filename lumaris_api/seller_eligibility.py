"""Authoritative seller eligibility for accepting a PAID job.

This is what every financially-meaningful entry point calls to decide whether a seller may take
a paid job RIGHT NOW. It combines the INDEPENDENT authoritative conditions — never one opaque
boolean:

  1. payout_ready    — provider-neutral payout readiness (bounded freshness, fail-closed)
  2. reputation_ok   — seller reputation >= MIN_REPUTATION
  3. fraud_ok        — no active fraud/risk hold (compliance decision)
  4. availability_ok — the specific node is attested + live + has capacity (when a spec is given)
  5. mode_ok         — the payout rail is usable in the CURRENT gateway/mode (TEST/LIVE isolation)

The cached ``users.can_accept_paid_jobs`` is a PROJECTION for UI/search speed. It is NEVER the
authoritative gate here: financial authorization re-checks the underlying conditions LIVE, so a
stale-true cache cannot authorize a new paid job, and a stale-false cache does not block a seller
who actually qualifies. Fail closed — if payout readiness is unknown/stale, the seller is not
eligible.
"""
from __future__ import annotations

# reason_code -> operator/seller-safe message (no provider/KYC internals leaked to buyers).
REASON_MESSAGES = {
    "OK": "eligible",
    "NOT_AVAILABLE": "GPU is not online/available/eligible",
    "NO_PAYOUT_RAIL": "seller is not payout-ready",
    "PAYOUT_NOT_READY": "seller is not payout-ready",
    "PAYOUT_READINESS_STALE": "seller is not payout-ready",
    "MODE_MISMATCH": "seller payout rail is not valid for the current payment mode",
    "REPUTATION_TOO_LOW": "seller not trusted for paid work (reputation too low)",
    "FRAUD_HOLD": "seller is under a risk/fraud hold",
    "INELIGIBLE": "seller is not eligible for paid work",
}

_PAYOUT_REASON_MAP = {
    "readiness_stale": "PAYOUT_READINESS_STALE",
    "no_payout_rail": "NO_PAYOUT_RAIL",
}


def get_seller_job_eligibility(db, seller, *, spec=None, now=None) -> dict:
    """Structured, authoritative eligibility. `seller` is a User; `spec` (optional) adds the
    node-availability condition. Returns::

        {"eligible": bool, "payout_ready": bool, "reputation_ok": bool, "fraud_ok": bool,
         "availability_ok": bool, "mode_ok": bool, "reason_code": str,
         "rail": str|None, "provider": str|None}
    """
    import db as _dbm
    import payout_readiness

    sid = getattr(seller, "id", seller)

    # 1) payout readiness (provider-neutral, fresh-or-fail-closed)
    pr = payout_readiness.get_seller_payout_readiness(db, seller, now=now)
    payout_ready = bool(pr.get("ready"))

    # 2) reputation (independent — never overwritten by payout readiness)
    reputation_ok = int(getattr(seller, "reputation", 0) or 0) >= _dbm.MIN_REPUTATION

    # 3) fraud/risk: an active 'risk' compliance hold blocks new paid work
    fraud_ok = not _dbm.payout_hold_active(db, sid)

    # 4) node availability (only when a specific spec is in play)
    availability_ok = True
    if spec is not None:
        availability_ok = bool(getattr(spec, "attested", False)
                               and _dbm.spec_is_live(spec)
                               and (getattr(spec, "available_units", 0) or 0) >= 1)

    # 5) mode: the payout rail must belong to the CURRENTLY-running gateway (fake vs real). A
    #    stale cross-mode rail (e.g. a fake account under the real gateway) is never eligible.
    mode_ok = True
    rail_mode = pr.get("rail_mode")
    if rail_mode is not None:
        import stripe_connect
        mode_ok = (rail_mode == stripe_connect._current_gateway_mode())

    eligible = (payout_ready and reputation_ok and fraud_ok and availability_ok and mode_ok)

    if eligible:
        reason_code = "OK"
    elif not availability_ok:
        reason_code = "NOT_AVAILABLE"
    elif not payout_ready:
        reason_code = _PAYOUT_REASON_MAP.get(pr.get("reason"), "PAYOUT_NOT_READY")
    elif not mode_ok:
        reason_code = "MODE_MISMATCH"
    elif not reputation_ok:
        reason_code = "REPUTATION_TOO_LOW"
    elif not fraud_ok:
        reason_code = "FRAUD_HOLD"
    else:
        reason_code = "INELIGIBLE"

    return {"eligible": eligible, "payout_ready": payout_ready,
            "reputation_ok": reputation_ok, "fraud_ok": fraud_ok,
            "availability_ok": availability_ok, "mode_ok": mode_ok,
            "reason_code": reason_code, "rail": pr.get("rail"), "provider": pr.get("provider")}


def message_for(reason_code: str) -> str:
    """Safe message for a reason_code (never exposes provider/KYC internals)."""
    return REASON_MESSAGES.get(reason_code, REASON_MESSAGES["INELIGIBLE"])
