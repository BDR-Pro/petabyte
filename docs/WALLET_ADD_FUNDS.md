# Wallet "Add funds" via Stripe Checkout

Clicking **Add funds** opens Stripe's hosted card page (Stripe Checkout) for a wallet
top-up. We never handle card data — the buyer enters it on Stripe. The wallet balance is
credited when the payment completes.

## Flow

```
buyer clicks Add funds (amount)
  → POST /wallet/topup {amount_minor}          # creates a Stripe Checkout Session
  → redirect to session.url (Stripe hosted card page)
  → buyer pays with a card
  → Stripe → POST /webhooks/stripe  checkout.session.completed
  → wallet credited (idempotent)               # balance += amount
```

- Endpoint: `POST /wallet/topup {amount_minor}` → `{checkout_url, session_id, topup_id,
  mode, test_mode, publishable_key}`. The UI redirects to `checkout_url`.
- Status: `GET /wallet/topup/{topup_id}`.
- Each top-up is a `WalletTopup` row (pending → paid), stamped with the money mode; the
  wallet is credited exactly once (`db.mark_topup_paid_and_credit`, idempotent on
  duplicate webhooks/retries).

## Demo (TEST) vs LIVE mode

The configured Stripe **gateway + keys** decide which environment the checkout runs in;
the top-up is stamped with `payments_mode()` (`TEST` unless `PAYMENTS_LIVE_ENABLED=true`).
`assert_test_mode` refuses live keys unless the operator explicitly opts in.

- **Demo / TEST**: `STRIPE_GATEWAY=real` + `sk_test_/pk_test_` keys → Stripe **test mode**;
  use test cards (`4242 4242 4242 4242`). `test_mode: true` in the response — the UI shows
  a "Test mode" note. No real money moves. Demo top-ups are stamped `TEST` and can never be
  counted as live funds (immutable `mode`).
- **LIVE**: `PAYMENTS_LIVE_ENABLED=true` + `STRIPE_ALLOW_LIVE=true` +
  `ENVIRONMENT=production` + `sk_live_/pk_live_` keys → real cards, real charges.
- **Offline (fake gateway, `STRIPE_GATEWAY=fake`)**: no network. `checkout_url` is a
  placeholder; complete a top-up with `POST /wallet/topup/{id}/simulate-pay` (TEST-only,
  404 in real mode) — used by the offline demo + CI.

## Operator setup (required for real checkout)

1. `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` (test or live) and
   `STRIPE_GATEWAY=real`.
2. `STRIPE_WEBHOOK_SECRET` for `POST /webhooks/stripe`, and enable the
   **`checkout.session.completed`** event on that Stripe webhook (that's what credits the
   wallet). `payment_intent.*` and `account.updated` are already used for the marketplace
   flow.
3. `PUBLIC_BASE_URL` so the success/cancel URLs (`/account?funded=1|0`) are correct.
4. Bounds: `WALLET_MIN_TOPUP_MINOR` (default 500 = $5), `WALLET_MAX_TOPUP_MINOR`
   (default 500000 = $5,000).

## Tests

`wallet_test.py` (offline, fake gateway): start returns a checkout URL + TEST mode,
amount bounds enforced, simulate-pay credits exactly once (idempotent), the
`checkout.session.completed` webhook credits, a duplicate webhook does not double-credit,
and an unpaid session credits nothing. Wired into `run_tests.sh` + CI.
