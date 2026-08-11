# Pricing model — value-anchored, demand-aware, and explainable

> Code: [`lumaris_api/pricing_engine.py`](../lumaris_api/pricing_engine.py) ·
> Tests: [`lumaris_api/pricing_engine_test.py`](../lumaris_api/pricing_engine_test.py)

The old auto-price slid a listing around the **midpoint of the seller's own `[min, max]` band**
with a demand multiplier. That never asked what the GPU is actually worth — a mispriced band stayed
mispriced. The pricing engine replaces it with one that prices on **value** and **market**, and
**shows its work**: every recommendation returns the labelled factors that produced it.

One pure function, `pricing_engine.recommend(...)`, is the single source of truth. It is called in
three places so they never disagree:

| Surface | Endpoint / call | Who sees it |
|---|---|---|
| **Preview** | `GET /nodes/{spec_id}/price/recommendation` | the seller (JWT), on demand |
| **Dashboard** | inline `suggested_price` on each node in `GET /seller/dashboard` | the seller, in the web UI |
| **Auto-price** | `db.reprice_specs()` (opt-in `auto_price` nodes) | applied automatically each cycle |

## How a price is built

Starting from an **anchor**, each factor is a multiplier with a plain-language reason:

1. **Anchor — the per-GPU cloud on-demand rate.** Petabyte's value prop is "cheaper than cloud,
   verified", so the anchor is `cloud_rate × PRICING_CLOUD_DISCOUNT` (default `0.60` → target ~40%
   under cloud). The cloud rate comes from the shared, **like-for-like** table
   (`CLOUD_REFERENCE`); if we don't recognise the GPU we fall back to the seller's band midpoint
   and **say so** — no invented discount.
2. **Demand** — `1 + PRICING_DEMAND_SENSITIVITY × (utilization − 0.5)`. Busy GPU class → higher;
   idle → lower. Default sensitivity `0.50` gives an idle 0.75× … full 1.25× swing.
3. **Verified performance / trust** — a benchmark that **matches** the claimed GPU's public
   reference earns a premium (1.08×); a **flagged** (implausible) benchmark or a still-unproven
   self-reported listing is discounted (0.90× / 0.92×). This ties price to the honest
   [trust ladder](TRUST_MODEL.md).
4. **Premiums** — confidential/TEE capability (1.15×), region-verified (1.03×), and reputation
   (0.92× … 1.08× across 0–100).

## Clamps (always honest, always the seller's floor)

- **Below cloud** — the result is capped under the cloud reference, so a Petabyte listing is
  always cheaper than renting the same card from a hyperscaler.
- **Inside the seller's band** — never below `min_price`, never above `max_price`. The seller sets
  the bounds; the engine only moves within them.
- **Positive**, rounded to the cent.

Each clamp that bites is recorded as a factor (`cloud_cap` / `seller_ceiling` / `seller_floor`) so
the seller can see *why* the number stopped where it did.

## What the seller gets back

```jsonc
{
  "recommended_price": 11.68,
  "anchor": 7.37, "anchor_source": "cloud", "cloud_reference": 12.29,
  "savings_vs_cloud_pct": 5.0,
  "floor": 1.0, "ceiling": 20.0,
  "factors": [
    {"factor": "demand",       "multiplier": 1.2,  "why": "90% of this GPU class is busy"},
    {"factor": "verification", "multiplier": 1.08, "why": "benchmark matches public reference for the claimed GPU"},
    {"factor": "confidential", "multiplier": 1.15, "why": "confidential (TEE) capability commands a premium"},
    {"factor": "cloud_cap",    "multiplier": null, "why": "kept below the cloud reference (always cheaper than cloud)"}
  ],
  "explanation": "Recommended $11.68/hr — about 5% below the equivalent cloud rate. Raised by: demand, verification, confidential, region, reputation.",
  "note": "A recommendation — you set the final price. …"
}
```

## Configuration

Two operator knobs (see [`template.env`](../lumaris_api/template.env)), both with safe defaults:

| Var | Default | Meaning |
|---|---|---|
| `PRICING_CLOUD_DISCOUNT` | `0.60` | fraction of the cloud rate to target (0.60 ≈ 40% cheaper) |
| `PRICING_DEMAND_SENSITIVITY` | `0.50` | how hard busy-ness moves price (idle 0.75× … full 1.25×) |

## Honest limitations

- The **cloud reference table is a static, approximate snapshot** of single-GPU on-demand rates —
  it is not a live price feed. Savings figures are directional, not a guarantee against any
  specific provider's current rate. Where we don't recognise a GPU, we show **no** savings figure.
- Auto-price is **opt-in** (`auto_price`), only ever moves inside the seller's own `[min, max]`,
  and logs every change as a `PriceChange(reason="auto")` the seller can see.
- The engine is deterministic and pure (no ML). Feeding the authenticity
  [dataset](DATA_MOAT.md) back into demand/price forecasting is a documented next step, not a
  claim we make today.
