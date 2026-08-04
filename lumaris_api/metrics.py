"""Marketplace / investor / operations metrics — computed from real DB queries.

Every number here is derived from the ledger, bookings, specs, tasks and users —
nothing is hardcoded or invented. Demo and real data are separable via `scope`, and
the response always states which scope it used so the UI can badge demo numbers.

Metric definitions live in docs/METRIC_DEFINITIONS.md; keep the two in sync.
"""
from datetime import datetime, timezone
from decimal import Decimal

from db import D, q, SellerSpec, Booking, Task, spec_is_live

# Task types that represent BUYER compute jobs. Internal probes (benchmark, test)
# are deliberately excluded from "jobs completed/failed" so the numbers mean what an
# investor thinks they mean.
BUYER_JOB_TYPES = ("notebook", "template", "render", "transcode", "stitch", "vm")

# GPU categories for the "supply by hardware" breakdown.
_GPU_CATEGORY = [
    ("H100/H200 (top-tier)", ("h100", "h200")),
    ("A100 (data-center)", ("a100",)),
    ("L40/L4/A10 (inference)", ("l40", "l4", "a10")),
    ("RTX 40-series (consumer)", ("4090", "4080", "4070")),
    ("RTX 30-series (consumer)", ("3090", "3080")),
    ("Other GPU", ()),
]


def _categorize(gpu_model: str) -> str:
    g = (gpu_model or "").lower()
    for label, keys in _GPU_CATEGORY:
        if any(k in g for k in keys):
            return label
    return "CPU / unspecified" if not g else "Other GPU"


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_metrics(db, cloud_reference_for, scope="all", since=None, until=None,
                    default_reference=12.29):
    """Return the metrics object for the given scope ('all'|'demo'|'real') and
    optional [since, until] date window (ISO strings or datetimes).

    `cloud_reference_for(gpu_model)` is injected so this module stays independent of
    the pricing table in main.py.
    """
    since_dt = _parse_dt(since)
    until_dt = _parse_dt(until)

    def in_window(dt):
        dt = _aware(dt)
        if dt is None:
            return True
        if since_dt and dt < since_dt:
            return False
        if until_dt and dt > until_dt:
            return False
        return True

    # ---- scope filters -----------------------------------------------------
    specs = db.query(SellerSpec).all()
    bookings = db.query(Booking).all()
    tasks = db.query(Task).all()
    if scope == "demo":
        specs = [s for s in specs if s.is_demo]
        bookings = [b for b in bookings if b.is_demo]
        tasks = [t for t in tasks if t.spec_id in {s.id for s in specs}]
    elif scope == "real":
        specs = [s for s in specs if not s.is_demo]
        bookings = [b for b in bookings if not b.is_demo]
        tasks = [t for t in tasks if t.spec_id in {s.id for s in specs}]

    bookings = [b for b in bookings if in_window(b.created_at)]

    # ---- supply ------------------------------------------------------------
    online = [s for s in specs if spec_is_live(s)]
    attested = [s for s in specs if s.attested]
    total_units = sum((s.total_units or 0) for s in specs)
    avail_units = sum((s.available_units or 0) for s in specs)
    busy_units = total_units - avail_units
    utilization = round(100.0 * busy_units / total_units, 1) if total_units else 0.0

    # ---- money (from booking rows; ledger cross-check below) ---------------
    released = [b for b in bookings if b.status == "released"]
    gmv = sum((D(b.gross_amount) for b in released), Decimal(0))
    platform_rev = sum((D(b.platform_fee) for b in released), Decimal(0))
    seller_payouts = sum((D(b.seller_payout) for b in released), Decimal(0))
    take_rate = (float(platform_rev / gmv) if gmv else 0.0)

    booked_gpu_hours = sum((b.hours or 0) for b in released)
    # available GPU-hours = free units x the listed rentable window (a capacity proxy)
    avail_gpu_hours = sum((s.available_units or 0) * (s.duration or 0) for s in online)

    prices = [float(s.price_per_hour) for s in online]
    avg_price = round(sum(prices) / len(prices), 2) if prices else None

    # ---- buyer savings vs the per-class cloud reference --------------------
    saved = Decimal(0)
    ref_basis = 0
    for b in released:
        spec = next((s for s in db.query(SellerSpec).filter(SellerSpec.id == b.spec_id)), None)
        ref = cloud_reference_for(spec.gpu_model) if spec else None
        if ref and float(b.price_per_hour) < ref:
            saved += (D(ref) - D(b.price_per_hour)) * D(b.hours or 0)
            ref_basis += 1

    # ---- jobs (buyer compute only) ----------------------------------------
    job_tasks = [t for t in tasks if t.task_type in BUYER_JOB_TYPES]
    completed = sum(1 for t in job_tasks if t.status == "completed")
    failed = sum(1 for t in job_tasks if t.status == "failed")
    running = sum(1 for t in job_tasks if t.status == "running")
    pending = sum(1 for t in job_tasks if t.status == "pending")
    finished = completed + failed
    completion_rate = round(100.0 * completed / finished, 1) if finished else None

    # ---- median time to start (booking created -> task marked running) ------
    # Uses task.created_at as the start proxy; null when no completed jobs exist.
    starts = []
    for t in job_tasks:
        if t.status in ("completed", "running") and t.created_at and t.booking_id:
            b = next((x for x in bookings if x.id == t.booking_id), None)
            if b and b.created_at:
                dt = (_aware(t.created_at) - _aware(b.created_at)).total_seconds()
                if dt >= 0:
                    starts.append(dt)
    median_start_s = round(_median(starts), 1) if starts else None

    # ---- buyers / sellers activity ----------------------------------------
    buyer_ids = [b.buyer_id for b in bookings]
    active_buyers = len(set(buyer_ids))
    from collections import Counter
    repeat_buyers = sum(1 for _id, n in Counter(buyer_ids).items() if n > 1)
    active_sellers = len({b.seller_id for b in released})

    # ---- breakdowns --------------------------------------------------------
    by_region = {}
    by_hw = {}
    for s in specs:
        r = s.region or "unspecified"
        by_region[r] = by_region.get(r, 0) + 1
        cat = _categorize(s.gpu_model)
        by_hw[cat] = by_hw.get(cat, 0) + 1

    # ---- ledger integrity (an investor-grade honesty signal) --------------
    ledger_ok, broken = _ledger_ok(db)

    return {
        "scope": scope,
        "contains_demo_data": scope in ("all", "demo") and any(s.is_demo for s in specs),
        "window": {"since": since, "until": until},
        "supply": {
            "registered": len(specs),
            "online": len(online),
            "verified": len(attested),
            "total_units": total_units,
            "busy_units": busy_units,
            "available_units": avail_units,
            "utilization_pct": utilization,
            "available_gpu_hours": avail_gpu_hours,
            "booked_gpu_hours": booked_gpu_hours,
            "by_region": by_region,
            "by_hardware": by_hw,
        },
        "demand": {
            "active_buyers": active_buyers,
            "repeat_buyers": repeat_buyers,
            "active_sellers": active_sellers,
        },
        "jobs": {
            "completed": completed, "failed": failed,
            "running": running, "pending": pending,
            "completion_rate_pct": completion_rate,
            "median_time_to_start_s": median_start_s,
        },
        "economics": {
            "gmv": q(gmv),
            "platform_revenue": q(platform_rev),
            "seller_payouts": q(seller_payouts),
            "effective_take_rate_pct": round(take_rate * 100, 1),
            "avg_hourly_price": avg_price,
            "buyer_savings_vs_cloud": q(saved),
            "savings_basis_bookings": ref_basis,
            "cloud_reference_default": default_reference,
        },
        "integrity": {
            "ledger_balanced": ledger_ok,
            "broken_transactions": broken,
        },
    }


def _ledger_ok(db):
    try:
        from db import ledger_is_balanced
        ok, broken = ledger_is_balanced(db)
        return ok, broken
    except Exception:
        return None, []


def _parse_dt(v):
    if v is None or isinstance(v, datetime):
        return _aware(v)
    try:
        return _aware(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
    except Exception:
        return None
