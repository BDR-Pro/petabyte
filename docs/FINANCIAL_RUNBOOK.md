# Financial Runbook (operators)

Day-to-day and incident operations for the Stripe Connect money flow. All admin
financial actions require authorization + a reason, are audited, idempotent, validate
current state, and never create duplicate money movement.

## Where to look

- `GET /admin/payments` — all compute transactions (filter by status).
- `GET /admin/payments/{id}` — full detail: pricing snapshot, **state-transition
  history**, every `PaymentOperation` (with idempotency key + Stripe object id + error),
  and settlement versions.
- `GET /admin/webhooks` — webhook processing history (state, attempts, errors).
- Internal ledger integrity: `ledger_is_balanced()` (also surfaced on `/metrics`).

## Common operations

| Task | Action |
|---|---|
| A capture is stuck (`CAPTURE_FAILED`) | Re-run `POST /admin/payments/{id}/capture` (idempotent). |
| A transfer failed (`TRANSFER_FAILED`) | Re-run `POST /admin/payments/{id}/transfer`. |
| Buyer cancelled before run | Handled by `/payments/{id}/cancel`; verify GPU released. |
| Refund (full/partial) | `POST /admin/payments/{id}/refund {amount?, reason}`. |
| Refund after transfer | Same call — it also creates the transfer reversal automatically. |
| Reconcile an uncertain Stripe result | Retrieve the object in Stripe; the deterministic idempotency keys mean re-issuing the operation is safe (it returns the same object, never a second money movement). |

## Incident: uncertain network response to a money-moving call

Do **not** blindly retry. Every operation is persisted (`PaymentOperation`) **before**
the Stripe call with a deterministic idempotency key. To resolve:
1. Look up the `PaymentOperation` for the tx + op type.
2. Retrieve the Stripe object by the stored idempotency key (or the recorded external
   id). Stripe returns the original result for a reused idempotency key.
3. If it exists, mark the op succeeded and reconcile; if not, the retry is safe.

## Incident: `reconciliation_status = needs_review`

Set when a refund succeeded but its transfer reversal could not be completed, or on a
dispute. Resolve the seller-side liability manually (reversal when permitted, or a
seller balance adjustment), then mark reconciled. The customer-facing job state is
independent, so a completed job with an open money issue is never shown as settled.

## Incident: seller not receiving money

Distinguish two events:
- **Transfer** (Petabyte → connected account's Stripe balance): check
  `tx.stripe_transfer_id` and the `transfer.*` webhook.
- **Bank payout** (Stripe → seller's bank on their schedule): check `payout.*`
  webhooks (`/admin/webhooks`, or the seller's `payout_events`). A successful transfer
  does **not** mean the bank has been paid.

## Balances & risk

- Insufficient platform balance → transfers fail (`TRANSFER_FAILED`); top up the
  platform balance, then retry.
- Seller negative-balance risk (refund after transfer) → transfer reversal; if the
  connected account lacks balance, Stripe creates a debit — monitor and escalate.
- Never pay a seller for unverified or fraudulent usage; capture is driven only by
  trusted server-side metering.

## Reconciliation job (recommended)

Periodically compare internal `ComputeTransaction` + ledger against Stripe
(PaymentIntents, transfers, refunds) and flag divergences to `needs_review`. This is
scaffolded via the stored idempotency keys + external ids; a scheduled reconciler is
on the roadmap (see [PRODUCTION_PAYMENT_CHECKLIST](PRODUCTION_PAYMENT_CHECKLIST.md)).
