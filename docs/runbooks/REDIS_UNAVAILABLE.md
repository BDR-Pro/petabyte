# Runbook: Redis Unavailable

Redis is **optional** in Petabyte. When it is down, the platform degrades to
in-process behavior (locks, queue/dispatch coordination, caches) rather than failing.
This runbook is about confirming the degrade is clean and restoring Redis.

## Symptoms

- Log lines with `event_name="redis.unavailable"`; occasional `redis.lock.conflict`.
- Grafana alert `RedisUnavailable` (warning severity — not an outage).
- Cross-process coordination weaker than usual: e.g. the maintenance/reaper leader
  election falls back to in-process, queue depth visibility may be reduced.

## Impact

- **No hard outage.** The API keeps serving; jobs keep dispatching; settlement keeps
  running (settlement correctness depends on **Postgres**, not Redis).
- Degraded coordination: distributed locks become in-process only. On a multi-worker/
  multi-host deployment this weakens cross-instance mutual exclusion, so watch for
  duplicate work and reservation contention.
- Any Redis-backed queue depth signal may be stale; `petabyte_queue_depth` can read
  low/empty if the queue lived in Redis.

## Dashboard

**Workers & Queue** (queue depth, dispatch coordination) and **Infrastructure**
(Redis process/memory).

## Loki query

```logql
{service="petabyte-api"} | json | event_name="redis.unavailable"
```

Also check lock contention across services:

```logql
{environment="production"} | json | event_name=~"redis.lock.(conflict|acquired)"
```

## Metrics to inspect

- `petabyte_queue_depth{queue="...",environment="production"}` — is queue visibility
  intact?
  ```promql
  max by (queue) (petabyte_queue_depth{environment="production"})
  ```
- `petabyte_reservation_conflicts_total` — degraded locking can raise conflicts:
  ```promql
  increase(petabyte_reservation_conflicts_total{environment="production"}[15m])
  ```
- `up{job="redis"}` and Redis memory (`maxmemory`, evictions) on Infrastructure.

## Trace to inspect

1. Find an affected `transaction_id`/`job_id` from Loki around the
   `redis.unavailable` events.
2. Pull its `trace_id`, open in **Tempo** (or the **Transaction Trace** dashboard).
3. Confirm the flow still completed via the in-process path — spans for reservation
   and dispatch should still be present and successful.

## Safe first actions

1. Confirm this is a degrade, not a masked outage: API `/healthz` should still be
   200. If the app is actually down, use `API_UNAVAILABLE.md` — Redis being down
   should not, by design, take the app down.
2. Restore Redis: check the process, `bind`/auth, firewall, and `maxmemory` /
   eviction policy (`allkeys-lru` is expected). Restart if needed.
3. On a multi-host deploy, if degraded locking is causing duplicate dispatch or
   reservation churn, consider temporarily reducing to a single writer worker until
   Redis is back.

## Escalation criteria

- Redis outage coincides with rising `petabyte_reservation_conflicts_total` or
  observed duplicate dispatch on a multi-host fleet.
- `REDIS_URL` credentials/network cannot be restored quickly and the deployment
  relies on Redis for cross-host coordination.

## Recovery verification

- `redis.unavailable` events stop; `up{job="redis"}` is 1.
- `petabyte_queue_depth` reflects reality again; `petabyte_reservation_conflicts_total`
  returns to baseline.
- Spot-check a full transaction end-to-end.

## Financial-safety considerations

- Redis holds **no** financial truth. Money movement is governed by Postgres, the FSM
  `transition()` chokepoint, and idempotent `PaymentOperation` rows.
- Losing Redis cannot double-charge or double-pay: capture/transfer idempotency keys
  are deterministic and enforced at the DB, independent of any Redis lock.
- Do not treat a stale `petabyte_queue_depth` as a settlement problem — verify against
  transaction states in Postgres.

## See also

- `WORKER_QUEUE_BACKLOG.md` — sustained reservation contention
  (`petabyte_reservation_conflicts_total`) can accompany or drive a queue backlog.
