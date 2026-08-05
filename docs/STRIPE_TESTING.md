# Stripe Testing (test mode)

Everything below uses Stripe **test mode**. Never commit real credentials.

## Environment (`lumaris_api/template.env` → copy to your `.env`)

```
STRIPE_GATEWAY=fake            # 'fake' = in-process (tests/demo); 'real' = live SDK
STRIPE_SECRET_KEY=sk_test_...  # from the Stripe dashboard (test mode)
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...   # from `stripe listen`
PLATFORM_DEFAULT_COUNTRY=US
PLATFORM_CURRENCY=usd
PLATFORM_COMMISSION_BPS=1000    # 10.00% (defaults to PLATFORM_TAKE_RATE)
PLATFORM_MIN_CHARGE_MINOR=50
PLATFORM_AUTH_MARGIN_BPS=2000
PUBLIC_BASE_URL=http://localhost:8000
```

`.env.example` at the repo `lumaris_api/` root lists the same keys.

## Run the tests (no network needed)

```
cd lumaris_api
python stripe_test.py                 # 54 offline assertions (fake gateway)
bash run_tests.sh --postgres          # full suite incl. stripe on SQLite + Postgres
```

`stripe_test.py` uses `FakeStripeGateway` (deterministic, in-process) but verifies
webhook signatures with the **real** Stripe verifier. CI runs it on both engines.

## Live-ish test mode with the Stripe CLI

```
# 1. real test keys
export STRIPE_GATEWAY=real STRIPE_SECRET_KEY=sk_test_... STRIPE_PUBLISHABLE_KEY=pk_test_...
# 2. forward webhooks and capture the signing secret
stripe listen --forward-to localhost:8000/webhooks/stripe
export STRIPE_WEBHOOK_SECRET=whsec_...   # printed by `stripe listen`
# 3. run the API
uvicorn main:app --reload
```

### Test cards (Stripe test mode)

| Card | Behavior |
|---|---|
| 4242 4242 4242 4242 | succeeds |
| 4000 0025 0000 3155 | requires 3DS authentication |
| 4000 0000 0000 9995 | declined (insufficient funds) |

Any future expiry, any CVC, any ZIP.

### Test seller onboarding

Create a connected account (`POST /payments/connect/account`), open the onboarding
link, and use Stripe's test onboarding values (e.g. SSN `000-00-0000`, test bank
routing `110000000` / account `000123456789`). Then `POST /payments/connect/refresh`
or wait for `account.updated`.

### Trigger events

```
stripe trigger payment_intent.amount_capturable_updated
stripe trigger charge.refunded
stripe trigger account.updated
stripe trigger payout.paid
```

## Deterministic offline demo

```
make stripe-demo        # seeds an onboarded test seller, GPU, buyer, and runs the
                        # full authorize -> reserve -> dispatch -> meter -> capture ->
                        # transfer flow against the FAKE gateway, printing every amount.
```

The demo uses genuine Stripe test-mode object shapes via the fake gateway and clearly
labels the simulated GPU execution. See [FINANCIAL_RUNBOOK](FINANCIAL_RUNBOOK.md) for
admin operations and [PRODUCTION_PAYMENT_CHECKLIST](PRODUCTION_PAYMENT_CHECKLIST.md)
before going live.

## Commands to run migrations and tests

```
cd lumaris_api
python -c "import db; db.init_db()"   # build schema (create_all + _ensure_columns)
bash run_tests.sh --postgres          # full suite
```
