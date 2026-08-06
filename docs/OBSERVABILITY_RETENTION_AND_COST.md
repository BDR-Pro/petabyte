# Observability Retention and Cost

Retention, sampling, and bounding guidance for the telemetry backends, and the
non-negotiable rule that **telemetry is never the financial record**.

## The one rule that governs all retention

**Payment and settlement audit data lives durably in Postgres.** The
`ComputeTransaction` FSM state, the append-only `ComputeTxEvent` history, the
double-entry ledger postings (`db.post()`), `PaymentOperation` rows, `Settlement`
rows, and `StripeWebhookEvent` records are the **permanent** financial record and are
retained per your financial/compliance policy (years, backed up).

Loki, Tempo, Prometheus, and Sentry are **diagnostic** systems with short retention.
**Never** reconstruct, reconcile, or prove a financial fact from them. If a trace or
log has aged out, the truth is still in Postgres and in Stripe.

## Retention guidance by backend

| Backend | Suggested retention | Notes |
|---|---|---|
| **Prometheus** | ~15d raw; longer via downsampled/recording-rule aggregates | Keep high-resolution short; roll up business KPIs (GMV, capture counts, uptime) into recording rules / long-term store for trend dashboards. |
| **Loki** | ~7–14d | Structured JSON logs are the bulk of volume. Financial events are also in Postgres, so logs can expire safely. |
| **Tempo** | ~72h | Traces are for live/near-term debugging. A `transaction_id` still reconstructs the flow from Postgres + Loki + Stripe after traces expire. |
| **Sentry** | Per plan event quota (fixed monthly quota) | Control volume with `SENTRY_TRACES_SAMPLE_RATE`; reserve error-event budget for real errors. |
| **Redis** | Not a store of record | `maxmemory` with `maxmemory-policy allkeys-lru`; it is a cache/coordination layer only. Losing it is a degrade, not data loss. |
| **Postgres (financial)** | Long-term per policy | The durable ledger; backed up and retained for audit. |

## Sampling and volume controls

- **Trace sampling** — `OTEL_TRACE_SAMPLE_RATIO` (default `1.0`). Lower it under high
  volume; the sampler is `ParentBased(TraceIdRatioBased(ratio))`, so a sampled parent
  keeps its children — a `transaction_id`'s trace stays whole or absent, not partial.
  Consider keeping money-path traces at higher effective sampling than routine reads.
- **Sentry sampling** — `SENTRY_TRACES_SAMPLE_RATE` bounds performance-trace volume;
  errors are captured on their own quota.
- **Metrics cardinality** — the dominant cost driver for Prometheus. Petabyte caps it
  at the source: labels are **bounded enumerations only** (`bounded_label`), routes are
  collapsed to `{id}` (`bounded_route`), and **no** id is ever a label. Do not add
  high-cardinality labels; put ids in log/trace bodies instead.

## Per-signal bounds (protect the pipeline and the bill)

- **Max log line size** — cap log line / field length so a large payload can't bloat
  Loki. Redaction already truncates lists (≤200 items) and bounds recursion depth (≤6).
- **Max attributes / span events per span** — keep span attributes and span-event
  counts bounded; the batch processor uses `OBSERVABILITY_QUEUE_SIZE` (2048) and
  `OBSERVABILITY_BATCH_SIZE` (512) with a `OBSERVABILITY_EXPORT_TIMEOUT_SECONDS` (5s)
  export timeout — spans are dropped rather than allowed to back up unboundedly.
- **Max payload capture** — never log full workload inputs/outputs; capture sizes,
  hashes, and ids instead. This is both a cost and a security control (redaction
  strips secrets/PII regardless).
- **DCGM scrape interval** — GPU metrics sample on `GPU_METRICS_INTERVAL` (default 10s);
  widen it if per-node series volume becomes a cost concern.

## Cost posture summary

- Spend the metric budget on **bounded**, business-meaningful series; spend the log
  budget on **structured events with ids**, not verbose free text; spend the trace
  budget on **sampled** end-to-end flows.
- Because everything financial is durably in Postgres, you can keep Loki/Tempo/
  Prometheus retention short and cheap without any audit risk.
- If a backend is dropping data or over quota, that is a diagnostics/cost issue — see
  `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md`. It is **never** a reason to make
  telemetry blocking (`OBSERVABILITY_FAILURE_MODE` stays `degrade` in production) and
  **never** a reason to treat lost telemetry as lost money.
