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

### GPU hardware (DCGM exporter, per node)

| Metric | Type | Meaning |
|---|---|---|
| `DCGM_FI_DEV_GPU_TEMP` | Gauge | GPU temperature (°C). Thermal / overheat signal. |
| `DCGM_FI_DEV_GPU_UTIL` | Gauge | GPU utilization (%). Distinguishes a working job from a hung one. |
| `DCGM_FI_DEV_XID_ERRORS` | Counter/Gauge | NVIDIA XID hardware error events. Precedes node loss / result corruption. |

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
