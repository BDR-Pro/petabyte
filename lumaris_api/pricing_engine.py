"""pricing_engine.py — a performance-anchored, demand-aware, EXPLAINABLE price recommender.

The old auto-price moved a listing around the midpoint of the seller's own [min,max] band with a
demand multiplier. That ignores what the GPU is actually worth. This engine prices on VALUE and
MARKET, and shows its work:

  1. Anchor on the per-GPU **cloud on-demand price** and target a competitive discount — Petabyte's
     value prop is "cheaper than cloud, verified." (No cloud reference for the GPU -> fall back to
     the seller's band midpoint and say so.)
  2. Multiply by **demand** (how busy this GPU class is right now).
  3. Multiply by **verified performance / trust** — a benchmark-consistent card earns a premium; a
     flagged or unverified one is discounted.
  4. Add premiums for **confidential (TEE)** capability, **region-verified**, and **reputation**.
  5. Clamp: always below the cloud reference, and within the seller's own [min,max] — the seller
     is never priced below their floor or above their ceiling.

Every step is returned as a labelled factor with a plain-language reason, so the seller sees WHY.
Pure functions (no DB, no network) so the recommendation endpoint, the auto-price batch, and the
tests all share one implementation.
"""
from __future__ import annotations

import os

# Per-GPU-class on-demand cloud reference rates (USD/hr, approximate, single-GPU). A savings claim
# is only honest LIKE-FOR-LIKE; where we don't recognise the GPU we show NO reference (no invented
# discount). Shared by main.py (marketplace savings) and the pricing engine.
CLOUD_REFERENCE = {
    "h100": 12.29, "h200": 14.00, "a100": 4.10, "l40": 1.80, "l4": 0.90,
    "a10": 1.30, "v100": 3.06, "t4": 0.53, "rtx 4090": 0.80, "4090": 0.80,
    "rtx 4080": 0.60, "rtx 3090": 0.55, "3090": 0.55, "rtx a6000": 1.60, "a6000": 1.60,
}


def cloud_reference_for(gpu_model):
    """The on-demand cloud rate for THIS GPU class, or None if we can't compare fairly."""
    if not gpu_model:
        return None
    g = str(gpu_model).lower()
    for key in sorted(CLOUD_REFERENCE, key=len, reverse=True):
        if key in g:
            return CLOUD_REFERENCE[key]
    return None


def _f(env, default):
    try:
        return float(os.getenv(env, default))
    except (TypeError, ValueError):
        return float(default)


def recommend(cloud_ref, *, utilization=0.5, trust_level=None, benchmark_verdict=None,
              confidential=False, region_verified=False, reputation=None,
              min_price=None, max_price=None, current_price=None,
              cloud_discount=None, demand_sensitivity=None) -> dict:
    """Recommend a price for one node. Returns the recommended price + the labelled factors that
    produced it (anchor, demand, verification, confidential, region, reputation) + the clamps."""
    disc = _f("PRICING_CLOUD_DISCOUNT", 0.60) if cloud_discount is None else float(cloud_discount)
    dsens = _f("PRICING_DEMAND_SENSITIVITY", 0.50) if demand_sensitivity is None else float(demand_sensitivity)
    factors = []

    # 1) anchor
    if cloud_ref and float(cloud_ref) > 0:
        anchor = float(cloud_ref) * disc
        anchor_source = "cloud"
    elif min_price is not None and max_price is not None:
        anchor = (float(min_price) + float(max_price)) / 2.0
        anchor_source = "seller_band"
    else:
        anchor = float(current_price or 0)
        anchor_source = "current"
    price = float(anchor)

    def mul(name, m, why):
        nonlocal price
        price *= float(m)
        factors.append({"factor": name, "multiplier": round(float(m), 3), "why": why})

    # 2) demand
    util = min(max(float(utilization if utilization is not None else 0.5), 0.0), 1.0)
    mul("demand", 1.0 + dsens * (util - 0.5), f"{int(round(util * 100))}% of this GPU class is busy")

    # 3) verified performance / trust
    tl = (trust_level or "").lower()
    if benchmark_verdict in ("implausibly_low", "suspiciously_high") or "flagged" in tl:
        mul("verification", 0.90, "benchmark inconsistent with the claimed GPU — discounted")
    elif benchmark_verdict == "consistent" or tl == "benchmark_verified":
        mul("verification", 1.08, "benchmark matches public reference for the claimed GPU")
    elif tl in ("self_reported", ""):
        mul("verification", 0.92, "not yet agent-verified — discounted until proven")

    # 4) premiums
    if confidential:
        mul("confidential", 1.15, "confidential (TEE) capability commands a premium")
    if region_verified:
        mul("region", 1.03, "region verified")
    if reputation is not None:
        r = min(max(float(reputation), 0.0), 100.0)
        mul("reputation", 0.92 + 0.16 * (r / 100.0), f"reputation {int(round(r))}/100")

    # 5) clamps — always below cloud, always within the seller's band
    ceiling = None
    if cloud_ref and float(cloud_ref) > 0:
        ceiling = float(cloud_ref) * 0.95
        if price > ceiling:
            price = ceiling
            factors.append({"factor": "cloud_cap", "multiplier": None,
                            "why": "kept below the cloud reference (always cheaper than cloud)"})
    if max_price is not None and price > float(max_price):
        price = float(max_price)
        factors.append({"factor": "seller_ceiling", "multiplier": None,
                        "why": "clamped to your max price"})
    floor = float(min_price) if min_price is not None else 0.0
    if price < floor:
        price = floor
        factors.append({"factor": "seller_floor", "multiplier": None,
                        "why": "raised to your min price (never below your floor)"})
    price = round(max(0.0, price), 2)

    savings = None
    if cloud_ref and float(cloud_ref) > 0:
        savings = round(max(0.0, 1.0 - price / float(cloud_ref)) * 100.0, 1)

    return {
        "recommended_price": price,
        "anchor": round(anchor, 2),
        "anchor_source": anchor_source,
        "cloud_reference": (round(float(cloud_ref), 2) if cloud_ref else None),
        "savings_vs_cloud_pct": savings,
        "current_price": (round(float(current_price), 2) if current_price is not None else None),
        "floor": round(floor, 2),
        "ceiling": (round(ceiling, 2) if ceiling is not None
                    else (round(float(max_price), 2) if max_price is not None else None)),
        "factors": factors,
        "explanation": _explain(price, savings, anchor_source, factors),
        "note": "A recommendation — you set the final price. Higher verified trust and demand "
                "support a higher price; we always keep you below cloud.",
    }


def _explain(price, savings, anchor_source, factors) -> str:
    lead = (f"Recommended ${price:.2f}/hr" +
            (f" — about {savings:.0f}% below the equivalent cloud rate." if savings
             else " (no cloud reference for this GPU; anchored on your price band)."))
    ups = [f["factor"] for f in factors if f.get("multiplier") and f["multiplier"] > 1]
    downs = [f["factor"] for f in factors if f.get("multiplier") and f["multiplier"] < 1]
    tail = ""
    if ups:
        tail += " Raised by: " + ", ".join(ups) + "."
    if downs:
        tail += " Reduced by: " + ", ".join(downs) + "."
    return lead + tail
