# Runbook: API Unavailable

`petabyte-api` (the platform FastAPI service) is not serving requests, or is
serving 5xx/timeouts for a material share of traffic.

## Symptoms

- `/healthz` (liveness) or `/readyz` (readiness) return non-200, time out, or the
  process is not listening on `BIND` (default `127.0.0.1:8000` behind nginx).
- Users report the site/API is down; nginx returns 502/504.
- Elevated 5xx rate on the API dashboard; `petabyte_http_in_flight_requests` pinned
  high (event-loop saturation) or dropping to zero (process dead).
- Grafana alerts `APIDown` / `APIHighErrorRate` / `APILatencyHigh` firing.

## Impact

- Buyers cannot create quotes, authorize payments, reserve GPUs, or dispatch jobs.
- In-flight jobs keep running on seller agents (they poll `/jobs/next` and report
  back), but capture/settlement of finished jobs stalls until the API recovers.
- No money moves incorrectly: settlement is DB-backed and idempotent, so a hard
  outage delays money movement rather than corrupting it.

## Dashboard

**API** (primary) and **Executive Marketplace** (blast-radius / traffic view).

## Loki query

Confirm the service is logging and see the last errors before it stopped:

```logql
{service="petabyte-api", log_level="ERROR"} | json
```

Scope to one impacted request/transaction:

```logql
{service="petabyte-api"} | json | request_id="<REQUEST_ID>"
{service="petabyte-api"} | json | transaction_id="<TX>"
```

Look for `event_name="unhandled.exception"`, and for a burst that stops abruptly
(process died) vs. a burst that continues (dependency failure).

## Metrics to inspect

- `petabyte_http_requests_total{status_class="5xx"}` — error volume:
  ```promql
  sum(rate(petabyte_http_requests_total{environment="production",status_class="5xx"}[5m]))
  /
  sum(rate(petabyte_http_requests_total{environment="production"}[5m]))
  ```
- `petabyte_http_request_duration_seconds` — latency (p95):
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(petabyte_http_request_duration_seconds_bucket{environment="production"}[5m])))
  ```
- `petabyte_http_in_flight_requests{environment="production"}` — saturation.
- `up{job="petabyte-api"}` — is the scrape target even reachable? (If the target is
  down, the API's own counters go stale — treat absence of data as a strong signal.)

## Trace to inspect

1. Grab a failing `request_id` or `transaction_id` from the Loki query above.
2. Read the `trace_id` JSON field off any matching log line
   (`... | json | line_format "{{.trace_id}}"`).
3. In Grafana → Explore → **Tempo** → search by that Trace ID, or open the
   **Transaction Trace** dashboard and paste the id. The `http.request` server span
   (see `observability.span("http.request", kind="server", ...)`) shows where time
   went and carries the recorded exception on error.

## Safe first actions

1. Check `/healthz` and `/readyz` directly on the box (bypass nginx):
   `curl -s localhost:8000/healthz`. `readyz` returns 503 with
   `database unavailable` when Postgres is the real cause — if so, switch to
   `DATABASE_UNAVAILABLE.md`.
2. Check the process/service and nginx upstream; review `systemctl status` and the
   most recent deploy. If the incident started at a deploy, **roll back** to the
   previous release.
3. Confirm resource exhaustion (CPU, memory/OOM-kill, disk full, file descriptors).
4. Restart `petabyte-api` (workers are `WEB_CONCURRENCY`). A restart is safe:
   startup replays nothing destructive, and settlement is idempotent.
5. Confirm `/health/observability` — if telemetry is degraded but the app is up,
   that is a separate, non-blocking issue (see `OBSERVABILITY_PIPELINE_FAILURE.md`).

## Escalation criteria

- Full outage > 5 min, or error rate > 25% for > 10 min.
- Restart does not recover, or the process crash-loops.
- Root cause points at Postgres, Stripe, or the host/provider — page the on-call
  owner for that dependency and the platform lead.

## Recovery verification

- `/healthz` and `/readyz` return 200; `petabyte_http_in_flight_requests` settles to
  a normal band.
- 5xx rate back under baseline; p95 latency normal.
- Spot-check a real flow: quote → authorize (Stripe **test** mode) → timeline.
- Drain any settlement backlog: transactions stuck in `METERING_FINALIZED` or
  `PAYMENT_CAPTURE_PENDING` should progress once the API is healthy.

## Financial-safety considerations

- Postgres is the durable ledger; an API outage never loses committed transaction
  state or `ComputeTxEvent` history.
- Every Stripe mutation is guarded by a persist-before-call `PaymentOperation` with a
  deterministic idempotency key, so restarts/retries cannot double-capture or
  double-transfer.
- Do **not** manually poke Stripe or the DB to "unstick" money during the outage —
  let the idempotent settlement path resume. Reconcile afterward via
  `LEDGER_RECONCILIATION_FAILURE.md` if `petabyte_reconciliation_discrepancies_total`
  or `petabyte_ledger_imbalance_total` moved.
