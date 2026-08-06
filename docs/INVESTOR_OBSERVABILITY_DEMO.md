# Investor Observability Demo

How to run the investor demo and read the **Investor Demo** Grafana dashboard so an
investor can watch a real GPU job execute and a real (test-mode) Stripe settlement
move through the state machine — end to end, correlated, and provably not simulated.

## What the demo proves

A single click produces: a real workload running on a real GPU (DCGM utilization and
temperature rising on an actual node), the transaction walking the FSM
(`DRAFT → … → COMPLETED`), and Stripe **test-mode** money moving (authorize → capture →
seller transfer) — all correlated by one `transaction_id` across logs, traces, and
metrics. The point is: **real execution, real settlement mechanics, zero real money.**

## Required banners (always visible)

The dashboard and demo surface must display all three banners at all times:

- **REAL GPU EXECUTION** — the job runs on an actual GPU node, not a simulator.
- **STRIPE TEST MODE** — Stripe is in test mode (`STRIPE_MODE=test`,
  `PAYMENTS_LIVE_ENABLED=false`, `STRIPE_ALLOW_LIVE=false`); `payment_mode` is a
  test/demo value, never `live`.
- **NO REAL MONEY** — no live charge, capture, or payout occurs; test cards and test
  connected accounts only.

These banners are mandatory: they prevent any misreading of the demo as live
production money movement.

## Running the demo

1. Ensure live infrastructure is reachable: the DigitalOcean droplets (API + a real
   GPU seller node running `petabyte-seller-agent`) and the observability server
   (Collector, Prometheus, Loki, Tempo, Grafana). **The CI sandbox cannot reach these
   boxes** — the demo is verified live on the DigitalOcean + observability
   infrastructure, not in CI.
2. Confirm test-mode gating: `STRIPE_MODE=test`, `PAYMENTS_LIVE_ENABLED=false`,
   `STRIPE_ALLOW_LIVE=false`. Confirm `/health/observability` shows tracing + metrics
   active so the panels populate live.
3. Open the **Investor Demo** dashboard via the dedicated **read-only** Grafana account
   (Viewer role, scoped to the demo dashboards — see `OBSERVABILITY_SECURITY.md`).
4. Kick off a demo transaction (buyer checkout → quote → authorize with a Stripe **test
   card** → reserve → dispatch). Keep the `transaction_id` handy to follow it live.
5. Watch the panels update in real time as the job runs and settles.

## Reading the proof panels

| Panel | What it proves | Backing signal |
|---|---|---|
| GPU execution (live) | A real GPU is doing real work right now | DCGM `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_GPU_TEMP` rising on the node; `petabyte_gpus_online` |
| Fleet online | Real seller capacity exists | `petabyte_agents_online`, `petabyte_gpus_online` |
| Transaction state machine | The money flow is a validated FSM, not a mock | `petabyte_transaction_transitions_total{to_state,payment_mode}` stepping through states |
| Job lifecycle | The job really ran and passed validation | `petabyte_jobs_total{job_status}`, events `job.execution.started/completed`, `result.validation.passed` |
| Stripe settlement (test) | Authorize → capture → transfer actually executes | `petabyte_payment_captures_total{outcome,payment_mode}`, `petabyte_seller_transfers_total{outcome,payment_mode}` — all with a test/demo `payment_mode` |
| Ledger integrity | The books balance | `petabyte_ledger_imbalance_total` (flat at zero), `petabyte_reconciliation_discrepancies_total` (zero) |
| End-to-end latency | It's fast and real | `petabyte_job_startup_seconds`, `petabyte_job_duration_seconds`, `petabyte_payment_capture_duration_seconds` |

## Following one demo transaction live

Use the same reconstruction as `TRANSACTION_TRACE_GUIDE.md`, but live during the demo:

- Logs: `{environment="..."} | json | transaction_id="<TX>"` shows the event stream
  arriving in order.
- Trace: grab the `trace_id` from a log line and open it in Tempo (or the
  **Transaction Trace** dashboard) to show the span tree crossing API → agent → GPU
  executor → validator → settlement — visibly one flow across real machines.
- Authoritative timeline: `GET /payments/{TX}/timeline` shows the append-only
  `ComputeTxEvent` history (who/when/why) — the durable proof in Postgres.

## Talking points / integrity notes

- The `payment_mode` label on every settlement metric will read as a **test/demo**
  value — point to it as proof no live money moved.
- `petabyte_ledger_imbalance_total` and `petabyte_reconciliation_discrepancies_total`
  staying flat at zero demonstrates the double-entry ledger balances even under a live
  run.
- Seeded/demo figures elsewhere are always separable from real traction (the platform
  tags demo data); the Investor Demo dashboard is explicitly the **real-execution**
  view, badged accordingly, and must never present seeded numbers as real.
- If a panel is blank, it's an observability-pipeline issue, not a settlement issue —
  the money path is unaffected (`OBSERVABILITY_FAILURE_MODE=degrade`). See
  `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md`.
