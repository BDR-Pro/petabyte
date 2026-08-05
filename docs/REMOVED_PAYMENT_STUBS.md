# Payment Stubs & Fake Money-Movement — Inventory and Removal Tracker

**Purpose:** the authoritative, auditable record of every code path that simulates money
movement without Stripe, and the plan to remove it so that **Stripe (test mode now, live
later) is the single payment architecture for both the app and the demo**.

**Status of this document:** removal is a **phased migration**, because the fake-money
system is load-bearing — the real product runs on it. This file tracks each item from
`IDENTIFIED` → `REMOVED`. It is honest about what has and has not been done. Nothing is
marked `REMOVED` until the code is gone, its replacement is in place, and tests prove it.

**Audit date:** 2026-08-05. **Source of truth for the inventory:** repo-wide audit
(see the sibling roadmap `PAYMENTS_AND_PAYOUTS_ROADMAP.md`).

---

## The core finding (read this first)

**The real product is 100% internal wallet + escrow. The Stripe Connect flow is fully
built but PARALLEL and UNWIRED.**

- `/launch` → `request_vm` → `try_debit(wallet)` + `book_with_escrow` → `create_task` →
  VM. **No Stripe object is created or verified on this path.**
- In the shipped default (`PAYMENTS_MODE=sandbox`, `STRIPE_GATEWAY=fake`), a buyer calls
  `/deposit` to mint free wallet credit, then `/launch` spends it and dispatches a job —
  **a job runs with no card, no PaymentIntent, no authorization.**
- The Stripe Connect service (`stripe_connect.py`), the ledger, obligations, and routing
  are correct and tested, but **no product endpoint calls them**.

**Therefore "remove the fake payment system" means: rewire `/launch` (and the rest of the
product) onto the already-built Stripe Connect chain, migrate tests + demo to it, then
delete the wallet/escrow/legacy-payout surface.** This cannot be a single delete without
breaking the entire app and ~100 test assertions; it is sequenced in the Migration Plan
below.

---

## What is being KEPT (legitimate — not stubs)

These are real infrastructure and must **not** be removed:

| Component | Where | Why it stays |
|---|---|---|
| Double-entry ledger | `db.py` `post`/`account_balance`/`ledger_is_balanced` | Real accounting; it will record Stripe flows instead of fake deposits. |
| Stripe Connect service | `stripe_connect.py` | The real authorize→capture→transfer state machine (the replacement). |
| Real gateway + test-mode guard | `stripe_gateway.py` `RealStripeGateway`, `assert_test_mode` | The real SDK path; hard-fails on live keys. |
| Obligations / rails / routing | `db.py`, `payout_rails.py`, `payout_routing.py`, `payout_capabilities.py` | Provider-neutral payout layer (Connect-first). |
| Production boot gate | `main.py` `_assert_production_is_safe` | Refuses to start prod with any stub enabled. |
| `FakeStripeGateway` | `stripe_gateway.py` | A **network-boundary test double** for unit tests only — explicitly allowed. Must never be the app/demo gateway. |
| Unimplemented rails | `payout_rails.py` Global Payouts / stablecoin / Circle | Honest `NOT_IMPLEMENTED` stubs that *refuse* to move money — not fake success. |
| `reconcile.py` | — | Internal-vs-Stripe reconciliation. |

---

## Inventory of FAKE / SIMULATED / BYPASS code (to remove or rewire)

Legend — **Status:** `IDENTIFIED` (found, not yet removed) · `REMOVED` (gone + replaced +
tested). **Class:** FAKE-MONEY / DEV-BYPASS / STUB-PROVIDER / DEMO-DATA.

### Group 1 — Internal wallet / escrow (the live product money path) — FAKE-MONEY

| # | File:line — symbol | Previous behavior | Why unsafe / misleading | Replacement | Status |
|---|---|---|---|---|---|
| 1.1 | `main.py:3032` `deposit_funds` (`/deposit`, alias `/wallet/deposits:4407`) | Credits arbitrary wallet balance with no payment (`PAYMENTS_MODE=sandbox`). | Mints free money; the product's "funding" step never touches Stripe. | Buyer funds a job via a Stripe test-mode PaymentIntent (Elements/Checkout); no standalone deposit. | IDENTIFIED |
| 1.2 | `db.py:2029` `deposit()` | `user.balance += amount`; ledgers `external:payments → buyer`. | Records inflow for money that never arrived. | Ledger inflow posted only from a captured Stripe charge. | IDENTIFIED |
| 1.3 | `main.py:3002` `/orgs/{id}/deposit` → `db.py:2311` `org_deposit` | Same free-mint for org wallets. | Same as 1.1 for orgs. | Org pays via Stripe (or invoiced), not free credit. | IDENTIFIED |
| 1.4 | `db.py:2044` `try_debit` / `db.py:2324` `try_org_debit` | Wallet balance IS the payment method for a rental (`request_vm`). | Spending fake credit = paying with fake money. | Payment = Stripe authorize+capture on the ComputeTransaction. | IDENTIFIED |
| 1.5 | `db.py:2055` `book_with_escrow` | Internal escrow hold via ledger; no Stripe. | Simulated escrow. | Stripe manual-capture authorization holds the funds. | IDENTIFIED |
| 1.6 | `db.py:2092` `release_booking` | On job completion, grows `seller.earnings` + `platform.revenue` from internal escrow. | Seller "earnings" are fabricated, not from a Stripe transfer. | `capture()` → `PayoutObligation` → Connect transfer creates real earnings. | IDENTIFIED |
| 1.7 | `db.py:2125` `refund_booking` | Returns escrow to wallet. | Fake refund of fake money. | Stripe refund of the PaymentIntent/charge. | IDENTIFIED |
| 1.8 | `main.py:3045` `/webhooks/payment` → `db.py:2216` `credit_user_by_username` | Credits wallet from a generic HMAC webhook (`PAYMENT_WEBHOOK_SECRET`), not Stripe-verified. Docstring: "For Stripe, swap the signature check…". | Placeholder deposit rail masquerading as a payment webhook. | Stripe-signed `/webhooks/stripe` is the only funding webhook. | IDENTIFIED |
| 1.9 | `db.py:139` `User.balance`, `db.py:140` `User.earnings`, `db.py:366` `Organization.balance`, `db.py:540` `Platform.revenue` | Money caches that hold the fake balances. | Source of the fake numbers shown as real. | Balances derived from ledger over real Stripe flows; drop spendable-wallet columns. | IDENTIFIED |
| 1.10 | `db.py:1986` `maybe_reward_referral` / `db.py:1980` `_grant_promo_credit` | Grants spendable wallet credit (default $20) to referrer+referee. | Inflates the same fake wallet that acts as the payment method. | If retained, promo credit must be a discount on a real Stripe charge, not spendable cash. | IDENTIFIED |

### Group 2 — Legacy seller payout (earnings → withdraw → stub) — FAKE-MONEY / STUB-PROVIDER

| # | File:line — symbol | Previous behavior | Why unsafe / misleading | Replacement | Status |
|---|---|---|---|---|---|
| 2.1 | `main.py:2540` `/wallet/withdraw` → `db.py:2561` `request_payout` | Debits internal `earnings`, creates `Payout(requested)`. | Cashes out fabricated earnings. | Payout of a real `PayoutObligation` via `payout_routing`/Connect. | IDENTIFIED |
| 2.2 | `payout_providers.py:51` `StubProvider.send` | Returns `{"status":"confirmed","ref":"stub-…"}` — pays nobody. | **Fake payout success.** | Real rail adapter (`StripeConnectPayoutRail`, etc.). | IDENTIFIED |
| 2.3 | `payout_providers.py:24` `screen()` | Returns `True` unconditionally when `PAYOUT_STUB=true`. | Disables AML/sanctions screening. | Real screening provider; `compliance_ok` fail-closed (already built). | IDENTIFIED |
| 2.4 | `main.py:2513` `/wallet/methods/{id}/verify` | Marks method `verified` after stub screen. | Fake KYC. | Stripe/real verification state. | IDENTIFIED |
| 2.5 | `payout_providers.py:114` `process_payouts` + `tools/payout_worker.py` | Drives the stub provider, marks payouts `confirmed`. | Fake settlement loop. | Batch execution via `execute_batch` on real rails. | IDENTIFIED |
| 2.6 | `main.py:3522` `/seller/earnings` (+ `/wallet/payouts`, `/wallet/schedule`) | Reports internal `earnings`. | Not Stripe-derived. | Report from obligations/transfers. | IDENTIFIED |

### Group 3 — Dev bypass — DEV-BYPASS

| # | File:line — symbol | Previous behavior | Why unsafe / misleading | Replacement | Status |
|---|---|---|---|---|---|
| 3.1 | `main.py:1411,1429` `GOOGLE_OAUTH_STUB` | When true, logs anyone in as admin `info@petabyte.market` with a valid JWT. | Auth bypass → full control of financial admin routes. | Real OAuth; the offline test double stays test-only, never enabled in a served app. | IDENTIFIED (already blocked in prod by boot gate) |
| 3.2 | `main.py:3850` `/launch`, `main.py:1570` `/request_vm` | Dispatch gated only on internal `try_debit`. | **A job runs with no verified Stripe payment.** | Dispatch requires a Stripe-authorized (or captured) ComputeTransaction. | IDENTIFIED (the central rewire) |

### Group 4 — Demo — DEMO-DATA

| # | File:line — symbol | Previous behavior | Why unsafe / misleading | Replacement | Status |
|---|---|---|---|---|---|
| 4.1 | `demo.py` (`/deposit` seed, `SIMULATED_RESULT`, forces sandbox+stubs) | Fabricates balances via `/deposit`; settles internal escrow with simulated job results. Every row stamped `is_demo=True`. | Demo money is fake, not real Stripe test objects. (Honestly labelled, but still simulated payments.) | Demo creates **real Stripe test-mode objects** (`acct_`/`pi_`/`ch_`/`tr_`); GPU may remain simulated. Needs Stripe test keys. | IDENTIFIED |
| 4.2 | `demo_run.sh` | Exports sandbox/stub env, seeds + serves. | Same as 4.1. | Same architecture as prod, test keys only. | IDENTIFIED |

### Config flags that enable fake behavior (see `PAYMENTS_AND_PAYOUTS_ROADMAP.md` for the full table)

- `PAYMENTS_MODE=sandbox` (`main.py:92`) — **core fake-money enabler**; `/deposit` mints credit. → to be removed with the wallet.
- `PAYOUT_STUB=true` (`payout_providers.py`) — stub payout "confirms" + AML auto-pass. → removed with Group 2.
- `GOOGLE_OAUTH_STUB=true` (`main.py`) — auth bypass. → test-only.
- `STRIPE_GATEWAY=fake` (`stripe_gateway.py`) — offline double; fine for unit tests, must not be the served gateway.

---

## Guardrails already added (DONE this pass)

These are additive and shipped; they make live-money misconfiguration impossible without
touching the fake-money removal yet:

- **`PAYMENTS_LIVE_ENABLED` master switch** — a live Stripe key is refused unless
  `PAYMENTS_LIVE_ENABLED=true` **and** `STRIPE_ALLOW_LIVE=true` **and**
  `ENVIRONMENT=production` (`stripe_gateway.assert_test_mode`). Live cannot start while
  the flag is false.
- **No test/live key mixing** — a test secret with a live publishable key (or vice-versa)
  hard-fails.
- **`STRIPE_MODE` consistency** — a declared mode that disagrees with the key prefix
  hard-fails.
- **No half-configured live mode** — in production, `PAYMENTS_LIVE_ENABLED=true` requires
  real keys + webhook secret + `STRIPE_GATEWAY=real`, else the app refuses to start
  (`main.py:_assert_production_is_safe`).
- **Tests:** `stripe_test.py` now asserts all of the above (71/71 green).

---

## Migration plan (sequenced so tests stay green between phases)

1. **✅ Fail-safe config** (done above): `PAYMENTS_LIVE_ENABLED`, key-mode checks, no
   half-live.
2. **Immutable TEST/LIVE mode field** on financial records + metric isolation (so test
   data can never appear as real revenue). *(additive)*
3. **Wire `/launch` (and `/request_vm`) through Stripe Connect** — add the real path
   (authorize → reserve → dispatch → meter → capture → transfer/obligation) alongside the
   wallet, behind a switch. Job dispatch requires a verified Stripe payment. *(additive)*
4. **Migrate tests + demo** to the Stripe path (real test objects in the demo — requires
   owner-supplied `sk_test_`/`pk_test_` keys). Add Stripe test-mode banners + `TEST`
   markings.
5. **Delete the fake surface** — remove Groups 1–2 code, obsolete columns/routes/UI,
   `PAYMENTS_MODE`, `PAYOUT_STUB`/`StubProvider`, the generic `/webhooks/payment`; add
   migrations; update tests; confirm no runtime import references the removed code
   (grep clean). Flip each item's Status to `REMOVED` here with its proving test.
6. **Country coverage verification + Circle adapter** (behind `CIRCLE_PAYOUTS_ENABLED=false`).

**Blockers / decisions needed from the owner before Phase 3–5:**
- Confirmation to rewire the product's payment UX from a wallet to per-job Stripe
  checkout (this changes buyer flow and breaks/rewrites ~100 wallet-based test
  assertions — expected and accepted, but it should be a conscious call).
- Stripe **test-mode API keys** (`sk_test_`/`pk_test_`) + a webhook secret, so the demo
  can create genuine Stripe test objects instead of fabricated balances.
