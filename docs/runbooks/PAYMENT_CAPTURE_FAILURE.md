# Runbook: Payment Capture Failure

Capturing the buyer's authorized PaymentIntent (for metered actual usage) is failing.
Transactions are landing in `CAPTURE_FAILED` instead of `PAYMENT_CAPTURED`.

## Symptoms

- `event_name="settlement.capture.failed"` in logs.
- `petabyte_payment_captures_total{outcome="failure"}` incrementing.
- Transactions stuck in `PAYMENT_CAPTURE_PENDING` or bouncing to `CAPTURE_FAILED`.
- Rising `petabyte_payment_capture_duration_seconds` (Stripe latency) preceding
  failures.
- Grafana alert `PaymentCaptureFailures` firing.

## Impact

- Metered, delivered jobs are not being billed → revenue at risk and seller payout
  (which follows capture) is blocked.
- Buyer authorizations may expire if capture keeps failing past the auth window
  (`AUTHORIZATION_EXPIRED`) — then the charge is lost entirely.

## Dashboard

**Stripe & Settlement** (primary) and **Transaction Trace** (per-transaction).

## Loki query

```logql
{service="petabyte-settlement"} | json | event_name="settlement.capture.failed"
```

Drill into one transaction:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
{environment="production"} | json | payment_intent_id="<pi_...>"
```

## Metrics to inspect

- Capture success ratio:
  ```promql
  sum(rate(petabyte_payment_captures_total{outcome="success",environment="production"}[15m]))
  /
  sum(rate(petabyte_payment_captures_total{environment="production"}[15m]))
  ```
- Failures by mode (isolate `test` vs `live`):
  ```promql
  sum by (payment_mode) (increase(petabyte_payment_captures_total{outcome="failure",environment="production"}[1h]))
  ```
- Capture latency:
  ```promql
  histogram_quantile(0.95, sum by (le) (rate(petabyte_payment_capture_duration_seconds_bucket{environment="production"}[15m])))
  ```
- Watch approaching expiries:
  ```promql
  increase(petabyte_transaction_transitions_total{to_state="AUTHORIZATION_EXPIRED",environment="production"}[1h])
  ```

## Trace to inspect

1. Get the failing `transaction_id` and its `payment_intent_id` from Loki.
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. The capture span (under settlement) carries the Stripe error (card declined,
   expired auth, API error, insufficient funds on the auth). Distinguish
   Stripe-declined (buyer-side, terminal) from platform/transient (retryable).

## Safe first actions

1. Classify the Stripe failure:
   - **Transient / Stripe API error / timeout**: safe to retry. The capture is guarded
     by a persist-before-call `PaymentOperation` with a deterministic idempotency key
     (`petabyte:capture:<public_id>:<version>`), so retrying **cannot** double-capture.
     `CAPTURE_FAILED → PAYMENT_CAPTURE_PENDING` is a legitimate retry edge.
   - **Authorization expired**: the auth is gone; capture is impossible. Move to the
     refund/cancel path — do not attempt to re-charge.
   - **Card declined**: buyer-side; follow product policy (may end in refund/no-capture
     and a failed job settlement).
2. If failures are broad (not one card), suspect a platform issue: Stripe key/mode
   mismatch, `PAYMENTS_LIVE_ENABLED`/`STRIPE_MODE` misconfig, or Stripe incident.
   Check `STRIPE_MODE` matches key prefixes and the Stripe status page.
3. Let the settlement retry loop drain `CAPTURE_FAILED` once the root cause is fixed.

## Escalation criteria

- Broad capture failures (platform-wide, not per-card) → page settlement owner.
- Authorizations expiring in volume due to capture delay → urgent (lost revenue).
- Any sign of double-capture or ledger divergence → `LEDGER_RECONCILIATION_FAILURE.md`,
  treat as a financial incident.

## Recovery verification

- `petabyte_payment_captures_total{outcome="success"}` resumes; failure rate back to
  baseline.
- Previously `CAPTURE_FAILED` transactions retried to `PAYMENT_CAPTURED`, then flow on
  to `SELLER_TRANSFER_PENDING`.
- `/payments/{id}/timeline` shows a clean `... → METERING_FINALIZED →
  PAYMENT_CAPTURE_PENDING → PAYMENT_CAPTURED`.
- `petabyte_reconciliation_discrepancies_total` / `petabyte_ledger_imbalance_total`
  stay at zero.

## Financial-safety considerations

- Capture amount derives from the **immutable pricing snapshot** and **metered actual
  usage**, never a client-supplied amount.
- Idempotency is enforced at the DB via `PaymentOperation`; retries after a crash or
  duplicate webhook cannot capture twice. Never bypass this by calling Stripe directly.
- The seller is transferred **only after** a successful capture and at most once —
  keep the ordering; never pre-pay a seller for an uncaptured job.
- Every capture posts to the double-entry ledger (`db.post()`); if a capture succeeded
  at Stripe but the ledger posting is missing, reconcile — do not "fix" by re-capturing.
