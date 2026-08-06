# Observability Alerts

Alert rules grouped by category, with the condition summary, user impact, and the
runbook to open when it fires. Conditions are expressed against the canonical
Prometheus metrics; tune thresholds/windows per environment. Severity: **P1** (page
now), **P2** (page during hours / urgent), **P3** (warning / ticket).

Standard label filter on every rule: `environment="production"` (swap per environment).

## Availability

| Alert | Severity | Condition (summary) | Impact | Runbook |
|---|---|---|---|---|
| `APIDown` | P1 | `up{job="petabyte-api"} == 0` for 2m, or `/healthz` failing | Platform down; no quotes/auth/dispatch/settlement | `runbooks/API_UNAVAILABLE.md` |
| `APIHighErrorRate` | P1 | 5xx share `rate(petabyte_http_requests_total{status_class="5xx"}) / rate(petabyte_http_requests_total)` > 0.05 for 5m | Users failing; degraded service | `runbooks/API_UNAVAILABLE.md` |
| `DatabaseUnreachable` | P1 | `/readyz` 503 / DB `up == 0` for 2m | All stateful ops + money movement halt | `runbooks/DATABASE_UNAVAILABLE.md` |
| `ReaperStale` | P2 | `/health/ready` `maintenance.stale == true` | Reaper dead: VMs never expire, dead nodes stay listed, bookings never settle | `runbooks/DATABASE_UNAVAILABLE.md` / `API_UNAVAILABLE.md` |
| `RedisUnavailable` | P3 | `event_name="redis.unavailable"` present / `up{job="redis"} == 0` | Degraded coordination only (in-process fallback) | `runbooks/REDIS_UNAVAILABLE.md` |

## Performance

| Alert | Severity | Condition (summary) | Impact | Runbook |
|---|---|---|---|---|
| `APILatencyHigh` | P2 | p95 `histogram_quantile(0.95, rate(petabyte_http_request_duration_seconds_bucket[5m]))` > 1s for 10m | Slow UX; possible saturation | `runbooks/API_UNAVAILABLE.md` |
| `QueueBacklogHigh` | P2 | `max(petabyte_queue_depth)` above threshold and rising for 15m | Jobs waiting; auth-expiry risk | `runbooks/WORKER_QUEUE_BACKLOG.md` |
| `JobStartupLatencyHigh` | P2 | p95 `petabyte_job_startup_seconds` above threshold for 15m | Slow time-to-start; auth-expiry risk | `runbooks/WORKER_QUEUE_BACKLOG.md` |
| `ReservationConflictsHigh` | P3 | `increase(petabyte_reservation_conflicts_total[15m])` above threshold | Contention / degraded locking | `runbooks/REDIS_UNAVAILABLE.md` / `WORKER_QUEUE_BACKLOG.md` |

## Payments & settlement

| Alert | Severity | Condition (summary) | Impact | Runbook |
|---|---|---|---|---|
| `LedgerImbalance` | P1 | `increase(petabyte_ledger_imbalance_total[1h]) > 0` | Financial-correctness breach | `runbooks/LEDGER_RECONCILIATION_FAILURE.md` |
| `ReconciliationDiscrepancy` | P1 | `increase(petabyte_reconciliation_discrepancies_total[1h]) > 0` | Ledger vs. Stripe divergence | `runbooks/LEDGER_RECONCILIATION_FAILURE.md` |
| `PaymentCaptureFailures` | P1 | `rate(petabyte_payment_captures_total{outcome="failure"})` share > 0.1 for 10m | Delivered jobs unbilled; payout blocked | `runbooks/PAYMENT_CAPTURE_FAILURE.md` |
| `SellerTransferFailures` | P2 | `rate(petabyte_seller_transfers_total{outcome="failure"})` share > 0.1 for 15m | Sellers unpaid | `runbooks/SELLER_TRANSFER_FAILURE.md` |
| `WebhookInvalidSignature` | P2 | `increase(petabyte_webhook_invalid_signature_total[15m]) > 0` | Misconfig or spoofing attempt | `runbooks/STRIPE_WEBHOOK_FAILURE.md` |
| `WebhookProcessingFailures` | P2 | `sum(increase(petabyte_webhooks_total{outcome="failure"}[15m]))` above threshold | Settlement out of sync with Stripe | `runbooks/STRIPE_WEBHOOK_FAILURE.md` |
| `AuthorizationExpirySpike` | P2 | `increase(petabyte_transaction_transitions_total{to_state="AUTHORIZATION_EXPIRED"}[1h])` above baseline | Lost bookings (auth voided before capture) | `runbooks/WORKER_QUEUE_BACKLOG.md` / `PAYMENT_CAPTURE_FAILURE.md` |

## Jobs

| Alert | Severity | Condition (summary) | Impact | Runbook |
|---|---|---|---|---|
| `JobFailureRateHigh` | P2 | `rate(petabyte_jobs_total{job_status="failed"}) / rate(petabyte_jobs_total)` above threshold for 15m | Buyers' jobs failing; refunds up | `runbooks/GPU_JOB_STUCK.md` / `SELLER_AGENT_OFFLINE.md` |
| `ResultValidationFailureRateHigh` | P2 | invalid share `rate(petabyte_jobs_total{job_status="invalid"}) / rate(petabyte_jobs_total{job_status=~"validated|invalid"})` above threshold | Good jobs failing validation, or bad results caught | `runbooks/RESULT_VALIDATION_FAILURE.md` |
| `JobDurationOutliers` | P3 | p95 `petabyte_job_duration_seconds` by `gpu_class` far above baseline | Stuck/hung jobs | `runbooks/GPU_JOB_STUCK.md` |

## Infrastructure

| Alert | Severity | Condition (summary) | Impact | Runbook |
|---|---|---|---|---|
| `SellerAgentsDropped` | P2 | `delta(petabyte_agents_online[10m])` sharply negative | Supply loss; queue backlog risk | `runbooks/SELLER_AGENT_OFFLINE.md` |
| `GpusOnlineDropped` | P2 | `delta(petabyte_gpus_online[10m])` sharply negative | Capacity loss | `runbooks/SELLER_AGENT_OFFLINE.md` |
| `GpuXidErrors` | P2 | `increase(DCGM_FI_DEV_XID_ERRORS[15m]) > 0` | GPU hardware faults; result corruption risk | `runbooks/GPU_JOB_STUCK.md` / `SELLER_AGENT_OFFLINE.md` |
| `GpuOverheat` | P3 | `DCGM_FI_DEV_GPU_TEMP` above safe threshold | Thermal throttling / imminent node loss | `runbooks/SELLER_AGENT_OFFLINE.md` |
| `TelemetryExportFailures` | P3 | `increase(petabyte_telemetry_export_failures_total[15m])` above threshold | Blind spots (no app impact — degrade mode) | `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md` |
| `MetricsTargetDown` | P3 | `up{job=~"petabyte-.*"} == 0` for 5m | Missing metrics for that target | `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md` |

## Alerting principles

- **Money alerts fail closed and page.** Any `petabyte_ledger_imbalance_total` or
  `petabyte_reconciliation_discrepancies_total` increment is P1 — a single event, not a
  rate, is enough.
- **Degrade-mode alerts do not page as outages.** Telemetry export failures and Redis
  unavailability are warnings; the app is designed to keep running.
- Every alert links to exactly one first-responder runbook above.
