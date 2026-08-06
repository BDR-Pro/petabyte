# Observability Dashboards

The Grafana dashboards that ship with Petabyte, what each one shows, and who uses it.
All are backed by Prometheus (metrics), Loki (logs), and Tempo (traces); the
transaction-level dashboards link Loki → Tempo by `trace_id`.

## Executive Marketplace

- **Shows**: top-line marketplace health — request volume and error rate, GMV /
  revenue trend, jobs completed vs. failed, completion rate, active buyers/sellers,
  supply online (`petabyte_agents_online`, `petabyte_gpus_online`), and settlement
  throughput. The "is the business healthy right now" view.
- **Key metrics**: `petabyte_http_requests_total`, `petabyte_jobs_total`,
  `petabyte_payment_captures_total`, `petabyte_seller_transfers_total`,
  `petabyte_agents_online`, `petabyte_gpus_online`.
- **Who**: founders/leadership and on-call for blast-radius at a glance.

## Transaction Trace

- **Shows**: a single transaction end to end. Paste a `transaction_id` to see its FSM
  timeline, the correlated log lines, and a link into the Tempo trace. The forensic
  view behind `TRANSACTION_TRACE_GUIDE.md`.
- **Key signals**: FSM transitions (`petabyte_transaction_transitions_total`), the
  event stream (`transaction.transition`, `settlement.*`, `job.*`, `gpu.*`), and the
  `trace_id` jump-off to Tempo.
- **Who**: on-call and support debugging one buyer/seller/job.

## API

- **Shows**: HTTP-layer health — request rate, status-class breakdown, p50/p95/p99
  latency, in-flight requests, auth/authz failures, rate-limit blocks, validation
  failures.
- **Key metrics**: `petabyte_http_requests_total`,
  `petabyte_http_request_duration_seconds`, `petabyte_http_in_flight_requests`,
  `petabyte_auth_failures_total`, `petabyte_ratelimit_blocks_total`.
- **Who**: on-call for `runbooks/API_UNAVAILABLE.md`.

## Workers & Queue

- **Shows**: dispatch pipeline — queue depth by queue, job startup latency,
  reservation conflicts, running jobs vs. capacity, worker throughput.
- **Key metrics**: `petabyte_queue_depth`, `petabyte_job_startup_seconds`,
  `petabyte_reservation_conflicts_total`, `petabyte_jobs_running`.
- **Who**: on-call for `runbooks/WORKER_QUEUE_BACKLOG.md`.

## Seller-Agent Fleet

- **Shows**: the seller GPU fleet — agents/GPUs online, available vs. reserved,
  heartbeat health (`agent.heartbeat.missed`), and per-node GPU health from DCGM
  (`DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_XID_ERRORS`).
- **Key metrics**: `petabyte_agents_online`, `petabyte_gpus_online`,
  `petabyte_gpus_available`, `petabyte_gpus_reserved`, DCGM series.
- **Who**: on-call for `runbooks/SELLER_AGENT_OFFLINE.md` and
  `runbooks/GPU_JOB_STUCK.md`; supply/marketplace ops.

## Stripe & Settlement

- **Shows**: the money path — PaymentIntent attempts, authorizations, captures
  (success/failure + latency), seller transfers, refunds, webhook throughput and
  invalid signatures, reconciliation discrepancies, ledger imbalance.
- **Key metrics**: `petabyte_payment_captures_total`,
  `petabyte_payment_capture_duration_seconds`, `petabyte_seller_transfers_total`,
  `petabyte_refunds_total`, `petabyte_webhooks_total`,
  `petabyte_webhook_invalid_signature_total`,
  `petabyte_reconciliation_discrepancies_total`, `petabyte_ledger_imbalance_total`.
- **Who**: settlement owner and on-call for all payment/webhook/transfer/ledger
  runbooks.

## Infrastructure

- **Shows**: platform substrate — host CPU/mem/disk, Postgres health
  (connections, replication, disk), Redis health/memory, and the observability backends
  themselves (Collector queues, Prometheus/Loki/Tempo ingestion, scrape `up{}`
  targets, `petabyte_telemetry_export_failures_total`).
- **Who**: on-call for `runbooks/DATABASE_UNAVAILABLE.md`,
  `runbooks/REDIS_UNAVAILABLE.md`, and `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md`.

## Investor Demo

- **Shows**: a curated proof-of-real-execution view for investors — real GPU jobs
  running (with DCGM utilization/temperature), real Stripe **test-mode** settlement
  moving through the FSM, and the correlation from click → GPU → capture. Carries the
  mandatory banners **REAL GPU EXECUTION**, **STRIPE TEST MODE**, **NO REAL MONEY**.
- **Who**: viewed via a dedicated **read-only** Grafana account during demos. See
  `INVESTOR_OBSERVABILITY_DEMO.md`.
