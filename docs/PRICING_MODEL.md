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
| **Catalog** | `GET /pricing/catalog` — every GPU sorted by benchmark, reference $/hr + live avg | public (`/pricing` page) |
| **Suggest** | `GET /pricing/suggest?gpu_model=…` — benchmark-anchored suggestion for a listing | any prospective seller |
| **Preview** | `GET /nodes/{spec_id}/price/recommendation` | the seller (JWT), on demand |
| **Dashboard** | inline `suggested_price` on each node in `GET /seller/dashboard` | the seller, in the web UI |
| **Auto-price** | `db.reprice_specs()` (opt-in `auto_price` nodes) | applied automatically each cycle |

### The catalog (`GET /pricing/catalog`)

Lists every recognised GPU model **sorted by FP16 benchmark ascending**, each with its
benchmark-anchored `reference_price_per_hour` (monotonic — slower is never dearer), the live
marketplace `avg_price_per_hour` for that model, and the cloud reference + savings. The reference
prices per model (a representative slice):

| GPU | FP16 TFLOPS | Reference $/hr | Cloud ref | Save |
|---|--:|--:|--:|--:|
| RTX 2060 | 52 | $0.13 | — | — |
| RTX 3060 | 51 | $0.12 | — | — |
| RTX 4060 | 61 | $0.15 | — | — |
| T4 | 65 | $0.15 | $0.53 | 72% |
| RTX 4070 | 117 | $0.26 | — | — |
| RTX 3090 | 142 | $0.31 | $0.55 | 44% |
| RTX 4080 | 195 | $0.42 | $0.60 | 30% |
| A100 | 312 | $0.66 | $4.10 | 84% |
| RTX 4090 | 330 | $0.70 | $0.80 | 13% |
| H100 | 989 | $2.05 | $12.29 | 83% |

## How a price is built

Starting from an **anchor**, each factor is a multiplier with a plain-language reason:

1. **Anchor — the GPU's performance reference (benchmark-ordered).** The anchor is derived from the
   one hardware-invariant benchmark we freeze on — **FP16 matmul TFLOPS** — as a *monotonic*
   function: `reference_price = PRICING_PERF_BASE + PRICING_PERF_PER_TFLOP × fp16_tflops`. Because
   it is monotonic, **a slower GPU is never priced above a faster one** — an RTX 2060 is always
   cheaper per hour than an RTX 4080, by construction. Cloud on-demand rates can't guarantee this
   (an A100 costs ~5× an RTX 4090 despite similar TFLOPS — scarcity/VRAM, not raw compute), so
   performance, not cloud, sets the ordering. The cloud rate is still reported for the
   savings figure and enforced as a ceiling. If we don't recognise the GPU we fall back to the
   cloud rate × discount, then the seller's band midpoint, and **say so** — no invented number.

   > The fairness rule — **benchmark order ⇒ price order** — is enforced at the reference/anchor
   > level, which is what the catalog advertises and what auto-price anchors to. It is asserted by
   > `pricing_engine_test.py` (the whole catalog is non-decreasing along the benchmark) and by the
   > smoke suite (an RTX 2060 is suggested below an RTX 4080).
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
| `PRICING_PERF_BASE` | `0.02` | $/hr floor offset of the benchmark price curve |
| `PRICING_PERF_PER_TFLOP` | `0.00205` | $/hr added per FP16 TFLOPS (the monotonic slope) |
| `PRICING_CLOUD_DISCOUNT` | `0.60` | cloud-anchor fallback: fraction of cloud rate to target |
| `PRICING_DEMAND_SENSITIVITY` | `0.50` | how hard busy-ness moves price (idle 0.75× … full 1.25×) |

The performance curve is deliberately calibrated to sit **below** cloud rates for the cards where
we have a cloud reference, so the below-cloud clamp rarely bites and never inverts the benchmark
ordering.

## Honest limitations

- The **cloud reference table is a static, approximate snapshot** of single-GPU on-demand rates —
  it is not a live price feed. Savings figures are directional, not a guarantee against any
  specific provider's current rate. Where we don't recognise a GPU, we show **no** savings figure.
- Auto-price is **opt-in** (`auto_price`), only ever moves inside the seller's own `[min, max]`,
  and logs every change as a `PriceChange(reason="auto")` the seller can see.
- The engine is deterministic and pure (no ML). Feeding the authenticity
  [dataset](DATA_MOAT.md) back into demand/price forecasting is a documented next step, not a
  claim we make today.
