# Runbook: Database Unavailable

Postgres — the durable, authoritative ledger — is unreachable, read-only, or
failing queries. This is the most financially sensitive dependency in Petabyte.

## Symptoms

- `/readyz` returns `503 {"status":"not_ready","database":"unreachable"}`;
  `/health/ready` returns 503 with `"database":"unreachable"`.
- API logs full of connection/timeout errors to Postgres; `event_name` of
  `unhandled.exception` around DB calls.
- Writes failing: transitions do not persist, `ComputeTxEvent` rows are not appended,
  captures/transfers cannot start.
- Grafana alert `DatabaseUnreachable` firing.

## Impact

- Platform is effectively down for anything stateful: quotes, authorizations,
  reservations, dispatch, capture, transfer, refunds.
- The double-entry ledger (`db.post()`) cannot accept new postings; all money
  movement halts. This is the correct fail-closed behavior — no money should move
  while the ledger is unwritable.

## Dashboard

**Infrastructure** (DB health, connections, replication) and **API** (readiness /
error propagation).

## Loki query

```logql
{service="petabyte-api", log_level="ERROR"} | json |~ "(?i)(database|psycopg|connection|deadlock|timeout)"
```

Correlate to a specific stuck transaction:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
```

## Metrics to inspect

- `up{job="postgres"}` / DB exporter connection and saturation gauges on the
  Infrastructure dashboard (active connections vs. `max_connections`, replication lag,
  disk usage).
- `petabyte_http_requests_total{status_class="5xx"}` — user-visible fallout:
  ```promql
  sum(rate(petabyte_http_requests_total{status_class="5xx"}[5m]))
  ```
- After recovery, watch `petabyte_ledger_imbalance_total` and
  `petabyte_reconciliation_discrepancies_total`:
  ```promql
  increase(petabyte_ledger_imbalance_total{environment="production"}[1h])
  increase(petabyte_reconciliation_discrepancies_total{environment="production"}[1h])
  ```

## Trace to inspect

1. From the Loki query, take a `transaction_id` (or `request_id`) that failed.
2. Read its `trace_id` field, open in Grafana → Explore → **Tempo**, or via the
   **Transaction Trace** dashboard.
3. The span tree shows the failing DB span (recorded exception + ERROR status) and
   confirms nothing downstream (Stripe capture/transfer) ran — i.e. no partial money
   movement occurred.

## Safe first actions

1. Confirm scope: is it connectivity (network/firewall/credentials), the DB process,
   disk-full, connection exhaustion, or a failover in progress?
2. Check `DATABASE_URL` reachability from the API host; check Postgres logs, disk,
   and `max_connections`.
3. If connections are exhausted, identify and kill runaway/idle-in-transaction
   sessions; do **not** blindly restart Postgres mid-write if a clean drain is
   possible.
4. If disk is full, free space (WAL/archive) before restart.
5. Once Postgres is healthy, `/readyz` recovers on its own; restart `petabyte-api`
   only if its connection pool is wedged.

## Escalation criteria

- Any suspected data loss, corruption, or need to restore from backup — page the
  platform lead / DBA **immediately** and treat as a financial incident.
- Failover did not complete, or the primary cannot be recovered in < 15 min.
- `petabyte_ledger_imbalance_total` increases after recovery.

## Recovery verification

- `/readyz` and `/health/ready` return 200 with `"database":"ok"`.
- `/health/ready` shows `maintenance.stale == false` (the reaper resumed).
- Run the ledger balance / reconciliation check; `petabyte_ledger_imbalance_total`
  and `petabyte_reconciliation_discrepancies_total` show **no** new increments.
- Drain stuck settlements: transactions in `PAYMENT_CAPTURE_PENDING` /
  `SELLER_TRANSFER_PENDING` resume via the idempotent path.

## Financial-safety considerations

- Postgres is the **permanent** financial record. Loki and Tempo are diagnostic and
  short-retention — never reconstruct the ledger from them.
- Persist-before-call means a crash between "row written" and "Stripe called" is
  recoverable: on resume the deterministic idempotency key prevents a second
  capture/transfer. Do not manually re-run Stripe calls to compensate for the outage.
- If a restore-from-backup is ever required, any Stripe activity that occurred after
  the backup point must be reconciled against Stripe as source of truth before
  resuming settlement.

## See also

- `API_UNAVAILABLE.md` — the maintenance/reaper loop runs inside the API process; if
  `maintenance.stale == true` while Postgres is healthy, triage the API process here.
