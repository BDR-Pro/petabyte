# Runbook: Seller Transfer Failure

Transferring the seller's net earning to their Stripe Connect connected account is
failing. Transactions land in `TRANSFER_FAILED` instead of `SELLER_TRANSFERRED`.
The buyer has already been captured; this is the payout leg.

## Symptoms

- `event_name="seller.transfer.failed"` in logs.
- `petabyte_seller_transfers_total{outcome="failure"}` incrementing.
- Transactions stuck in `SELLER_TRANSFER_PENDING` or bouncing to `TRANSFER_FAILED`.
- Sellers report missing/late payouts.
- Grafana alert `SellerTransferFailures` firing.

## Impact

- Sellers not paid for delivered, captured work → trust and retention risk.
- Platform holds funds it owes the seller (a `seller_payable` obligation) — must be
  resolved, not dropped.

## Dashboard

**Stripe & Settlement** (primary) and **Seller-Agent Fleet** (which sellers are
affected).

## Loki query

```logql
{service="petabyte-settlement"} | json | event_name="seller.transfer.failed"
```

Drill into one transaction / seller:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
{environment="production"} | json | seller_id="<SELLER_ID>"
{environment="production"} | json | transfer_id="<tr_...>"
```

## Metrics to inspect

- Transfer success ratio:
  ```promql
  sum(rate(petabyte_seller_transfers_total{outcome="success",environment="production"}[15m]))
  /
  sum(rate(petabyte_seller_transfers_total{environment="production"}[15m]))
  ```
- Failures by mode:
  ```promql
  sum by (payment_mode) (increase(petabyte_seller_transfers_total{outcome="failure",environment="production"}[1h]))
  ```
- Cross-check that captures are healthy (transfers depend on captured funds):
  ```promql
  sum(rate(petabyte_payment_captures_total{outcome="success",environment="production"}[15m]))
  ```

## Trace to inspect

1. Get the failing `transaction_id` and `transfer_id`/`seller_id` from Loki.
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. The transfer span carries the Stripe error: connected-account not payouts-enabled,
   restricted/blocked account, capability missing, or a transient API error.

## Safe first actions

1. Classify:
   - **Account-side** (connected account not enabled for transfers/payouts, missing
     capabilities, verification pending, blocked): the seller must complete Connect
     onboarding — see `SELLER_ONBOARDING`. Do not retry until fixed; the earning stays
     as a payable obligation and pays out once the account is eligible.
   - **Transient / Stripe API**: safe to retry. Transfers are guarded by a
     persist-before-call `PaymentOperation` with a deterministic idempotency key
     (`petabyte:transfer:<public_id>:<version>`) — retrying **cannot** double-pay.
     `TRANSFER_FAILED → SELLER_TRANSFER_PENDING` is the legitimate retry edge.
2. Confirm the buyer capture actually succeeded (transfer must only follow capture).
3. Respect the payout hold / cooling-off (`PAYOUT_COOLING_OFF_H`, `PAYOUT_HOLD_DAYS`)
   — a "failure" may actually be a held-not-yet-due earning; check before forcing.
4. Let the settlement retry loop drain `TRANSFER_FAILED` after the account/root cause
   is resolved.

## Escalation criteria

- Many sellers failing at once (points at platform config: Stripe key/mode, Connect
  platform settings) → page settlement owner.
- A seller owed funds with no viable payout path within SLA.
- Any sign of double-transfer or ledger divergence → `LEDGER_RECONCILIATION_FAILURE.md`.

## Recovery verification

- `petabyte_seller_transfers_total{outcome="success"}` resumes.
- Previously `TRANSFER_FAILED` transactions retried to `SELLER_TRANSFERRED → COMPLETED`.
- `/payments/{id}/timeline` shows `PAYMENT_CAPTURED → SELLER_TRANSFER_PENDING →
  SELLER_TRANSFERRED → COMPLETED`.
- `seller_payable` obligations for affected sellers clear; ledger balanced
  (`petabyte_ledger_imbalance_total` flat).

## Financial-safety considerations

- Transfer happens **only after capture** and **at most once** — the ordering and the
  idempotency key are the guardrails against paying a seller twice or paying for an
  uncaptured job.
- The seller nets `gross − platform_fee`; the amount comes from the settlement
  computation (`pricing.py`), never a client value. `settlement.commission.recorded`
  and `settlement.seller_earning.created` should have preceded the transfer.
- A failed transfer never means the seller loses the money — it becomes a durable
  `seller_payable` obligation in Postgres that must eventually pay out. Never clear it
  by hand-editing state; drive it through the FSM / retry path.
- Every transfer posts to the double-entry ledger; if Stripe shows a transfer that the
  ledger doesn't, reconcile — do not re-issue.
