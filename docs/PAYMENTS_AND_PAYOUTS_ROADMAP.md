# Payments & Global Payouts Roadmap

**Owner directive (2026-08-05):** build a solid, working Stripe Connect marketplace
first, then expand global payout coverage cleanly. The platform now has an **approved
Stripe account with Stripe Connect enabled** (owner-confirmed). This document is the
single source of truth for the ordered plan and supersedes the sequencing in
`GLOBAL_PAYOUT_REPORT.md` (which remains the honest status snapshot).

The order is fixed: **(1) Connect → (2) Global Payouts → (3) Circle → (4) measure
coverage → (5) one more provider only if still short.**

---

## Guiding principle — provider-agnostic by construction

The core marketplace, settlement, and ledger must never know which payout provider is
used. This is already the architecture in the repo; every step below is *adding an
adapter*, never rewiring the core.

```
  Buyer payment ─┐
                 ▼
        ┌───────────────────┐     records what we OWE, provider-neutral,
        │  Settlement/capture│───▶ independent of the ledger and of any provider
        └───────────────────┘        │
                 │                    ▼
        ┌───────────────────┐   ┌──────────────────────┐
        │ Double-entry LEDGER│   │  PayoutObligation      │  (db.py)
        │ (accounting truth) │   │  accrued→available→…   │
        └───────────────────┘   └──────────┬───────────┘
                                            ▼
                                  ┌──────────────────────┐
                                  │  Routing engine        │  select_rail()
                                  │  sanctions ▸ compliance│  (payout_routing.py)
                                  │  ▸ priority ▸ consent   │
                                  └──────────┬───────────┘
                                            ▼
              ┌──────────── PayoutRail interface (payout_rails.py) ───────────┐
              │  get_country_capability()          send_payout()               │
              ├───────────────┬───────────────┬───────────────┬──────────────┤
              │ StripeConnect  │ StripeGlobal   │ Circle         │ <future>     │
              │ (Step 1) REAL  │ Payouts(Step 2)│ (Step 3)       │ (Step 5)     │
              └───────────────┴───────────────┴───────────────┴──────────────┘
```

**The contract every provider plugs into (already defined, `payout_rails.py`):**

| Method | Responsibility |
|---|---|
| `get_country_capability(country, recipient_type, currency)` | Return a `PayoutCapability` (status, bank/stablecoin, limits, delivery). Reads the normalized dataset — never hardcoded. |
| `send_payout(db, obligation, idempotency_key)` | Move money for one obligation/batch idempotently; return an `ExternalPayout`. |
| `retrieve_payout(id)` | Reconcile external status back to us. |

Adding a provider = **(a)** implement one adapter class, **(b)** add capability rows to
`config/payout_country_capabilities.json`, **(c)** add the rail to the priority list.
**Zero** changes to `authorize/capture/transfer`, the ledger, or the marketplace UI.
This is what "provider-agnostic" means here, and it is already true.

---

## Current state (grounded, not aspirational)

| Piece | State |
|---|---|
| Connect end-to-end state machine | ✅ Built: `DRAFT → PAYMENT_REQUIRES_ACTION → PAYMENT_AUTHORIZED → GPU_RESERVED → DISPATCHING → …CAPTURE_PENDING → PAYMENT_CAPTURED → SELLER_TRANSFER_PENDING → SELLER_TRANSFERRED → COMPLETED` (`stripe_connect.py`) |
| HTTP surface | ✅ onboarding, `/payments/authorize`, reserve/dispatch/meter/capture/transfer, `/webhooks/stripe`, earnings views |
| Separate charges & transfers, manual capture, integer minor units | ✅ Implemented + tested |
| Webhook-authoritative, idempotent, at-most-once | ✅ Implemented + tested |
| Tests | ✅ `stripe` 68/68, `payout` 26/26 (SQLite + Postgres) |
| Provider-neutral obligation + routing + aggregation | ✅ Built (Task 4) |
| **Live-mode payouts verified per country** | ❌ **Not yet** — Stripe runs in test mode; `0` countries `active` |

So Step 1 is ~90% engineering-complete. What remains is **productionizing and
live-verifying**, not building from scratch.

---

## Step 1 — Complete Stripe Connect (production-quality, all Connect countries)

**Goal:** the full flow works for real money for every country Stripe Connect supports as
a connected-account (recipient) country.

**Remaining work (the honest gap list):**

1. **Live-mode enablement, safely.** The code hard-blocks live keys unless
   `ENVIRONMENT=production` **and** `STRIPE_ALLOW_LIVE=true` (`stripe_gateway.assert_test_mode`).
   Wire the approved live keys through secrets management; keep test mode the default for
   CI and dev. *No key ever in the repo.*
2. **Drive capture from real metered usage, not an admin button.** Today
   `/admin/payments/{id}/meter` + `/capture` are operator-triggered. Production: job
   completion → metered seconds → `capture(amount = metered usage)` automatically, with
   the admin route retained as a manual override. Capture is already
   usage-based and idempotent; this is wiring, not redesign.
3. **Seller country + cross-border onboarding.** Collect the seller's country at
   onboarding and pass it to connected-account creation so cross-border payouts work
   (`get_or_create_connected_account(country=…)`). Surface bank vs. eligibility per
   country in the onboarding UI.
4. **Automatic seller settlement.** After capture + risk-hold, transfer the seller's net
   (direct `transfer_to_seller`, or aggregate via `create_and_send_batch` on a schedule).
   The anti-double-pay guard across both paths is already in place.
5. **Flip coverage to reflect reality — only after live verification.** For each Connect
   country, run a real test-mode (then live) end-to-end payout; on success set
   `approved: true` + `availability_status: "active"` for that row. The coverage number
   rises **because** we verified it, not because the account is approved on paper.

**Definition of done for Step 1:**
- A buyer in a supported country can pay; a seller in any Stripe-Connect recipient
  country is paid their net after commission, end-to-end, in live mode.
- `verify_payout_country_coverage.py` shows the Connect countries as `active` (backed by
  real verification), and the `stripe` suite stays green in both test and (smoke) live
  config.
- No manual step is required for the happy path.

---

## Step 2 — Prepare for Stripe Global Payouts

**What it is / how it differs from Connect.** Connect pays *connected accounts* (full
sub-accounts you onboard). **Global Payouts** lets a platform pay **recipients** in
countries beyond where you can onboard a full connected account — broader *destination*
reach, lighter recipient object. It extends seller reach without a second settlement
system.

**Approval / configuration required (verify against your Stripe dashboard + rep — do not
assume):**
- Global Payouts is **not universally on**. It typically requires **Stripe enabling the
  product for your platform** (sales/eligibility review), on top of your existing
  approved account. Confirm with your Stripe account manager exactly which product SKU
  ("Global Payouts" / cross-border payouts to recipients) is enabled for your account and
  in which platform region.
- Confirm your **platform country** is eligible to originate Global Payouts (US platforms
  are generally eligible; verify).
- Recipient **onboarding/KYC** requirements per destination country.
- Supported **destination currencies** and **payout methods** (bank vs. card/wallet vary
  by country).

**Code design so it drops in with minimal change (already scaffolded):**
- `StripeGlobalPayoutRail` exists as an honest `NOT_IMPLEMENTED` stub in
  `payout_rails.py`. Implementing it = fill in `get_country_capability` (read the Global
  Payouts rows) and `send_payout` (call Stripe's recipient/payout API with the
  obligation's idempotency key).
- Add the real destination rows to the dataset (`product: "global_payouts"`), flip to
  `implemented` + `active` per country **after** verification.
- It already sits second in `RAIL_PRIORITY`, so routing prefers Connect and falls back to
  Global Payouts automatically. **No settlement/ledger change.**

**Deliverable of this step:** a short written confirmation from Stripe of what's enabled
for your account, plus the implemented adapter behind a feature flag, ready to activate
per verified country.

---

## Step 3 — Prepare Circle Mint + stablecoin payouts

> **Honesty caveat up front:** per Circle's own materials, **Circle Mint is aimed at
> institutions** (exchanges, PSPs, fintechs, large financials) and is *"not available to
> individuals or small businesses."* Circle's third-party **Payouts API** launched via
> the US and **Singapore** entities. Before building, we must confirm Petabyte
> **qualifies** and that Circle will approve a GPU-marketplace use case. If it won't, we
> skip Circle and lean on Steps 2/5 — that's a legitimate outcome, not a failure.

**Adapter design (modular, already scaffolded):**
- `CircleStablecoinPayoutRail` exists as a `NOT_IMPLEMENTED` stub. Implement
  `get_country_capability` (Circle payout countries) and `send_payout` (Circle Payouts
  API: create a payout from the USDC balance to the seller's verified wallet/bank).
- Stablecoin is **never auto-selected**: routing already requires explicit seller
  **consent** (`PayoutMethodRail.consented_at`) + a **verified** method + an implemented
  rail. Circle plugs into that gate unchanged.

**Exactly what you (owner) need to obtain for Circle — bring me confirmation of each:**
1. **Circle Mint account** — apply at circle.com/circle-mint; expect a rigorous
   application.
2. **KYB (Know-Your-Business) approval** — required for production API use; business
   registration, ownership, documents.
3. **KYC / sanctions screening** on the business and beneficial owners (Circle runs its
   own; processing can take days to weeks).
4. **Eligible operating entity/region** — confirm whether you're served by Circle's US
   entity, the Singapore entity, or another; this dictates which Payouts API you can use.
5. **Production API credentials** (API key) — sandbox first, then production after KYB.
6. **A funded USDC treasury / Circle wallet** to pay out from, plus your bank rails for
   mint/redeem 1:1.
7. **On-chain wallet-screening** provider/process for **destination** wallets (sanctions
   / mixer screening) — required before any real send.
8. **Chain decision** (e.g. USDC on which network) and fee model.
9. Legal sign-off per §6 of `GLOBAL_PAYOUT_LEGAL_QUESTIONS.md` (VASP/MiCA, travel rule,
   tax characterization).

**Deliverable of this step:** confirmed Circle eligibility + accounts, and the adapter
implemented behind the consent gate, ready to activate per verified country. **No
settlement/ledger change.**

---

## Step 4 — Calculate the actual verified country coverage (only after 1–3)

**Rule: no guessing. Pull official provider country lists, cite them with dates, and
count only rows that are implemented + approved + active + not sanctioned.**

**Method:**
1. **Connect recipient countries** — from Stripe's official cross-border payouts /
   connected-account country docs.
2. **+ Global Payouts destinations** — from Stripe's Global Payouts country docs
   (destinations Connect can't reach).
3. **+ Circle payout countries** — from Circle's official payout-country docs.
4. **Deduplicate** to unique countries; **subtract** sanctioned countries; **exclude**
   anything not live-verified.
5. Regenerate the dataset and run `scripts/verify_payout_country_coverage.py`.

**Report template (to be filled from official docs, with source URLs + check dates):**

| Segment | Countries | Count |
|---|---|---:|
| Covered by Stripe Connect | … | … |
| **Additional** via Stripe Global Payouts | … | … |
| **Additional** via Circle | … | … |
| **Total unique supported** | — | **…** |
| Remaining unsupported (excl. sanctioned) | … | … |
| Blocked (sanctioned) | CU, IR, KP, SY, RU, BY | 6 |

Output goes into `GLOBAL_PAYOUT_COVERAGE.md` and the CI coverage check reflects the real
number.

---

## Step 5 — One additional bank-payout provider, only if still below target

**Trigger:** run this step **only** if the unique total from Step 4 is below your target.
*(You have not yet given a target number — I need it before Step 5. See "Open inputs".)*

**Compare on the countries that are still uncovered after Steps 1–4** — not on general
reputation:

| Provider | Strength (typical) | Evaluate for |
|---|---|---|
| Wise Platform | Broad bank reach, clean API, transparent FX | Coverage of the *remaining* gap; API quality |
| Airwallex | Strong APAC + global accounts | Gap fit; multi-currency settlement |
| dLocal | Emerging markets (LatAm, Africa, Asia) | Exactly the countries Stripe/Circle miss |
| Thunes | Wallets + bank in emerging markets | Wallet-heavy regions |
| Payoneer | Freelancer/marketplace payouts | Recipient onboarding UX |

**Decision rule:** recommend the **single** provider that (a) covers the most of the
*remaining* uncovered countries, (b) has the best API + lowest implementation effort into
the existing `PayoutRail` interface, and (c) meets compliance. **Do not add more than one
unless one genuinely cannot close the gap.** The winner becomes one more adapter — same
interface, no core changes.

---

## Open inputs I need from you

1. **Target country count** (drives Step 4 pass/fail and whether Step 5 runs at all).
2. **Live-mode go-ahead** + which Connect countries to verify first (Step 1 activation).
3. **First seller countries** you're onboarding (so I sequence cross-border onboarding).
4. **Circle intent** — do you want to pursue institutional Circle Mint, given the
   institution-oriented eligibility? If not, we skip Step 3 and rely on Steps 2/5.

---

## Guardrails that stay true through every step

- Coverage flips to `active` **only** on real, verified end-to-end payouts — never on a
  paper approval or an edited dataset.
- Unimplemented adapters return `NOT_IMPLEMENTED` and **raise** on send — no fake success.
- Sanctioned countries are hard-blocked; compliance **fails closed**; stablecoin requires
  explicit consent.
- One obligation is paid by exactly one path (guarded across direct + batch).
- Stripe **test mode by default**; live mode only behind the explicit production gate,
  with keys in secrets, never in the repo.
