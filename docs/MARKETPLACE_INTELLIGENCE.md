# Marketplace intelligence

The moat isn't "AI" as a buzzword — it's the **operational-data flywheel**: every job
teaches the platform which GPUs win which workloads, which sellers are reliable, which
prices fill capacity, where shortages form. This doc is what's **real and shipping now**
(all SQL-backed, explainable, never faked), and what honestly needs accumulated data,
an LLM, or an observability stack before it's real.

Guiding rule: **every number is a live query; a node with no history shows an honest prior
or `null`, never an invented stat.**

## Real now (data-driven, explainable, tested)

- **Explainable routing + predicted success — `POST /route`.** Picks the best GPU(s) for
  the stated intent and shows *why*: a **predicted success probability** per node computed
  transparently from real signals (this node's completion history, fraud flags, benchmark,
  latency) with a factor list, plus a plain ✓-checklist (lowest price / region / highest
  reliability / compatible GPU / trusted seller / available now / historical success %).
  Deterministic tie-breaks; the full candidate scoring is persisted so any booking can
  answer "why this machine?" later. *(User AI list: #1 routing, #17 explainable routing.)*
- **Seller trust score — `GET /sellers/{id}/trust`.** A 0-100 score + star rating + the
  real signals behind it (completion/failure rates, fraud, response latency, benchmark,
  heartbeats, identity-verified, tests, payout-success). Untracked dimensions
  (buyer_rating, uptime %, acceptance/cancellation rates) are `null` on purpose.
  *(#5 trust score.)*
- **Marketplace health dashboard — `GET /marketplace/health`.** Supply (online/offline
  GPUs, available units, reserved, GPU-hours), demand (queued/running/completed/failed
  jobs), economics (GMV, platform revenue, seller earnings — current money mode), quality
  (success/retry/refund rates, latency). *(#3, #7 substrate, #12 live metrics.)*
- **Natural-language health summary — `GET /marketplace/health/summary`.** A plain-English
  summary generated **from the live numbers** (deterministic template today, LLM-swappable
  later — the narrative changes, the facts stay these real aggregates). *(#7/#19/#20
  substrate, honest form.)*
- **Immutable transaction timeline + "why it failed" — `GET /payments/{id}/timeline`.**
  Every state change (who, when, why) from the append-only event log, plus a plain failure
  reason when a tx ends in a failure state ("GPU disconnected after 83% of execution").
  *(#10 audit history, #6 why-this-failed.)*
- **Fraud detection + job verification (already shipped).** Signed-result attestation,
  server-seeded known-answer checks, `matmul_validation` (nonce/seed binding, digest
  allowlist, numeric tolerance, runtime bounds, telemetry consistency, duplicate),
  **random spot-check audits**, and **quorum re-execution** across sellers — with
  fraud→payout-freeze. *(#4 fraud detection, #6/#6-verify job verification.)* See
  `docs/SELLER_ANTIFRAUD.md`.

## Real once there's data (the flywheel fits a model to the same inputs)

These use the *same* real inputs as above; today they run as calibrated heuristics/priors
and are honestly labeled as such. As jobs accumulate, fit a model (logistic regression /
gradient boosting) to the recorded outcomes — **same inputs, same output**, better
calibration — without changing the API:

- Success-probability prediction (the `predict_success` heuristic → a fitted model).
- **AI price optimizer / seller assistant** (#2, #11): recommend a price from real
  utilization + demand + this GPU class's marketplace stats.
- **Buyer recommendation** (#3), **capacity & revenue forecasting** (#13, #14),
  **auto-benchmark classification** (#18).

To get here honestly needs what your funding plan already prioritizes: real GPU owners +
100+ real jobs. The data model to capture it is in place (`RoutingDecision`,
`ReputationEvent`, `ComputeTxEvent`, `TestWorkload`, `QuorumCheck`, obligations).

## Needs an LLM + observability stack (not faked here)

These are genuinely valuable but are an **LLM narrative layer over real telemetry**, so
they need (a) an LLM key and (b) logs/metrics wired in (Prometheus/Grafana/Elastic):

- **AI ops engineer / incident summaries / security analyst** (#9, #15, #16).
- **AI support agent** (#8) and **NL exec/investor Q&A** (#19, #20) beyond the
  deterministic summary above.
- **AI deployment review** (#10).

The right build order is: keep emitting the real signals now → add the LLM narrative layer
when there's an LLM key + telemetry, so it always speaks from true data. We will not ship a
fake "AI says…" that isn't reading real state.

## Endpoints

| Endpoint | What |
|---|---|
| `POST /route` | explainable routing + predicted success + checklist |
| `GET /sellers/{public_id}/trust` | trust score + components |
| `GET /marketplace/health` | supply/demand/economics/quality (live) |
| `GET /marketplace/health/summary` | NL summary from the live numbers |
| `GET /payments/{public_id}/timeline` | immutable timeline + why-failed |

## Tests

`marketplace_test.py` (18): empty marketplace → honest zeros; health reflects real
supply/economics; NL summary from live numbers; routing selects the bookable node with a
checklist + a real predicted-success factor; trust score + real completion rate + null
untracked dims; timeline shows the full history, explains a failure, and refuses a
non-party (404).
