# Runbook: Worker Queue Backlog

Jobs are accumulating faster than they are dispatched/executed. Queue depth is rising
and time-to-start is climbing.

## Symptoms

- `petabyte_queue_depth` trending up and not draining.
- Rising `petabyte_job_startup_seconds` (booking-to-start latency).
- Buyers report jobs "stuck in queued".
- Grafana alert `QueueBacklogHigh` / `JobStartupLatencyHigh` firing.

## Impact

- Buyers wait; authorizations age toward `AUTHORIZATION_EXPIRED` if a job cannot start
  before the Stripe authorization window closes (that expiry voids the auth — no
  capture, no charge).
- Seller GPUs may sit idle while work waits, hurting utilization and marketplace
  liquidity.

## Dashboard

**Workers & Queue** (primary) and **Seller-Agent Fleet** (is there capacity to drain
into?).

## Loki query

```logql
{service="petabyte-worker"} | json | event_name=~"job.dispatched|gpu.reservation.conflict"
```

Inspect one backed-up job:

```logql
{service="petabyte-api"} | json | job_id="<JOB_ID>"
{service="petabyte-api"} | json | transaction_id="<TX>"
```

## Metrics to inspect

- `petabyte_queue_depth{queue="...",environment="production"}`:
  ```promql
  max by (queue) (petabyte_queue_depth{environment="production"})
  ```
- `petabyte_job_startup_seconds` (p95 startup latency):
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(petabyte_job_startup_seconds_bucket{environment="production"}[10m])))
  ```
- Supply vs. demand:
  ```promql
  petabyte_agents_online{environment="production"}
  petabyte_gpus_online{environment="production"}
  ```
- `petabyte_reservation_conflicts_total` — contention forcing re-tries:
  ```promql
  increase(petabyte_reservation_conflicts_total{environment="production"}[15m])
  ```

## Trace to inspect

1. Pick a long-queued `job_id`/`transaction_id` from Loki.
2. Read its `trace_id`; open in **Tempo** (or **Transaction Trace** dashboard).
3. The span tree reveals where the delay is: reservation (`gpu.reservation.created`
   vs `gpu.reservation.conflict`), dispatch (`job.dispatched`), or agent pickup
   (`job.execution.started`).

## Safe first actions

1. Determine the bottleneck class:
   - **No capacity**: `petabyte_agents_online` / `petabyte_gpus_online` too low for
     demand — a supply problem, not a worker problem.
   - **Capacity exists but idle**: dispatch/worker problem — check worker health,
     `redis.unavailable`, or reservation conflicts.
2. Check worker process health and concurrency (`WEB_CONCURRENCY`, worker service
   status). Restart wedged workers (safe — dispatch is idempotent at the reservation
   layer).
3. If Redis coordination is implicated, see `REDIS_UNAVAILABLE.md`.
4. If specific agents are offline, see `SELLER_AGENT_OFFLINE.md`.

## Escalation criteria

- Backlog growing > 30 min despite available capacity.
- Startup latency high enough that authorizations are expiring
  (`AUTHORIZATION_EXPIRED` transitions increasing) — this loses bookings.
- Suspected dispatch deadlock / poison job repeatedly failing and re-queuing.

## Recovery verification

- `petabyte_queue_depth` drains back to baseline.
- `petabyte_job_startup_seconds` p95 back to normal.
- No abnormal rise in `AUTHORIZATION_EXPIRED`:
  ```promql
  increase(petabyte_transaction_transitions_total{to_state="AUTHORIZATION_EXPIRED",environment="production"}[1h])
  ```

## Financial-safety considerations

- A backlog itself moves no money. The risk is **authorization expiry**: a job that
  can't start in time transitions to `AUTHORIZATION_EXPIRED` and the card auth is
  voided — the buyer is correctly **not** charged.
- Never "force" a stale job to run by editing state; go through the FSM. Capturing
  after an expired authorization is impossible by design and must not be worked around.
- If you cancel queued jobs to shed load, ensure each goes through `CANCELLED`
  (void auth, release GPU, charge $0) — do not orphan a held authorization.
