# Runbook: Stripe Webhook Failure

Stripe webhooks are the **authoritative async source of truth** for payment state
(a browser redirect never marks anything paid). Webhooks failing signature
verification, erroring during processing, or not arriving puts settlement out of sync
with Stripe.

## Symptoms

- `event_name="webhook.processing.failed"` or `webhook.received` with no matching
  `webhook.verified`.
- `petabyte_webhook_invalid_signature_total` incrementing.
- Rising `petabyte_webhooks_total{outcome="failure"}`.
- Stripe Dashboard shows webhook delivery retries / failures to
  `petabyte-stripe-webhook`.
- Grafana alert `WebhookFailures` / `WebhookInvalidSignature` firing.

## Impact

- Transactions may not advance (e.g. auth confirmation, capture confirmation) because
  the confirming webhook wasn't processed.
- If invalid-signature spikes: either a misconfigured signing secret (benign but
  blocking) or a spoofing attempt (security event).

## Dashboard

**Stripe & Settlement** (primary) and **Transaction Trace** (per-transaction).

## Loki query

```logql
{service="petabyte-stripe-webhook"} | json | event_name=~"webhook.(received|verified|processing.failed|duplicate)"
```

Correlate a webhook to its transaction:

```logql
{service="petabyte-api"} | json | transaction_id="<TX>"
{environment="production"} | json | webhook_event_id="<evt_...>"
```

## Metrics to inspect

- Invalid signatures (config error or attack):
  ```promql
  increase(petabyte_webhook_invalid_signature_total{environment="production"}[15m])
  ```
- Processing outcomes by category:
  ```promql
  sum by (category,outcome) (increase(petabyte_webhooks_total{environment="production"}[1h]))
  ```
- Duplicate deliveries (should be absorbed idempotently, not double-applied):
  ```promql
  increase(petabyte_webhook_duplicate_total{environment="production"}[1h])
  ```

## Trace to inspect

1. From Loki, get the `transaction_id` (and `payment_intent_id`/`charge_id`) tied to a
   failed webhook.
2. Read the `trace_id`; open in **Tempo** or the **Transaction Trace** dashboard.
3. The webhook span shows verification and the processing outcome. Compare against the
   transaction FSM: did the expected transition (e.g. → `PAYMENT_AUTHORIZED`,
   → `PAYMENT_CAPTURED`) happen?

## Safe first actions

1. **Invalid signature**: verify `STRIPE_WEBHOOK_SECRET` (and
   `PAYMENT_WEBHOOK_SECRET` for deposits) matches the Stripe Dashboard signing secret
   for this endpoint. A rotated/mismatched secret is the usual cause. If the source IPs
   aren't Stripe, treat as a security event.
2. **Processing failure**: read the failure reason. If it's a transient dependency
   (DB down), fix that first — Stripe **retries** failed deliveries, so a healthy
   endpoint will catch up automatically.
3. Confirm the endpoint is reachable (TLS valid, not 5xx). Use Stripe Dashboard →
   Webhooks → "Resend" or let Stripe's automatic retries redeliver.
4. Reconcile: for any transaction whose Stripe object advanced but whose FSM did not,
   the reconciliation job should detect the gap
   (`petabyte_reconciliation_discrepancies_total`).

## Escalation criteria

- Invalid-signature spike from non-Stripe sources → security incident.
- Webhooks failing > 15 min with settlement falling behind.
- Reconciliation shows Stripe and the ledger diverging → `LEDGER_RECONCILIATION_FAILURE.md`.

## Recovery verification

- `webhook.received` → `webhook.verified` pairs resume;
  `petabyte_webhooks_total{outcome="success"}` recovers.
- `petabyte_webhook_invalid_signature_total` flat.
- Previously-stuck transactions advance to their correct states once retries land.
- `petabyte_reconciliation_discrepancies_total` returns to zero.

## Financial-safety considerations

- Webhooks are authoritative; a **redirect never marks paid**. Do not manually mark a
  transaction paid/captured to compensate for a missed webhook — replay the webhook
  and let the idempotent handler apply it.
- `StripeWebhookEvent` de-duplicates: a duplicate delivery (`webhook.duplicate`) must
  **not** re-apply money movement. If you see duplicates being double-counted, stop and
  escalate — that's a correctness bug.
- Signature verification is mandatory; never disable it or accept unverified events to
  "get unblocked."
