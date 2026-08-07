"""AI Router — 'solve compute', don't rent GPUs.

The customer states intent (workload, GPU class, region, redundancy, budget); the
router selects hardware from VERIFIED inventory using reputation + benchmark +
price + residency. Today candidates come only from our own marketplace nodes;
`gather_candidates` is the seam where external-provider adapters (AWS/Lambda/...)
would contribute candidates in future — the scorer is provider-agnostic.

Every selection is DETERMINISTIC (stable tie-breaks) and EXPLAINABLE (the buyer
sees why in plain language), and the caller is expected to persist the full
scoring input + outcome via db.record_routing_decision so any booking can answer
"why this machine?" later.
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
        jobs_total = (spec.jobs_completed or 0) + (spec.jobs_failed or 0)
        out.append({"spec": spec, "rep": rep["score"], "rep_full": rep,
                    "price": spec.price_per_hour,
                    "tokens_sec": spec.benchmark_tokens_sec or 0.0,
                    "success_rate": (round(100.0 * (spec.jobs_completed or 0) / jobs_total, 1)
                                     if jobs_total else None),
                    "jobs_total": jobs_total,
                    "owner_id": spec.user_id})
    return out


def _norm(vals):
    # Scoring is a ranking heuristic, not accounting — floats are fine and correct
    # here. Money itself stays Decimal; we only coerce for the 0..1 normalisation.
    vals = [float(v) for v in vals]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    return lambda v: (float(v) - lo) / span


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
    # Ties MUST break the same way every run: score desc, then price asc, then the
    # stable spec id. Without this, equal-scored nodes would be picked by dict/query
    # order and the decision could not be honestly called deterministic.
    return sorted(cands, key=lambda c: (-c["score"], float(c["price"]), c["spec"].id))


def explain_selection(chosen, ranked, intent: dict) -> str:
    """One plain-language sentence per selection: constraint met, price vs the next
    eligible node, and the reliability evidence. Never invents a number — if there
    is no job history or no runner-up, it says so."""
    s = chosen["spec"]
    reasons = []
    if intent.get("min_vram"):
        reasons.append(f"meets the {intent['min_vram']} GB VRAM requirement")
    if intent.get("gpu_class"):
        reasons.append(f"is {s.gpu_model}-class as requested")
    if intent.get("region"):
        reasons.append(f"is in verified region {s.region}")
    if intent.get("confidential"):
        reasons.append("carries the confidential-computing flag")
    runner_up = next((c for c in ranked if c["spec"].id != s.id), None)
    if runner_up:
        try:
            pct = round((1 - float(chosen["price"]) / float(runner_up["price"])) * 100)
        except ZeroDivisionError:
            pct = 0
        if pct > 0:
            reasons.append(f"costs {pct}% less than the next eligible node "
                           f"(${float(chosen['price']):.2f}/hr vs ${float(runner_up['price']):.2f}/hr)")
        else:
            reasons.append(f"scored highest on the blended reputation/price/throughput "
                           f"ranking ({chosen['score']:.2f} vs {runner_up['score']:.2f})")
    else:
        reasons.append("is the only node meeting all constraints right now")
    if chosen.get("success_rate") is not None:
        reasons.append(f"has a {chosen['success_rate']}% successful-job rate "
                       f"over {chosen['jobs_total']} jobs")
    else:
        reasons.append("has no completed-job history yet (new node)")
    return (f"Selected {s.gpu_model or 'CPU'} node {s.public_id or s.id} "
            f"because it " + "; ".join(reasons) + ".")


def candidate_snapshot(ranked, selected_ids):
    """The audit-record view of every eligible node: inputs + score + outcome."""
    return [{"spec_id": c["spec"].id, "public_id": c["spec"].public_id,
             "gpu_model": c["spec"].gpu_model,
             "price_per_hour": float(c["price"]), "reputation": c["rep"],
             "tokens_sec": c["tokens_sec"], "success_rate": c["success_rate"],
             "jobs_total": c["jobs_total"], "score": c.get("score"),
             "selected": c["spec"].id in selected_ids}
            for c in ranked]


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
                "tokens_sec": c["tokens_sec"], "success_rate": c["success_rate"],
                "score": c["score"],
                "reason": (explain_selection(c, ranked, intent) if chosen
                           else "qualified alternative")}

    from db import D, q
    est = q(sum((D(c["spec"].price_per_hour) for c in selected), D(0)) * D(hours))
    selected_ids = [c["spec"].id for c in selected]
    return {
        "fulfilled": len(selected) >= redundancy,
        "requested_redundancy": redundancy,
        "selected": [_fmt(c, True) for c in selected],
        "alternatives": [_fmt(c, False) for c in ranked if c not in selected][:5],
        "estimated_cost": est, "hours": hours,
        "explanation": (explain_selection(selected[0], ranked, intent)
                        if selected else "No eligible node meets these constraints."),
        "candidate_snapshot": candidate_snapshot(ranked, set(selected_ids)),
        "selected_spec_ids": selected_ids,
        "note": "Candidates are our own verified nodes; the scorer is provider-"
                "agnostic so external-cloud adapters can contribute candidates later.",
        # Internal request-scoped caches so /route can annotate selected + alternatives
        # WITHOUT re-fetching specs or recomputing reputation (popped before responding).
        "_specs": {c["spec"].id: c["spec"] for c in ranked},
        "_reputation": {c["spec"].id: c["rep_full"] for c in ranked},
    }
