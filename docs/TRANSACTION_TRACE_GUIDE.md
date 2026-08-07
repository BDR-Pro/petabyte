# Transaction Trace Guide

How to reconstruct the **entire** life of one compute transaction from a single
`transaction_id`, across logs (Loki), traces (Tempo), corroborating metrics
(Prometheus), and the authoritative append-only history in Postgres.

You start with one thing: a `transaction_id` (the `ComputeTransaction.public_id`). By
the end you can state exactly what happened, when, on which GPU, and how the money
moved — with each step corroborated by a log event, a span, a metric, and a durable
`ComputeTxEvent` row.

## The full flow you are reconstructing

The happy path, with the FSM state on the left and the stable `event_name` on the
right:

| # | Step | FSM state | `event_name` |
|---|---|---|---|
| 1 | Buyer opens checkout | `DRAFT` | `http.request.completed` |
| 2 | Quote calculated | `DRAFT` | `quote.calculated` |
| 3 | PaymentIntent created (manual capture) | `DRAFT` → `PAYMENT_REQUIRES_ACTION` | `payment.authorization.requested` |
| 4 | Card authorized (server-verified) | `PAYMENT_AUTHORIZED` | `payment.authorization.confirmed` |
| 5 | GPU selected + reserved | `GPU_RESERVED` | `gpu.reservation.created` |
| 6 | Job queued / dispatched | `DISPATCHING` | `job.dispatched` |
| 7 | Agent receives, container starts, executes | `RUNNING` | `job.execution.started` → `job.execution.completed` |
| 8 | Result uploaded | `RUNNING` | `result.uploaded` |
| 9 | Result validated | `RUNNING` | `result.validation.passed` |
| 10 | Metering finalized (actual usage) | `METERING_FINALIZED` | `settlement.metering.finalized` |
| 11 | Buyer captured | `PAYMENT_CAPTURE_PENDING` → `PAYMENT_CAPTURED` | `settlement.capture.completed` |
| 12 | Commission recorded | `PAYMENT_CAPTURED` | `settlement.commission.recorded` |
| 13 | Seller earning created | `PAYMENT_CAPTURED` | `settlement.seller_earning.created` |
| 14 | Transfer to seller created | `SELLER_TRANSFER_PENDING` → `SELLER_TRANSFERRED` | `seller.transfer.created` |
| 15 | Completed | `COMPLETED` | `transaction.completed` |

Every transition (states) passes through the single `transition()` chokepoint, which
appends a `ComputeTxEvent` row and increments
`petabyte_transaction_transitions_total{to_state,payment_mode,environment}`.

## Step 1 — pull the log timeline from Loki

Loki labels are only `service, environment, log_level, component, host_role, region`.
The `transaction_id` is a JSON **field** in the body, so filter with `| json`:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
```

Widen across every service in the chain to catch settlement, agent, executor, and
validator lines:

```logql
{environment="production"} | json | transaction_id="<TX>"
```

Sort ascending by time and you have the ordered `event_name` stream (steps 1–15
above). This tells you where the flow got to and, on a failure, the last event before
it stopped.

## Step 2 — get the `trace_id` from the logs

Every log line carries the `trace_id` JSON field (refreshed inside each `span`).
Extract it:

```logql
{environment="production"} | json | transaction_id="<TX>" | line_format "{{.trace_id}}"
```

Any non-empty `trace_id` for this transaction works; the whole flow shares the trace
(W3C context is propagated across API → Redis/worker → agent → executor → validator →
settlement).

## Step 3 — open the trace in Tempo

- Grafana → **Explore** → select the **Tempo** data source → **Search by Trace ID** →
  paste the `trace_id`. Or click the Loki→Tempo link on the log line.
- Or open the **Transaction Trace** dashboard and paste the `transaction_id`
  (or `trace_id`); it links straight to the trace.

In Tempo you see the span tree spanning machines: the `http.request` server span, the
reservation and dispatch spans, the agent/executor spans on the seller node, the
validator span, and the settlement spans (capture → commission → seller earning →
transfer). A failure shows as a span with recorded exception + ERROR status, pinpointing
exactly which step and service failed.

## Step 4 — corroborate with metrics (Prometheus)

Metrics don't carry the `transaction_id` (bounded cardinality), but they confirm the
transaction's steps happened within the expected window and weren't anomalous:

- Transition occurred:
  ```promql
  increase(petabyte_transaction_transitions_total{to_state="PAYMENT_CAPTURED",environment="production"}[15m])
  ```
- Capture succeeded and was timely:
  ```promql
  sum(rate(petabyte_payment_captures_total{outcome="success",environment="production"}[15m]))
  histogram_quantile(0.95, sum by (le) (rate(petabyte_payment_capture_duration_seconds_bucket{environment="production"}[15m])))
  ```
- Transfer succeeded:
  ```promql
  sum(rate(petabyte_seller_transfers_total{outcome="success",environment="production"}[15m]))
  ```
- No reconciliation/ledger fallout in the window:
  ```promql
  increase(petabyte_reconciliation_discrepancies_total{environment="production"}[1h])
  increase(petabyte_ledger_imbalance_total{environment="production"}[1h])
  ```

## Step 5 — the authoritative timeline (Postgres)

The durable, append-only record — the one that survives Loki/Tempo retention and is
safe to cite for audit:

```
GET /payments/{transaction_id}/timeline
```

Returns `{transaction_id, status, timeline[], why_failed}`, where each `timeline`
entry is a `ComputeTxEvent`: `{at, from, to, reason, by}`. Buyer, seller, and admins
each see every state change (who, when, why); on a failure, `why_failed` is the plain
reason from the last event that led into the terminal failure state.

Use this as the source of truth. Loki/Tempo explain *how* and *why* in rich detail;
the timeline endpoint and the ledger state *what actually happened* to the money.

## Debugging a stalled or failed transaction

1. Run the Loki query (Step 1); find the **last** `event_name` and its FSM `to_state`.
2. Map the last state to the responsible runbook:
   - stuck before `PAYMENT_AUTHORIZED` → payment/auth or webhook issue
     (`runbooks/STRIPE_WEBHOOK_FAILURE.md`).
   - stuck in `GPU_RESERVED`/`DISPATCHING` → `runbooks/WORKER_QUEUE_BACKLOG.md` /
     `runbooks/SELLER_AGENT_OFFLINE.md`.
   - stuck in `RUNNING` → `runbooks/GPU_JOB_STUCK.md`.
   - `result.validation.failed` → `runbooks/RESULT_VALIDATION_FAILURE.md`.
   - `CAPTURE_FAILED` → `runbooks/PAYMENT_CAPTURE_FAILURE.md`.
   - `TRANSFER_FAILED` → `runbooks/SELLER_TRANSFER_FAILURE.md`.
3. Open the trace (Steps 2–3) to see the failing span and its recorded exception.
4. Confirm the terminal financial state on `/payments/{id}/timeline` and, if money is
   involved, against Stripe. Reconcile via
   `runbooks/LEDGER_RECONCILIATION_FAILURE.md` if metrics show discrepancy/imbalance.
