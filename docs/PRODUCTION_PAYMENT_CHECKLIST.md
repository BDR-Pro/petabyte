# Production Payment Checklist

The Stripe Connect integration is **not** production-ready until every item below is
verified. Items are marked ✅ done in this repo / ⚠️ requires a real Stripe account or
external verification. Do not bypass unresolved items — document them.

## Implemented and tested (this repo, test mode)
- ✅ Separate charges & transfers with manual-capture PaymentIntents.
- ✅ Server-side pricing in integer minor units + immutable per-tx snapshot.
- ✅ Validated state machine with append-only history; separate reconciliation state.
- ✅ Atomic GPU reservation tied to verified authorization; idempotent dispatch.
- ✅ Partial capture of actual metered usage; unused authorization released.
- ✅ Commission accounting; seller Transfer at most once (idempotency + guards).
- ✅ Refunds, partial refunds, and transfer reversals with compensating ledger entries.
- ✅ Double-entry ledger, balanced, no float money, unique external references.
- ✅ Signed webhooks over the raw body, at-most-once, real Stripe verifier.
- ✅ Persist-before-Stripe idempotency ledger (`PaymentOperation`).
- ✅ Server-computed amounts only; client never sets price/fee/destination.
- ✅ 54 offline tests on SQLite **and** PostgreSQL; schema builds from a clean DB.
- ✅ Secrets from env; startup gate refuses production with stubs on.

## Requires a real Stripe account / external verification (⚠️ unresolved here)
- ⚠️ Petabyte's Stripe account has **Connect enabled** and the chosen connected-account
  model (Express controller config) is approved for the platform.
- ⚠️ Seller **countries** are supported by Connect + `transfers`; buyer **currencies**
  and payment methods are supported.
- ⚠️ Merchant-of-record implications understood (platform is MoR in this config).
- ⚠️ Terms of service, refund policy, and seller agreement exist.
- ⚠️ Tax responsibilities reviewed (tax fields are reserved in the snapshot, not computed).
- ⚠️ Stripe **processing fees** and Connect fees understood; `stripe_fee_amount` is
  tracked separately but is only populated from `balance_transaction`/webhook data in
  live mode (0 in the fake gateway).
- ⚠️ **Dispute liability** documented (platform bears the charge in this model).
- ⚠️ **Negative-balance** handling for refund-after-transfer on low-balance connected
  accounts documented and monitored.
- ⚠️ Webhook endpoint publicly reachable + the Connect event destination configured.
- ⚠️ Live keys in a secrets manager (never in the repo); `STRIPE_GATEWAY=real`.
- ⚠️ Monitoring/alerting on failed captures/transfers/payouts and `needs_review`.
- ⚠️ A scheduled **reconciler** comparing internal records to Stripe objects
  (scaffolded via idempotency keys + external ids; the periodic job is not yet built).
- ⚠️ A real accountant / payments specialist has reviewed the ledger model.
- ⚠️ Legal counsel has reviewed the marketplace money flow.

## Also not yet wired for live money (cross-refs)
- ⚠️ KYC + sanctions/AML screening before payouts (`payout_providers.screen()` fails
  closed in live mode until a provider is configured).
- ⚠️ The internal-wallet sandbox path (`/deposit`) must be disabled in production
  (`PAYMENTS_MODE=live` already 403s direct deposit).

## Go-live switch
1. Set `STRIPE_GATEWAY=real`, real `sk_live_…` / `pk_live_…`, real `whsec_…` from a
   production webhook endpoint.
2. Confirm Connect + capabilities on the platform account.
3. Run the reconciler and confirm zero divergence on a canary transaction.
4. Only then enable paid supply for real sellers.
