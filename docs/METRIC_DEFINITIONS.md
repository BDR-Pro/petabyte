# Metric Definitions

Every metric on `/metrics` and from `GET /metrics/overview` is computed live from the
database (`lumaris_api/metrics.py`) — no hardcoded figures. This document is the
canonical definition; the API also serves a short version at `/metrics/definitions`.

Metrics accept `scope=all|demo|real` and an optional `since`/`until` date window.
Demo and real data are always separable, and the response carries
`contains_demo_data` so the UI can badge seeded figures. **Seeded demo numbers are
never presented as real traction.**

## Supply

| Metric | Definition |
|---|---|
| Registered nodes | Count of `SellerSpec` rows in scope. |
| Online | Nodes currently heartbeating (`spec_is_live`, within `HEARTBEAT_TIMEOUT_S`). |
| Verified | Nodes with `attested=true` (agent-signed hardware report). |
| Total / busy / available units | Capacity units summed across specs; busy = total − available. |
| Utilization % | busy_units / total_units × 100. |
| Available GPU-hours | Σ (available_units × node rentable window) over online nodes — a capacity proxy, not a booking. |
| Booked GPU-hours | Σ hours over released (settled) bookings. |
| Supply by region / hardware | Node counts grouped by declared region and GPU category. |

## Demand & reliability

| Metric | Definition |
|---|---|
| Active buyers | Distinct buyers with ≥1 booking in the window. |
| Repeat buyers | Buyers with >1 booking in the window. |
| Active sellers | Distinct sellers with ≥1 released booking. |
| Jobs completed / failed | Buyer compute jobs (`notebook, template, render, transcode, stitch, vm`) by terminal status. Internal `benchmark`/`test` probes are excluded. |
| Completion rate % | completed / (completed + failed) over buyer jobs. |
| Median time to start | Median seconds from booking creation to the job task appearing — a startup-latency proxy. |

## Unit economics

| Metric | Definition |
|---|---|
| GMV | Σ `gross_amount` over **released** bookings in the window. Escrowed/refunded excluded. |
| Platform revenue | Σ `platform_fee` over released bookings. |
| Seller payouts | Σ `seller_payout` (gross − fee) over released bookings. |
| Effective take rate % | platform_revenue / GMV. Should track the configured `PLATFORM_TAKE_RATE`. |
| Avg hourly price | Mean listed `price_per_hour` of online nodes. |
| Buyer savings vs cloud | For each released booking on a GPU with a known per-class cloud reference, Σ (cloud_ref − price) × hours. No reference → not counted. `savings_basis_bookings` reports how many bookings contributed. |
| Cloud reference default | The configured `AWS_REFERENCE_PRICE` fallback (per-class references live in `CLOUD_REFERENCE`). |

### Cloud reference prices

Stored per GPU class in `lumaris_api/main.py::CLOUD_REFERENCE` (USD/hr, approximate,
single-GPU on-demand). A savings figure is only shown when a **like-for-like** class
match exists — an H100 rate is never quoted against a 4090 listing. These are
approximate published on-demand rates and will differ by provider, region and
commitment; treat them as a reference, not a quote. Update cadence and source
attribution are tracked in ROADMAP (a `pricing_references` table with source/date/
region is the next step).

## Integrity

| Metric | Definition |
|---|---|
| Ledger balanced | `ledger_is_balanced`: every transaction's debits equal its credits and all accounts sum to zero. |
| Broken transactions | IDs of any unbalanced transactions (should always be empty). |

## What we deliberately do NOT show

No "users", "revenue" or "traction" numbers presented as real unless they come from
real (non-demo) rows. No vanity counts without a definition. No savings percentage
without a like-for-like cloud reference.
