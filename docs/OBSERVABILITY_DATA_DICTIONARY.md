# Observability Data Dictionary

The contract for Petabyte telemetry: every Prometheus metric, every stable log
`event_name`, and the correlation-id vocabulary. These names are consumed by
dashboards, alerts, runbooks, and future AI-ops features — **never rename in place**.

Two invariants hold throughout:

1. **Metric labels are bounded-cardinality enumerations only.** No transaction/job/
   user/GPU id is ever a metric label. Would-be labels are clamped to controlled sets
   via `bounded_label()`; values outside a set collapse to `other`.
2. **Business ids live in log/trace bodies**, queried in Loki as JSON fields
   (`| json | transaction_id="..."`), not as Loki labels.

## Label enumerations (bounded cardinality)

| Label | Allowed values |
|---|---|
| `environment` | deployment env: `production`, `staging`, `development`, … (one per deploy) |
| `payment_mode` | `test`, `live`, `sandbox`, `pilot`, `demo`, `real` |
| `job_status` | `queued`, `running`, `completed`, `failed`, `validated`, `invalid`, `cancelled` |
| `gpu_class` | `h100`, `a100`, `l40s`, `l4`, `a10`, `rtx4090`, `rtx3090`, `t4`, `v100`, `other` |
| `outcome` | `success`, `failure`, `skipped`, `retry` |
| `status_class` | HTTP class: `2xx`, `3xx`, `4xx`, `5xx` |
| `to_state` | any FSM state (see the transaction state machine) |
| `category` (webhooks) | Stripe event category (bounded) |
| `exporter` | `otlp`, `prometheus`, `loki`, `tempo`, `sentry` |
| `queue` | logical queue name (bounded) |
| `template` | workload template name (bounded set) |
| `reason` (auth) | bounded failure reason |
| `route` | matched route template with ids collapsed to `{id}` (`bounded_route`) |

## Metrics

### API / HTTP

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_http_requests_total` | Counter | `method`, `route`, `status_class`, `environment` | HTTP requests served, by outcome class. |
| `petabyte_http_request_duration_seconds` | Histogram | `method`, `route`, `environment` | Request latency distribution (use `_bucket` with `histogram_quantile`). |
| `petabyte_http_in_flight_requests` | Gauge | `environment` | Currently in-flight requests (saturation). |
| `petabyte_auth_failures_total` | Counter | `reason`, `environment` | Authentication failures. |
| `petabyte_authz_denials_total` | Counter | `environment` | Authorization denials. |
| `petabyte_ratelimit_blocks_total` | Counter | `route`, `environment` | Requests blocked by rate limiting. |
| `petabyte_validation_failures_total` | Counter | `environment` | Request validation failures. |

### Payments / settlement

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_payment_intent_attempts_total` | Counter | `outcome`, `payment_mode`, `environment` | PaymentIntent creation attempts. |
| `petabyte_payment_authorizations_total` | Counter | `outcome`, `payment_mode`, `environment` | Card authorizations. |
| `petabyte_payment_captures_total` | Counter | `outcome`, `payment_mode`, `environment` | Manual-capture completions (bill for metered usage). |
| `petabyte_payment_capture_duration_seconds` | Histogram | `payment_mode`, `environment` | Capture latency at Stripe. |
| `petabyte_seller_transfers_total` | Counter | `outcome`, `payment_mode`, `environment` | Transfers of net earning to seller connected accounts. |
| `petabyte_refunds_total` | Counter | `payment_mode`, `environment` | Refunds issued. |
| `petabyte_gmv_captured_minor_total` | Counter | `payment_mode`, `environment` | Gross captured amount (minor units). GMV "today" = `increase(...[24h])`. Split by `payment_mode` so a LIVE panel never sums TEST money. |
| `petabyte_platform_fees_minor_total` | Counter | `payment_mode`, `environment` | Platform commission captured (minor units). |
| `petabyte_seller_earnings_minor_total` | Counter | `payment_mode`, `environment` | Seller net earned at capture (minor units). |
| `petabyte_processing_fees_minor_total` | Counter | `payment_mode`, `environment` | Estimated card-processing fee the platform bears (minor units). Net margin = `platform_fees - processing_fees`; can be negative on small jobs. |
| `petabyte_webhooks_total` | Counter | `category`, `outcome`, `environment` | Stripe webhooks processed, by category and outcome. |
| `petabyte_webhook_invalid_signature_total` | Counter | `environment` | Webhooks that failed signature verification (misconfig or spoofing). |
| `petabyte_webhook_duplicate_total` | Counter | `environment` | Duplicate webhook deliveries absorbed idempotently. |
| `petabyte_reconciliation_discrepancies_total` | Counter | `environment` | Ledger/state vs. Stripe discrepancies detected. **Alert on any increase.** |
| `petabyte_ledger_imbalance_total` | Counter | `environment` | Double-entry ledger imbalance detections. **Must stay zero.** |

### Jobs / marketplace

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_jobs_total` | Counter | `job_status`, `template`, `gpu_class`, `environment` | Jobs by terminal status. |
| `petabyte_job_startup_seconds` | Histogram | `gpu_class`, `environment` | Booking→start latency. |
| `petabyte_job_duration_seconds` | Histogram | `gpu_class`, `environment` | Job execution duration. |
| `petabyte_reservation_conflicts_total` | Counter | `environment` | GPU reservation conflicts (contention). |
| `petabyte_routing_duration_seconds` | Histogram | `environment` | GPU routing/selection latency. |
| `petabyte_gpus_online` | Gauge | `environment` | GPUs currently online. |
| `petabyte_gpus_available` | Gauge | `environment` | GPUs available for reservation. |
| `petabyte_gpus_reserved` | Gauge | `environment` | GPUs currently reserved. |
| `petabyte_jobs_running` | Gauge | `environment` | Jobs currently running. |
| `petabyte_queue_depth` | Gauge | `queue`, `environment` | Depth of a named work queue. |

### Transaction spine

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_transaction_transitions_total` | Counter | `to_state`, `payment_mode`, `environment` | FSM state transitions (one per `transition()` call). The metric spine of the money flow. |

### Agents / fleet

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_agents_online` | Gauge | `environment` | Connected seller agents. |

### Telemetry health

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_telemetry_export_failures_total` | Counter | `exporter`, `environment` | Telemetry export failures per backend (degrade-mode signal; no app impact). |

### Marketing / newsletter

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `petabyte_newsletter_subscribe_requests_total` | Counter | `environment` | Newsletter signup requests received. |
| `petabyte_newsletter_subscribe_success_total` | Counter | `outcome`, `environment` | Signups accepted. `outcome`: `new` / `duplicate`. |
| `petabyte_newsletter_subscribe_failures_total` | Counter | `reason`, `environment` | Signup failures. `reason`: `mailgun` / `db`. |

### GPU hardware (DCGM exporter, per node)

| Metric | Type | Meaning |
|---|---|---|
| `DCGM_FI_DEV_GPU_TEMP` | Gauge | GPU temperature (°C). Thermal / overheat signal. |
| `DCGM_FI_DEV_GPU_UTIL` | Gauge | GPU utilization (%). Distinguishes a working job from a hung one. |
| `DCGM_FI_DEV_XID_ERRORS` | Counter/Gauge | NVIDIA XID hardware error events. Precedes node loss / result corruption. |

## Business & integrity gauges (scrape-time collector)

The counters/histograms above are incremented in-process as events happen. The gauges
below are different: they are computed **live from the database on every scrape** by the
marketplace collector (`_marketplace_metrics` in `main.py`, registered via
`register_marketplace_collector`) and served on `/internal/metrics`. They are point-in-time
snapshots — never `rate()`/`increase()` them. Each query runs in its own guarded block, so a
failure in one family never drops the others. All labels are bounded enumerations (never an
id); `environment` is present on every gauge and omitted from the tables below for brevity.

The supply gauges already listed under **Jobs / marketplace** (`petabyte_gpus_online`,
`petabyte_gpus_available`, `petabyte_gpus_reserved`, `petabyte_jobs_running`) and under
**Agents / fleet** (`petabyte_agents_online`) are emitted by this same collector.

### Supply / marketplace

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_sellers_registered` | Gauge | — | Distinct sellers with a listing. |
| `petabyte_sellers_online` | Gauge | — | Sellers with a fresh heartbeat. |
| `petabyte_sellers_offline` | Gauge | — | Sellers with all specs offline. |
| `petabyte_sellers_stale` | Gauge | — | Specs marked online but heartbeat expired. |
| `petabyte_available_gpu_hours` | Gauge | — | Available GPU-hours (units × max hrs). |
| `petabyte_gpus_by_model` | Gauge | `gpu_class` | Online GPUs by class. |
| `petabyte_gpus_by_country` | Gauge | `country` | Online GPUs by country (normalized 2-letter, `unknown` when empty). |

### Financial integrity (ledger + payout backlog)

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_ledger_balanced` | Gauge | — | `1` iff the double-entry ledger balances (every tx and overall). **Alert on `0`.** |
| `petabyte_ledger_imbalanced_tx` | Gauge | — | Ledger transactions whose debits ≠ credits. **Must stay 0.** |
| `petabyte_ledger_net_minor` | Gauge | — | Signed ledger sum (credits − debits) across all entries. **Must stay 0.** |
| `petabyte_payout_obligations_unbatched` | Gauge | — | Settled obligations owed to sellers but not yet placed in a batch. |
| `petabyte_oldest_unbatched_payout_age_seconds` | Gauge | — | Age of the oldest unbatched payout obligation (payout backlog). |
| `petabyte_seller_payable_minor` | Gauge | `payment_mode` | Outstanding seller payable (minor units), split by money mode. |

### Trust & integrity (the verification moat)

Same honest counts as the public `/trust` page (single source of truth).

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_attested_gpus` | Gauge | — | Attested GPUs (verifiable listings). |
| `petabyte_confidential_nodes_active` | Gauge | — | Nodes holding a fresh confidential (TEE) attestation. |
| `petabyte_jobs_completed_total` | Gauge | — | Completed jobs (lifetime; a snapshot gauge despite the `_total` name). |
| `petabyte_results_content_bound` | Gauge | — | Results bound to the sha256 of the real output bytes. |
| `petabyte_verifiable_receipts` | Gauge | — | Jobs with a retained node signature (buyer-verifiable receipt). |
| `petabyte_sellers_fraud_flagged` | Gauge | — | Sellers with fraud on record (payouts frozen pending review). |
| `petabyte_trust_tier_gpus` | Gauge | `tier` | Attested GPUs by trust tier. |
| `petabyte_quorum_checks` | Gauge | `status` | Redundant re-execution (quorum) checks by outcome. |

### Disaster recovery (database backups)

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_db_backup_last_age_seconds` | Gauge | — | Seconds since the last SUCCESSFUL backup (`-1` if none yet). **Alert when it grows.** |
| `petabyte_db_backups_ok` | Gauge | — | Successful backups currently retained. |
| `petabyte_db_backups_failed` | Gauge | — | Failed backup attempts on record. |
| `petabyte_db_backup_bytes` | Gauge | — | Total compressed size of retained backups. |

### Operations (VMs, clusters, disk, teams, escrow)

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_vms_active` | Gauge | — | Buyer VMs active (starting/running/migrating). |
| `petabyte_vm_migrations_cumulative` | Gauge | — | Cumulative VM failovers/migrations across all routes. |
| `petabyte_distributed_clusters` | Gauge | `status` | Distributed (multi-node) clusters by status. |
| `petabyte_disk_rental_nodes` | Gauge | — | Nodes actively renting spare disk. |
| `petabyte_disk_rental_gb_pledged` | Gauge | — | Total GB pledged for disk rental. |
| `petabyte_disk_rental_gb_used` | Gauge | — | GB actually reported used across disk-rental nodes. |
| `petabyte_teams_total` | Gauge | — | Teams (shared-wallet orgs). |
| `petabyte_teams_pooled_balance_usd` | Gauge | — | Total balance pooled in team wallets (USD). |
| `petabyte_escrow_held_usd` | Gauge | — | Buyer money currently held in escrow (live only, USD). |
| `petabyte_wallet_balance_usd` | Gauge | — | Total buyer wallet balance across all users (USD). |
| `petabyte_pending_tasks` | Gauge | `queue` | Buyer tasks awaiting a node. |
| `petabyte_oldest_pending_task_age_seconds` | Gauge | `queue` | Age of the oldest pending task (0 when empty). |

### Data-API monetization

| Metric | Type | Extra labels | Meaning |
|---|---|---|---|
| `petabyte_data_api_revenue_usd` | Gauge | — | All-time data-API revenue booked to platform revenue (USD). |
| `petabyte_data_api_revenue_usd_month` | Gauge | — | Data-API revenue this calendar month (USD). |
| `petabyte_data_api_billed_calls` | Gauge | — | All-time billed (paid) data-API calls. |
| `petabyte_data_api_paying_accounts_month` | Gauge | — | Accounts that paid for data-API calls this month. |

## Stable log `event_name` values

Emitted via `observability.event(name, ...)` — one structured JSON log line **and** a
span event on the current trace. Business ids ride in the body.

### Payment / settlement

| `event_name` | Meaning | Key fields |
|---|---|---|
| `payment.authorization.confirmed` | Card authorization verified server-side; tx → `PAYMENT_AUTHORIZED`. | `transaction_id`, `payment_intent_id` |
| `settlement.capture.completed` | Buyer captured for metered usage; tx → `PAYMENT_CAPTURED`. | `transaction_id`, `payment_intent_id`, `charge_id`, amount |
| `settlement.capture.failed` | Capture attempt failed (retryable or terminal). | `transaction_id`, `payment_intent_id`, reason |
| `settlement.commission.recorded` | Platform commission posted to the ledger. | `transaction_id`, amount |
| `settlement.seller_earning.created` | Seller's net earning obligation created. | `transaction_id`, `seller_id`, amount |
| `seller.transfer.created` | Transfer to the seller's connected account succeeded; tx → `SELLER_TRANSFERRED`. | `transaction_id`, `seller_id`, `transfer_id` |
| `seller.transfer.failed` | Transfer attempt failed. | `transaction_id`, `seller_id`, reason |
| `settlement.metering.finalized` | Actual usage metered; tx → `METERING_FINALIZED`. | `transaction_id`, seconds, source |

### GPU / job lifecycle

| `event_name` | Meaning | Key fields |
|---|---|---|
| `gpu.reservation.created` | GPU reserved for a tx; → `GPU_RESERVED`. | `transaction_id`, `reservation_id`/`booking_id`, `gpu_id` |
| `gpu.reservation.conflict` | Reservation lost a race / capacity conflict. | `transaction_id`, `gpu_id` |
| `job.dispatched` | Job handed to the worker/agent. | `transaction_id`, `job_id`, `agent_id` |
| `job.execution.started` | Container/job started on the GPU; → `RUNNING`. | `job_id`, `gpu_id`, `agent_id` |
| `job.execution.completed` | Job finished executing. | `job_id`, `gpu_id` |
| `job.execution.failed` | Job failed during execution. | `job_id`, reason |
| `result.validation.passed` | Result verified; billable. | `job_id`, `transaction_id` |
| `result.validation.failed` | Result rejected; do not capture as success. | `job_id`, reason |

### Transaction spine

| `event_name` | Meaning | Key fields |
|---|---|---|
| `transaction.transition` | Any FSM state change (the chokepoint). | `transaction_id`, `from_state`, `to_state`, `actor`, `reason` |
| `transaction.completed` | Terminal happy-path; → `COMPLETED`. | `transaction_id` |

### Webhooks

| `event_name` | Meaning | Key fields |
|---|---|---|
| `webhook.received` | Stripe webhook received (pre-verification). | `webhook_event_id`, `category` |
| `webhook.processing.failed` | Webhook handler errored (Stripe will retry). | `webhook_event_id`, reason |
| `webhook.duplicate` | Duplicate delivery absorbed; not re-applied. | `webhook_event_id` |

### Agent / infra

| `event_name` | Meaning | Key fields |
|---|---|---|
| `agent.heartbeat.missed` | A seller node missed its heartbeat (reap candidate). | `agent_id`, `gpu_id` |
| `redis.unavailable` | Redis unreachable; degraded to in-process. | component |

Related non-required-but-present events: `quote.calculated`,
`payment.authorization.requested`, `settlement.refund.created`, `result.uploaded`,
`webhook.verified`, `agent.enrolled`, `agent.reconnected`, `redis.lock.acquired`,
`redis.lock.conflict`, `http.request.completed`, `auth.failed`, `authz.denied`,
`ratelimit.blocked`, `request.validation.failed`, `unhandled.exception`.

## Correlation id vocabulary

The one correlation model, propagated via contextvars and W3C trace context across
services. All appear as JSON log fields and span attributes; **none** are metric
labels.

| Id | Meaning |
|---|---|
| `request_id` | Per-HTTP-request id (generated or sanitized from an inbound header). |
| `trace_id` / `span_id` | W3C trace/span ids linking logs (Loki) to traces (Tempo). |
| `run_id` | Correlates a multi-step run/operation. |
| `transaction_id` | `ComputeTransaction.public_id` — the money-flow spine. |
| `booking_id` / `reservation_id` | GPU booking / reservation. |
| `job_id` | Job / task id. |
| `buyer_id` / `seller_id` | User ids on the transaction. |
| `gpu_id` / `agent_id` | Seller GPU / node/agent. |
| `template_name` / `template_version` | Workload template identity. |
| `payment_intent_id` / `charge_id` / `transfer_id` / `refund_id` | Stripe object ids. |
| `webhook_event_id` | `StripeWebhookEvent` id. |
| `data_class` | Data-sensitivity tag driving redaction. |

## Loki label set (the only labels)

`service`, `environment`, `log_level`, `component`, `host_role`, `region`. Everything
else — including every id above — is a JSON field in the log body. Query pattern:

```logql
{service="petabyte-api", environment="production"} | json | transaction_id="<TX>"
```
