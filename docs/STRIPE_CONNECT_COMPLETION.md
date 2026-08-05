# Stripe Connect — Completion Report

Branch `claude/petabyte-funding-readiness-fun2q6`. Test mode first; no live Stripe
account/keys/egress exist in this environment, so the flow is built against the
official `stripe` SDK behind a gateway seam with a deterministic in-process fake for
tests + demo (per the brief's "test mode first / no live Stripe in unit tests").

## 1. Files changed

**New:** `pricing.py`, `stripe_gateway.py`, `stripe_connect.py`, `stripe_test.py`,
`stripe_demo.py`, `.env.example`; docs `STRIPE_CONNECT_ARCHITECTURE.md`,
`PAYMENT_FLOW.md`, `SELLER_ONBOARDING.md`, `SETTLEMENT_AND_LEDGER.md`,
`REFUNDS_AND_DISPUTES.md`, `STRIPE_WEBHOOKS.md`, `STRIPE_TESTING.md`,
`FINANCIAL_RUNBOOK.md`, `PRODUCTION_PAYMENT_CHECKLIST.md`, this report.
**Modified:** `db.py` (5 new models + ledger accounts), `main.py` (19 endpoints +
webhook + 2 UI routes), `pages.py` (seller payouts page + admin payments panel),
`requirements.txt` (`stripe>=11`), `template.env`, `run_tests.sh`, `Makefile`,
`.github/workflows/tests.yml`.

## 2. Database migrations

Schema is `create_all()` + `_ensure_columns()` (the repo's mechanism; a CI job proves
it builds from a completely empty SQLite **and** Postgres DB). New tables:
`connected_accounts`, `compute_transactions`, `compute_tx_events`,
`payment_operations`, `stripe_webhook_events`, `settlements` (integer-minor-unit money,
FKs, unique constraints, non-negative CHECK constraints).

## 3. End-to-end flow implemented

onboard seller (Express, hosted onboarding, authoritative status sync) → server quote
→ authorize (manual-capture PaymentIntent, transfer_group, immutable-id metadata) →
verify authorization server-side → atomic GPU reservation → idempotent dispatch →
trusted metering → partial capture of actual usage (unused auth released) → commission
→ Transfer net to the connected account (at most once) → COMPLETED; plus refunds,
partial refunds, transfer reversals, cancel, and webhook reconciliation. Every money
movement posts to the existing double-entry ledger.

## 4. State machine

`DRAFT → PAYMENT_REQUIRES_ACTION → PAYMENT_AUTHORIZED → GPU_RESERVED → DISPATCHING →
RUNNING → METERING_FINALIZED → PAYMENT_CAPTURE_PENDING → PAYMENT_CAPTURED →
SELLER_TRANSFER_PENDING → SELLER_TRANSFERRED → COMPLETED`, plus `PAYMENT_FAILED,
AUTHORIZATION_EXPIRED, RESERVATION_FAILED, DISPATCH_FAILED, JOB_FAILED, CAPTURE_FAILED,
TRANSFER_FAILED, CANCELLED, REFUND_PENDING, REFUNDED, DISPUTED`. Transitions validated
in `stripe_connect.transition()`; history is append-only (`ComputeTxEvent`).
Full diagrams: `PAYMENT_FLOW.md`, `STRIPE_CONNECT_ARCHITECTURE.md`.

## 5. Money-flow & fee examples

`captured == platform_fee + seller_net`; Stripe fee borne by the platform, tracked
separately. At $2.50/hr, 10% commission, 20% auth margin, min charge $0.50:

| Metered | Captured | Platform fee | Seller net |
|---|---|---|---|
| 30 min | 125 | 12 | 113 |
| 60 min | 250 | 25 | 225 |
| < min | 50 | 5 | 45 |
| 0 | 0 (cancel, $0) | 0 | 0 |
| 90 min vs 60 min auth | 300 (capped) | 30 | 270 |

## 6. Tests & results

`stripe_test.py` — **54 assertions, offline** (fake gateway; real webhook verifier),
green on **SQLite and PostgreSQL**. Covers: onboarding creation/idempotency/gating,
server quote, browser-amount-ignored, PI-once, auth-before-reserve, reservation race,
idempotent dispatch, partial capture + released auth, duplicate-capture no-op,
transfer-only-after-capture + duplicate-transfer no-op, zero-usage cancel, refund
before/after transfer (+ reversal), partial refund, webhook valid/invalid/stale/
duplicate/unknown + payment_intent-drives-auth, ledger balance + duplicate-external-ref
rejection + compensating entries, admin detail + IDOR. Existing suites (smoke 499,
adversarial 14, tunnel 12, postgres 12, demo 21, frontend contract + JS) remain green.

## 7. Stripe CLI commands (for live test-mode verification)

```
stripe listen --forward-to localhost:8000/webhooks/stripe
stripe trigger payment_intent.amount_capturable_updated
stripe trigger charge.refunded
stripe trigger account.updated
stripe trigger payout.paid
```

## 8. Manual test procedure

See `STRIPE_TESTING.md`. Offline: `make stripe-demo` (narrated flow),
`make stripe-test` (54 assertions). Live-ish: set `STRIPE_GATEWAY=real` + test keys,
`stripe listen`, drive `/payments/*`, use test cards (4242…, 3DS 4000 0025 0000 3155,
decline 4000 0000 0000 9995).

## 9. Security controls

Server-computed amounts only (browser never sets price/auth/fee/net/destination);
manual-capture authorization verified server-side before any execution; atomic
reservation; idempotent dispatch/capture/transfer via `PaymentOperation` (persist
before Stripe) + deterministic keys; at-most-once signature-verified webhooks over the
raw body; per-object authorization + IDOR checks; admin financial actions require a
reason + audit; secrets from env; no card data through Petabyte; `screen()` fails
closed in live mode.

## 10. Known unresolved issues (see PRODUCTION_PAYMENT_CHECKLIST.md)

Live Stripe account/Connect enablement, country/currency support, MoR/tax/dispute
liability review, live-mode Stripe fee capture from balance transactions, negative
balance handling, publicly reachable signed webhook endpoint, a scheduled reconciler
(scaffolded via idempotency keys + external ids, periodic job not built), KYC/AML
provider, and accountant/legal review. The buyer card-entry front-end (Stripe Elements)
is not wired (needs live keys + js.stripe.com); the buyer API flow is complete and the
`client_secret` is returned for an Elements/Checkout integration.

## 11. Production-readiness

Not production-ready until the checklist in `PRODUCTION_PAYMENT_CHECKLIST.md` is
verified. The software money spine (authorization, capture, transfer, refund, reversal,
ledger, webhooks, idempotency) is implemented and tested; the unresolved items are
Stripe-account-, operational-, and compliance-dependent and are documented, not
bypassed.

## 12. Five-minute demo script

`make stripe-demo` proves, in order and with printed amounts: a seller onboards for
payouts; a GPU becomes available; a buyer selects it; **payment is authorized before
execution**; the job is **dispatched once** (retry keeps the same task); actual usage
is metered; **only actual usage is captured** (unused hold released); commission is
computed; the **seller net is transferred once** (retry creates no second transfer);
buyer/seller/admin records agree; and the ledger balances. Refund/dispute/duplicate-
webhook paths are proven in `stripe_test.py`.
