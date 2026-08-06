# Runbook: Ledger Reconciliation Failure

The reconciliation job found a discrepancy between the internal double-entry ledger /
transaction state and Stripe, or the ledger itself does not balance. This is the
highest-severity financial-correctness runbook.

## Symptoms

- `petabyte_reconciliation_discrepancies_total` incrementing.
- `petabyte_ledger_imbalance_total` incrementing (debits ≠ credits somewhere).
- A transaction whose Stripe object state disagrees with its FSM state / ledger.
- Grafana alert `LedgerImbalance` (critical) / `ReconciliationDiscrepancy` firing.

## Impact

- Potential real financial error: over/under-capture, missing or double transfer,
  unposted ledger entry, or a captured charge with no seller obligation. Even a single
  imbalance is treated as a **P1 financial incident**.

## Dashboard

**Stripe & Settlement** (reconciliation + ledger panels) and **Transaction Trace**
(per-transaction forensics).

## Loki query

```logql
{environment="production"} | json | event_name=~"settlement\\.(capture|commission|seller_earning|refund)\\.|seller.transfer\\."
```

For the flagged transaction:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
{environment="production"} | json | payment_intent_id="<pi_...>"
{environment="production"} | json | charge_id="<ch_...>"
{environment="production"} | json | transfer_id="<tr_...>"
```

## Metrics to inspect

- Imbalance (should be **flat at zero** always):
  ```promql
  increase(petabyte_ledger_imbalance_total{environment="production"}[6h])
  ```
- Discrepancies:
  ```promql
  increase(petabyte_reconciliation_discrepancies_total{environment="production"}[6h])
  ```
- Cross-check the money legs for the window:
  ```promql
  sum by (outcome) (increase(petabyte_payment_captures_total{environment="production"}[6h]))
  sum by (outcome) (increase(petabyte_seller_transfers_total{environment="production"}[6h]))
  increase(petabyte_refunds_total{environment="production"}[6h])
  ```

## Trace to inspect

1. Take the flagged `transaction_id` and its Stripe object ids from Loki.
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. Reconstruct the money legs from the spans/events:
   `settlement.metering.finalized` → `settlement.capture.completed` →
   `settlement.commission.recorded` → `settlement.seller_earning.created` →
   `seller.transfer.created`. Find the missing or duplicated leg.

## Safe first actions

1. **Freeze judgement on the number, not the truth.** Postgres + Stripe are the
   authoritative records; Loki/Tempo are diagnostic only. Reconcile the transaction
   against Stripe (Dashboard / API) as the external source of truth.
2. Identify the discrepancy class:
   - Ledger posting missing for a real Stripe event (unposted `db.post()`).
   - Stripe event with no corresponding FSM transition (missed webhook — see
     `STRIPE_WEBHOOK_FAILURE.md`).
   - Amount mismatch (capture ≠ metered/pricing-snapshot amount).
   - Duplicate money movement (should be impossible given idempotency keys — if real,
     it's a critical bug).
3. Pull the append-only `ComputeTxEvent` history via `/payments/{id}/timeline` and
   compare to the ledger and to Stripe.
4. **Do not** issue manual captures/transfers/refunds to "balance" it until root cause
   is understood — a wrong correction compounds the error.

## Escalation criteria

- **Any** `petabyte_ledger_imbalance_total` increment → immediate P1, page settlement
  owner + platform lead.
- Suspected double-capture or double-transfer.
- Discrepancy involving real money (`payment_mode="live"`,
  `PAYMENTS_LIVE_ENABLED=true`).

## Recovery verification

- Root cause identified and the specific transaction reconciled: ledger legs match
  Stripe and the FSM terminal state is correct.
- `petabyte_ledger_imbalance_total` and `petabyte_reconciliation_discrepancies_total`
  return to flat/zero and stay there across the next reconciliation cycles.
- A written incident record captures what diverged, why, and the correction.

## Financial-safety considerations

- The double-entry ledger (`db.post()` with `DEBIT`/`CREDIT`) must always balance;
  every money movement — capture, commission, seller earning, transfer, refund — posts
  to it. An imbalance means either an unposted leg or a bug, never "just a metric
  glitch."
- Postgres is the durable, permanent financial record. **Never** reconstruct or
  "correct" the ledger from Loki or Tempo — those are short-retention and lossy by
  design.
- Corrections go through the FSM and the ledger, with idempotency preserved. Manual
  Stripe actions outside the persist-before-call path can create the very duplicates
  this system is built to prevent.
