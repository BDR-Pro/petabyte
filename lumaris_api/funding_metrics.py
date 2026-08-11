"""funding_metrics.py — the CANONICAL, DB/ledger-derived funding metrics.

Every number here is computed from AUTHORITATIVE database rows (ComputeTransaction, Task,
SellerSpec, PayoutObligation, RoutingDecision, User) — never from application logs and never
fabricated. An investor can trust these because they are the same rows the money moves through.

Honesty rules, baked in:
  * `scope` cleanly separates REAL money (LIVE, non-demo) from TEST and seeded DEMO data.
    Default is 'real'. Demo/test money is NEVER counted as real traction.
  * a metric with no underlying data returns 0 / null, and `has_real_data` says so plainly —
    "insufficient real data" is a valid, honest answer, not a reason to invent a number.
  * amounts are integer minor units (cents); rates are fractions in 0..1 (or null when the
    denominator is 0, i.e. undefined).

There is ONE canonical GMV definition here (captured money on ComputeTransaction, scope-filtered),
so investor numbers stop depending on which of the three legacy helpers happened to be called.

Heavy aggregates use SQL GROUP BY (not per-row Python) so this stays cheap as tables grow.
`now` is injectable for deterministic tests (same pattern as the payout-hold clock).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

import db as dbmod
from marketplace_insight import _SETTLED, TX_FAILED

CT = dbmod.ComputeTransaction
S = dbmod.SellerSpec
RD = dbmod.RoutingDecision
PO = dbmod.PayoutObligation
U = dbmod.User


def _now(now=None) -> datetime:
    return now or datetime.now(timezone.utc)


def _scope_filters(scope: str):
    """ComputeTransaction/PayoutObligation filters for a scope. REAL = live money, non-demo."""
    if scope == "real":
        return [CT.is_demo == False, CT.mode == "LIVE"]        # noqa: E712
    if scope == "test":
        return [CT.is_demo == False, CT.mode == "TEST"]        # noqa: E712
    if scope == "demo":
        return [CT.is_demo == True]                            # noqa: E712
    return []                                                  # 'all'


def _po_scope_filters(scope: str):
    if scope == "real":
        return [PO.is_demo == False, PO.mode == "LIVE"]        # noqa: E712
    if scope == "test":
        return [PO.is_demo == False, PO.mode == "TEST"]        # noqa: E712
    if scope == "demo":
        return [PO.is_demo == True]                            # noqa: E712
    return []


def _rate(n, d):
    """Fraction 0..1, or None when the denominator is 0 (undefined, never faked as 0)."""
    n, d = float(n or 0), float(d or 0)
    return round(n / d, 4) if d else None


def funding_snapshot(db, *, scope: str = "real", now=None) -> dict:
    """The canonical funding-metrics snapshot for one scope. All money in minor units."""
    now = _now(now)
    filt = _scope_filters(scope)

    def csum(col):
        q = db.query(func.coalesce(func.sum(col), 0))
        for f in filt:
            q = q.filter(f)
        return int(q.scalar() or 0)

    def ccount_distinct(col, *extra):
        q = db.query(func.count(func.distinct(col)))
        for f in list(filt) + list(extra):
            q = q.filter(f)
        return int(q.scalar() or 0)

    # ---- money (authoritative: ComputeTransaction) ----
    gmv = csum(CT.captured_amount)                     # ONE canonical GMV
    refunds = csum(CT.refunded_amount)
    platform_revenue = csum(CT.platform_fee_amount)    # gross commission
    processing_fees = csum(CT.stripe_fee_amount)       # estimated card cost (platform-borne)
    seller_earnings = csum(CT.seller_net_amount)
    net_gmv = gmv - refunds
    net_platform_revenue = platform_revenue - processing_fees   # contribution margin

    # ---- captured-tx population (drives buyers/sellers/AOV/retention) ----
    captured = [CT.captured_amount > 0] + filt
    n_captured_tx = int(db.query(func.count(CT.id)).filter(*captured).scalar() or 0)
    active_buyers = int(db.query(func.count(func.distinct(CT.buyer_id)))
                        .filter(*captured).scalar() or 0)
    active_sellers = int(db.query(func.count(func.distinct(CT.seller_id)))
                         .filter(*captured).scalar() or 0)

    # ---- tx outcomes (paid-job reliability) ----
    def txc(states):
        q = db.query(func.count(CT.id)).filter(CT.status.in_(states))
        for f in filt:
            q = q.filter(f)
        return int(q.scalar() or 0)
    settled, failed = txc(_SETTLED), txc(TX_FAILED)
    disputed = txc(("DISPUTED",))

    # ---- outstanding seller liability + payouts (PayoutObligation) ----
    def posum(states):
        q = db.query(func.coalesce(func.sum(PO.net_amount_minor), 0)).filter(PO.state.in_(states))
        for f in _po_scope_filters(scope):
            q = q.filter(f)
        return int(q.scalar() or 0)
    seller_liability_outstanding = posum(("accrued", "available", "batched",
                                          "transferring", "reconciling"))
    payouts_paid = posum(("paid",))

    # ---- supply / liquidity (SellerSpec; demo-aware, mode-agnostic hardware) ----
    demo_only = scope == "demo"
    sfilt = [] if scope == "all" else [S.is_demo == (True if demo_only else False)]  # noqa: E712
    online = db.query(S).filter(S.status == "online", *sfilt).all()
    avail_units = sum((s.available_units or 0) for s in online)
    total_units = sum((s.total_units or 0) for s in online)
    busy_units = max(0, total_units - avail_units)
    gpu_hours_available = sum((s.available_units or 0) * (s.duration or 0) / 3600.0 for s in online)
    active_gpus_online = len(online)

    # ---- unfulfilled demand (RoutingDecision; global — no mode/demo split on this signal) ----
    rd_total = int(db.query(func.count(RD.id)).scalar() or 0)
    rd_unfulfilled = int(db.query(func.count(RD.id))
                         .filter(RD.fulfilled == False).scalar() or 0)  # noqa: E712

    # ---- retention / repeat (activity cohorts from captured-tx dates) ----
    repeat = _repeat_and_retention(db, filt, now)

    # ---- data honesty ----
    has_real_data = gmv > 0 or n_captured_tx > 0 or active_gpus_online > 0
    contains_demo = (
        int(db.query(func.count(S.id)).filter(S.is_demo == True).scalar() or 0) > 0    # noqa: E712
        or int(db.query(func.count(CT.id)).filter(CT.is_demo == True).scalar() or 0) > 0  # noqa: E712
    )

    return {
        "scope": scope,
        "as_of": now.isoformat(),
        "has_real_data": has_real_data,
        "contains_demo_data": contains_demo,
        "currency": "usd",
        "money_minor": {
            "gmv_captured": gmv,
            "refunds": refunds,
            "net_gmv": net_gmv,
            "platform_revenue_gross": platform_revenue,
            "processing_fees_est": processing_fees,
            "net_platform_revenue": net_platform_revenue,
            "seller_earnings": seller_earnings,
            "seller_liability_outstanding": seller_liability_outstanding,
            "payouts_paid": payouts_paid,
        },
        "rates": {
            "take_rate_gross": _rate(platform_revenue, gmv),
            "take_rate_net": _rate(net_platform_revenue, gmv),
            "refund_rate": _rate(refunds, gmv),
            "job_success_rate": _rate(settled, settled + failed),
            "dispute_rate": _rate(disputed, settled + failed),
        },
        "marketplace": {
            "active_buyers": active_buyers,
            "active_sellers": active_sellers,
            "active_gpus_online": active_gpus_online,
            "paid_transactions": n_captured_tx,
            "settled_tx": settled, "failed_tx": failed, "disputed_tx": disputed,
            "avg_transaction_value_minor": int(gmv / n_captured_tx) if n_captured_tx else 0,
            "gmv_per_buyer_minor": int(gmv / active_buyers) if active_buyers else 0,
            "gmv_per_seller_minor": int(gmv / active_sellers) if active_sellers else 0,
            "gmv_per_active_gpu_minor": int(gmv / active_gpus_online) if active_gpus_online else 0,
            "arpu_minor": int(gmv / active_buyers) if active_buyers else 0,
        },
        "liquidity": {
            "gpu_hours_available": round(gpu_hours_available, 2),
            "units_total": total_units, "units_busy": busy_units,
            "utilization": _rate(busy_units, total_units),
            "routing_decisions": rd_total,
            "unfulfilled_demand": rd_unfulfilled,
            "fill_rate": _rate(rd_total - rd_unfulfilled, rd_total),
        },
        "retention": repeat,
        "note": ("All figures are computed from authoritative DB rows for scope="
                 f"'{scope}'. Zero/null means no data yet — never fabricated. 'real' = LIVE "
                 "money only; TEST and demo are excluded from real traction."),
    }


def _repeat_and_retention(db, ctx_filters, now, windows=(7, 30, 90)) -> dict:
    """Repeat-buyer rate + activity-cohort retention, from captured-tx dates.

    A buyer 'retains at Nd' if — having made a first captured purchase at least N days ago — they
    made ANOTHER captured purchase within N days of that first one. Computed from a single
    (buyer_id, created_at) scan (bounded; admin-frequency), not per-buyer queries."""
    rows = db.query(CT.buyer_id, CT.created_at).filter(CT.captured_amount > 0, *ctx_filters).all()
    by_buyer: dict = {}
    for bid, created in rows:
        if bid is None or created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        by_buyer.setdefault(bid, []).append(created)
    total_buyers = len(by_buyer)
    repeat_buyers = sum(1 for ts in by_buyer.values() if len(ts) >= 2)

    out = {"repeat_buyer_rate": _rate(repeat_buyers, total_buyers),
           "buyers_total": total_buyers, "buyers_repeat": repeat_buyers}
    for w in windows:
        eligible = matured = 0        # eligible: first purchase >= w days ago
        cutoff = now - timedelta(days=w)
        for ts in by_buyer.values():
            ts_sorted = sorted(ts)
            first = ts_sorted[0]
            if first > cutoff:
                continue              # too new to have had a full N-day window
            eligible += 1
            if any(t <= first + timedelta(days=w) and t > first for t in ts_sorted):
                matured += 1
        out[f"buyer_retention_{w}d"] = _rate(matured, eligible)
    return out
