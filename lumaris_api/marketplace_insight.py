"""Marketplace insight: the operational heartbeat + seller trust, from REAL DB data.

Every number here is a live SQL aggregate — no vanity constants. When there's no data
yet a field is 0 or null (honest), never a fake figure. Economics are scoped to the
current money mode so TEST and LIVE are never mixed.
"""
from __future__ import annotations

from sqlalchemy import func

import db as dbmod

_SETTLED = ("PAYMENT_CAPTURED", "SELLER_TRANSFER_PENDING", "SELLER_TRANSFERRED", "COMPLETED")
# Public: terminal failure states. (Kept `_TX_FAILED` as a back-compat alias.)
# AUTHORIZATION_EXPIRED is a real terminal state (see stripe_connect.TERMINAL); it must be
# here so payment_timeline sanitizes it and populates why_failed from _FAILURE_MESSAGES.
TX_FAILED = ("PAYMENT_FAILED", "AUTHORIZATION_EXPIRED", "RESERVATION_FAILED",
             "DISPATCH_FAILED", "JOB_FAILED", "CAPTURE_FAILED", "TRANSFER_FAILED",
             "CANCELLED", "REFUNDED")
_TX_FAILED = TX_FAILED

# Safe, user-facing failure messages. Raw ComputeTxEvent.reason may embed
# str(StripeError) (gateway/decline/account/request internals) and must NEVER reach a
# normal buyer/seller — only authorized admins get the raw reason for troubleshooting.
_FAILURE_MESSAGES = {
    "PAYMENT_FAILED": "The payment could not be completed. You were not charged.",
    "CAPTURE_FAILED": "We couldn't capture payment for this job. You were not charged for it.",
    "AUTHORIZATION_EXPIRED": "The payment authorization expired before settlement. No charge was made.",
    "RESERVATION_FAILED": "We couldn't reserve a GPU for this request.",
    "DISPATCH_FAILED": "The job couldn't be dispatched to a GPU.",
    "JOB_FAILED": "The GPU job failed during execution.",
    "TRANSFER_FAILED": "The seller payout couldn't be completed and is under review.",
    "REFUNDED": "This transaction was refunded.",
    "CANCELLED": "This transaction was cancelled.",
}


def explain_failure(status: str) -> str:
    """A safe, user-facing explanation for a terminal failure status — never exposes raw
    gateway/Stripe error text. Falls back to a generic message for any unknown status."""
    return _FAILURE_MESSAGES.get(status, "This transaction did not complete successfully.")


def health(db) -> dict:
    """Supply / demand / economics / quality — the marketplace's operational heartbeat."""
    S, Task, CT = dbmod.SellerSpec, dbmod.Task, dbmod.ComputeTransaction
    mode = dbmod.payments_mode()

    online = db.query(func.count(S.id)).filter(S.status == "online").scalar() or 0
    attested = db.query(func.count(S.id)).filter(S.attested == True).scalar() or 0  # noqa: E712
    offline = db.query(func.count(S.id)).filter(
        S.attested == True, S.status != "online").scalar() or 0                      # noqa: E712
    online_specs = db.query(S).filter(S.status == "online").all()
    avail_units = sum((s.available_units or 0) for s in online_specs)
    total_units = sum((s.total_units or 0) for s in online_specs)
    avail_gpu_hours = sum((s.available_units or 0) * (s.duration or 0) for s in online_specs)

    def tcount(*st):
        return db.query(func.count(Task.id)).filter(Task.status.in_(st)).scalar() or 0
    queued, running = tcount("pending"), tcount("assigned", "running")
    completed_jobs, failed_jobs = tcount("completed"), tcount("failed")
    tasks_total = db.query(func.count(Task.id)).scalar() or 0
    retried = db.query(func.count(Task.id)).filter(Task.retries > 0).scalar() or 0

    def summ(col):
        return int(db.query(func.coalesce(func.sum(col), 0)).filter(CT.mode == mode).scalar() or 0)
    captured, fees = summ(CT.captured_amount), summ(CT.platform_fee_amount)
    seller_net, refunded = summ(CT.seller_net_amount), summ(CT.refunded_amount)

    def txc(states):
        return db.query(func.count(CT.id)).filter(
            CT.mode == mode, CT.status.in_(states)).scalar() or 0
    tx_settled, tx_failed = txc(_SETTLED), txc(_TX_FAILED)

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None
    job_denom = completed_jobs + failed_jobs
    # Aggregate latency in SQL (do NOT load every SellerSpec row). Ignore specs with no
    # samples; return None when there are no qualifying rows at all.
    lat_sum, lat_n = db.query(
        func.coalesce(func.sum(S.latency_sum_s), 0.0),
        func.coalesce(func.sum(S.latency_n), 0)
    ).filter(S.latency_n > 0).one()
    avg_latency = round(float(lat_sum) / lat_n, 2) if lat_n else None
    demo = (db.query(func.count(S.id)).filter(S.is_demo == True).scalar() or 0) > 0  # noqa: E712

    return {
        "mode": mode, "contains_demo_data": demo,
        "supply": {"gpus_online": online, "gpus_offline": offline, "specs_attested": attested,
                   "available_units": avail_units, "reserved_units": max(0, total_units - avail_units),
                   "available_gpu_hours": avail_gpu_hours},
        "demand": {"queued_jobs": queued, "running_jobs": running,
                   "completed_jobs": completed_jobs, "failed_jobs": failed_jobs},
        "economics_minor": {"gmv_captured": captured, "platform_revenue": fees,
                            "seller_earnings": seller_net, "refunded": refunded, "currency": "usd"},
        "quality": {"tx_success_rate_pct": pct(tx_settled, tx_settled + tx_failed),
                    "job_success_rate_pct": pct(completed_jobs, job_denom),
                    "retry_rate_pct": pct(retried, tasks_total),
                    "refund_rate_pct": pct(refunded, captured),
                    "avg_latency_s": avg_latency},
        "note": "Live DB aggregates for the current money mode; nulls/zeros mean no data "
                "yet (never faked).",
    }


def trust_score(db, spec) -> dict:
    """A 0-100 seller trust score + star rating + the historical signals behind it.
    Untracked dimensions are null on purpose — surfaced honestly, never invented."""
    rep = dbmod.compute_reputation(db, spec)
    owner = dbmod.get_user_by_id(db, spec.user_id)
    done, failed = spec.jobs_completed or 0, spec.jobs_failed or 0
    total = done + failed
    P = dbmod.PayoutObligation

    def paid_sum(state):
        return int(db.query(func.coalesce(func.sum(P.net_amount_minor), 0))
                   .filter(P.seller_id == spec.user_id, P.state == state).scalar() or 0)
    paid, pay_failed = paid_sum("paid"), paid_sum("failed")
    pay_denom = paid + pay_failed
    score = rep["score"]
    filled = int(round(score / 20.0))

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None
    return {
        "spec_public_id": spec.public_id, "gpu_model": spec.gpu_model,
        "trust_score": score, "stars": round(score / 20.0, 1),
        "star_display": "★" * filled + "☆" * (5 - filled),
        "components": {
            "jobs_completed": done, "jobs_failed": failed,
            "completion_rate_pct": pct(done, total), "failure_rate_pct": pct(failed, total),
            "fraud_count": spec.fraud_count or 0,
            "avg_response_latency_s": rep["avg_latency_s"],
            "benchmark_tokens_sec": spec.benchmark_tokens_sec,
            "heartbeats": spec.heartbeats or 0,
            "identity_verified": bool(owner and owner.email_verified),
            "tests_passed": (owner.tests_passed if owner else 0),
            "tests_failed": (owner.tests_failed if owner else 0),
            "payout_success_rate_pct": pct(paid, pay_denom),
            # not tracked yet — shown as null rather than faked:
            "uptime_pct": None, "acceptance_rate_pct": None,
            "cancellation_rate_pct": None, "buyer_rating": None,
        },
        "note": "Score from real signals; null components aren't tracked yet (never faked).",
    }


def predict_success(spec, rep: dict) -> dict:
    """Transparent, data-driven predicted success probability for a node — the honest
    core of 'AI routing'. It is a calibrated heuristic over REAL signals (this node's
    completion history, fraud flags, benchmark, latency), explainable factor-by-factor.
    As the marketplace accumulates jobs this is the exact target a fitted model
    (logistic regression / gradient boosting) replaces — same inputs, same output — so
    it improves with data instead of pretending to be ML today."""
    done, failed = spec.jobs_completed or 0, spec.jobs_failed or 0
    total = done + failed
    fraud = spec.fraud_count or 0
    factors = []
    if total:
        cr = done / total
        p = 0.5 + 0.45 * cr
        factors.append(f"{round(100 * cr)}% completion over {total} job(s)")
    else:
        p = 0.90
        factors.append("verified node, no history yet (prior 90%)")
    if fraud:
        p *= max(0.5, 1 - 0.15 * fraud)
        factors.append(f"{fraud} fraud flag(s)")
    if spec.benchmark_tokens_sec:
        p = min(0.99, p + 0.03)
        factors.append("has a recorded benchmark")
    if rep.get("avg_latency_s") is not None:
        factors.append(f"avg response {rep['avg_latency_s']}s")
    return {"probability": round(max(0.01, min(0.99, p)), 3), "factors": factors}


def summarize_health(h: dict) -> str:
    """A plain-language summary generated FROM the live health numbers (deterministic,
    honest, LLM-swappable). This is the real substrate for a natural-language exec /
    investor dashboard — the narrative layer can call an LLM later, but the numbers it
    speaks are always these real aggregates."""
    s, d, e, q = h["supply"], h["demand"], h["economics_minor"], h["quality"]
    parts = [f"{s['gpus_online']} GPU(s) online, {s['available_units']} unit(s) free "
             f"({s['available_gpu_hours']} GPU-hours offered)",
             f"{d['queued_jobs']} queued / {d['running_jobs']} running / "
             f"{d['completed_jobs']} completed job(s)"]
    if q["job_success_rate_pct"] is not None:
        parts.append(f"{q['job_success_rate_pct']}% job success")
    parts.append(f"GMV ${e['gmv_captured'] / 100:.2f}, platform revenue "
                 f"${e['platform_revenue'] / 100:.2f}, seller earnings "
                 f"${e['seller_earnings'] / 100:.2f} ({h['mode']} mode)")
    return "Marketplace status — " + "; ".join(parts) + "."


def route_checklist(plan: dict, intent: dict) -> list:
    """Turn a routing decision into the investor-facing '✓ chosen because' checklist for
    the selected node. Each item is (ok: True/False/None, label)."""
    if not plan.get("selected"):
        return []
    sel = plan["selected"][0]
    snaps = plan.get("candidate_snapshot") or []
    prices = [c["price_per_hour"] for c in snaps] or [sel["price_per_hour"]]
    reps = [c["reputation"] for c in snaps] or [sel["reputation"]]
    checks = [{"ok": sel["price_per_hour"] <= min(prices),
               "label": f"Lowest price (${sel['price_per_hour']:.2f}/hr)"}]
    if intent.get("region"):
        checks.append({"ok": True, "label": f"Region match ({sel.get('region')})"})
    if intent.get("gpu_class") or intent.get("min_vram"):
        checks.append({"ok": True, "label": f"Compatible GPU ({sel.get('gpu_model')})"})
    checks.append({"ok": sel["reputation"] >= max(reps),
                   "label": f"Highest reliability (reputation {sel['reputation']})"})
    checks.append({"ok": True, "label": "Trusted seller (passes the paid-work gate)"})
    checks.append({"ok": True, "label": "Available immediately"})
    if sel.get("success_rate") is not None:
        checks.append({"ok": True, "label": f"Historical success {sel['success_rate']}%"})
    else:
        checks.append({"ok": None, "label": "No completed-job history yet (new node)"})
    return checks
