"""AI Router — 'solve compute', don't rent GPUs.

The customer states intent (workload, GPU class, region, redundancy, budget); the
router selects hardware from VERIFIED inventory using reputation + benchmark +
price + residency. Today candidates come only from our own marketplace nodes;
`gather_candidates` is the seam where external-provider adapters (AWS/Lambda/...)
would contribute candidates in future — the scorer is provider-agnostic.
"""
from db import SellerSpec, compute_reputation, get_user_by_id


def gather_candidates(db, intent: dict):
    """Verified, bookable specs meeting the HARD constraints. (Own inventory only.)"""
    out = []
    for spec in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if spec.status != "online" or (spec.available_units or 0) < 1:
            continue
        owner = get_user_by_id(db, spec.user_id)
        if not owner or not owner.can_accept_paid_jobs:
            continue
        if intent.get("min_vram") and (spec.vram_gb or 0) < intent["min_vram"]:
            continue
        if intent.get("gpu_class") and intent["gpu_class"].lower() not in (spec.gpu_model or "").lower():
            continue
        if intent.get("region") and not (spec.region == intent["region"] and spec.region_verified):
            continue
        if intent.get("country") and not (spec.detected_country == intent["country"] and spec.region_verified):
            continue
        if intent.get("confidential") and not spec.confidential:
            continue
        if intent.get("max_price_per_hour") and spec.price_per_hour > intent["max_price_per_hour"]:
            continue
        rep = compute_reputation(db, spec)
        if intent.get("min_reputation") and rep["score"] < intent["min_reputation"]:
            continue
        out.append({"spec": spec, "rep": rep["score"],
                    "price": spec.price_per_hour,
                    "tokens_sec": spec.benchmark_tokens_sec or 0.0,
                    "owner_id": spec.user_id})
    return out


def _norm(vals):
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return lambda v: (v - lo) / span


def score_candidates(cands):
    if not cands:
        return []
    rep_n = _norm([c["rep"] for c in cands])
    price_n = _norm([c["price"] for c in cands])
    bench_n = _norm([c["tokens_sec"] for c in cands])
    for c in cands:
        # cheaper is better -> invert price; reward reputation + throughput.
        c["score"] = round(0.45 * rep_n(c["rep"]) +
                           0.30 * (1 - price_n(c["price"])) +
                           0.25 * bench_n(c["tokens_sec"]), 4)
    return sorted(cands, key=lambda c: c["score"], reverse=True)


def select_plan(db, intent: dict):
    """Return a placement plan: N nodes across DISTINCT owners for real redundancy."""
    redundancy = max(1, int(intent.get("redundancy", 1)))
    hours = max(1, int(intent.get("hours", 1)))
    ranked = score_candidates(gather_candidates(db, intent))
    selected, used_owners = [], set()
    for c in ranked:
        if c["owner_id"] in used_owners:
            continue                       # one replica per provider = true redundancy
        selected.append(c); used_owners.add(c["owner_id"])
        if len(selected) >= redundancy:
            break

    def _fmt(c, chosen):
        s = c["spec"]
        return {"spec_id": s.id, "provider": s.provider, "gpu_model": s.gpu_model,
                "price_per_hour": s.price_per_hour, "region": s.region,
                "confidential": bool(s.confidential), "reputation": c["rep"],
                "tokens_sec": c["tokens_sec"], "score": c["score"],
                "reason": ("highest blended score (reputation/price/throughput) "
                           "meeting all constraints") if chosen else "qualified alternative"}

    est = round(sum(c["spec"].price_per_hour for c in selected) * hours, 4)
    return {
        "fulfilled": len(selected) >= redundancy,
        "requested_redundancy": redundancy,
        "selected": [_fmt(c, True) for c in selected],
        "alternatives": [_fmt(c, False) for c in ranked if c not in selected][:5],
        "estimated_cost": est, "hours": hours,
        "note": "Candidates are our own verified nodes; the scorer is provider-"
                "agnostic so external-cloud adapters can contribute candidates later.",
    }
