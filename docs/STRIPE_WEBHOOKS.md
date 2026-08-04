# Stripe Webhooks

Stripe is the **authoritative** async source of truth. A browser redirect never marks
anything paid — only a verified webhook (or an explicit server-side retrieve) does.

## Endpoint: `POST /webhooks/stripe`

1. Read the **raw** request body (never the parsed JSON) for signature verification.
2. Verify `Stripe-Signature` against `STRIPE_WEBHOOK_SECRET` using the official
   `stripe.Webhook.construct_event` (retains Stripe's timestamp-tolerance protection).
3. Reject invalid signatures with 400.
4. Store the event (`StripeWebhookEvent`) and process it **at most once**; an
   already-processed event returns 200 immediately (idempotent).
5. Handler failure returns 500 so Stripe retries; success returns 200.
6. Never log secrets or full payment details.

Event order is not assumed; handlers fetch/reconcile against current state and are
safe under duplicate and out-of-order delivery.

## Handled events

| Event | Effect |
|---|---|
| `account.updated` | Sync connected-account capabilities/requirements; flip payout-ready. |
| `payment_intent.amount_capturable_updated`, `payment_intent.succeeded` | If `requires_capture`, mark the tx `PAYMENT_AUTHORIZED` (authoritative authorization). |
| `payment_intent.payment_failed` | `PAYMENT_FAILED`. |
| `payment_intent.canceled` | `CANCELLED`. |
| `charge.refunded` | Reconcile `refunded_amount`. |
| `charge.dispute.created/updated/closed` | `DISPUTED` + `needs_review`. |
| `transfer.*` | Recorded (transfer to connected account). |
| `payout.created/updated/paid/failed` | Recorded (connected-account **bank** payout — distinct from a transfer). |

Unknown event types are acknowledged (200) and recorded for the admin webhook-history
view, so Stripe stops retrying while nothing changes state.

## Reconciliation

```mermaid
sequenceDiagram
    participant S as Stripe
    participant P as Petabyte
    S-->>P: event (id, type, signature)
    P->>P: verify signature over RAW body (400 if bad)
    P->>P: StripeWebhookEvent seen & processed? -> 200 duplicate
    P->>P: store event (received)
    alt handled type
        P->>P: find tx by PI/charge/account; fetch latest if needed; update state + ledger
    else unknown
        P->>P: record only, no state change
    end
    P->>P: mark processed (or failed -> 500 so Stripe retries)
    P-->>S: 200
```

## Two webhook surfaces

- **Platform events** (PaymentIntent, charge, transfer, dispute) → `/webhooks/stripe`.
- **Connected-account events** (`account.updated`, `payout.*`) are delivered with an
  `account` context; the same endpoint handles them and records the account context on
  the stored event. In production, configure the Connect event destination to point at
  this endpoint (or a dedicated one) per the Stripe dashboard.

## Local testing

```
stripe listen --forward-to localhost:8000/webhooks/stripe
# copy the printed whsec_… into STRIPE_WEBHOOK_SECRET
stripe trigger payment_intent.amount_capturable_updated
stripe trigger account.updated
```

The offline test suite (`stripe_test.py`) builds signed events with the real verifier,
so signature/idempotency/handler logic is exercised without any network.
