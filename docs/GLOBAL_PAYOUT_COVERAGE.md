# Global Payout Coverage

**Platform country:** US (Stripe platform account) &nbsp;•&nbsp; **Verified:** 2026-08-05
&nbsp;•&nbsp; **Source of truth:** [`config/payout_country_capabilities.json`](../config/payout_country_capabilities.json)

This document is the honest, auditable statement of *where a seller can actually be
paid today* and *where they cannot yet*. It is generated from the same normalized
dataset the routing engine and the CI coverage check read — there is no second,
prettier list. If a country is not in the dataset as `active`, it is not supported,
full stop.

> **Read this first.** Petabyte **has an approved Stripe Connect account**
> (owner-confirmed 2026-08-05), but the code still runs Stripe in **test mode** and **no
> country has been live end-to-end payout-verified yet**. Therefore **zero countries are
> `active`** right now. The 46 Stripe Connect countries below are *implemented and
> sandbox-verified* and sit in `pending_provider_approval` — the code path exists and is
> tested, and the account is approved, but a country only becomes `active` after a real
> end-to-end payout is verified for it (see
> [`PAYMENTS_AND_PAYOUTS_ROADMAP.md`](./PAYMENTS_AND_PAYOUTS_ROADMAP.md), Step 1). We do
> **not** count these toward coverage, and we do **not** advertise them as supported,
> until that verification happens.

---

## Approval states (these are distinct — don't collapse them)

"Approved" is ambiguous, so the docs track four separate states and their current value:

| State | Meaning | Current value |
|---|---|---|
| Platform-account approval | Petabyte's Stripe platform account exists & is approved | **Yes** (owner-confirmed 2026-08-05) |
| Live Connect enablement | Connect enabled on that account | **Yes** (owner-confirmed) |
| Country/rail approval | a given country/rail is approved for our account | per-row `approved` flag (see dataset) |
| Live end-to-end verification | a real payout was verified for that country | **None yet** — code runs in Stripe test mode |

A country is `active` only when country/rail approval **and** live end-to-end
verification are both true. Platform-account approval alone does **not** make any country
active — which is why the number below is 0.

---

## The one number that matters

| Metric | Value |
|---|---:|
| **ACTIVE countries (verified + implemented + approved + not sanctioned)** | **0 / 100** |
| Pending provider approval (implemented, awaiting Stripe live approval) | 46 |
| Preview | 0 |
| Planned (adapter not yet built) | 2 |
| Not implemented | 2 |
| Blocked (sanctioned) | 6 |

`python scripts/verify_payout_country_coverage.py` prints this breakdown and **exits
non-zero** while ACTIVE < 100. That red status is the truth, not a bug. It turns green
only when real provider approvals and shipped rail adapters raise the ACTIVE count —
**never** by editing the dataset.

### What "ACTIVE" strictly requires

A country/rail row counts as ACTIVE **only** when *all* of these hold
(`payout_capabilities._row_is_active`):

1. `implementation_status == "implemented"` — the rail adapter genuinely exists and is
   exercised by tests (not a stub that returns fake success).
2. `availability_status == "active"` — not `preview`, `planned`, or
   `pending_provider_approval`.
3. `approved == true` when `provider_approval_required` is set — a real approval from
   the provider for *Petabyte's* account, not "documented as generally available".
4. The country is not in the sanctioned block list.

Anything short of all four does **not** count. This is the mechanism that prevents an
unimplemented adapter or an "available per the docs" product from inflating the number.

---

## Buyer coverage vs. seller coverage (these are different questions)

The requirement is global on **both** sides, and they have different answers:

- **Buyers (paying in):** Stripe Checkout / PaymentIntents accept cards and local
  methods from ~most of the world in test mode. Buyer-side reach is broad and is *not*
  the bottleneck. Buyer geography is gated only by sanctions/eligibility, not by a
  payout rail.
- **Sellers (getting paid out):** this is the hard, honest constraint and the subject
  of this document. A buyer in country X paying successfully says **nothing** about
  whether a seller in country Y can be paid. The coverage number above is the
  **seller-payout** number.

Do not conflate the two. "We take payments from 100 countries" is not "we pay sellers
in 100 countries."

---

## Rails and their real status

| Rail (`PayoutRailType`) | Implemented? | Countries | Status | Notes |
|---|---|---|---|---|
| `STRIPE_CONNECT` (Express) | ✅ Yes, tested | 46 | `pending_provider_approval` | Separate charges & transfers; blocked from `active` only by live-account approval. |
| `STRIPE_GLOBAL_PAYOUTS` | ❌ No | 1 (NG, planned) | `not_implemented` | Adapter returns `NOT_IMPLEMENTED`; `send_payout` raises. Does not count. |
| `STRIPE_STABLECOIN` | ❌ No | 0 | `not_implemented` | Placeholder rail; refuses to send. |
| `CIRCLE_STABLECOIN` (USDC) | ❌ No | 1 (KE, planned) | `not_implemented` | Requires seller consent + wallet screening before it could ever be selected. |
| `MANUAL_REVIEW` | ✅ Yes (fallback) | — | — | Queues an obligation for human handling when no automated rail fits. Never fabricates a payout. |

The unimplemented rails are in the dataset **on purpose**, as `planned` /
`not_implemented`, so the roadmap is visible — but they are excluded from ACTIVE and
their adapters raise rather than return a fake success.

---

## Stripe Connect countries (implemented, `pending_provider_approval`)

These 46 have a working, sandbox-verified Connect Express adapter. They become ACTIVE
**per country only after Petabyte's live Stripe platform account is approved** and the
row's `approved` flag flips to `true`. Recipient types: `individual`, `company`.
Settlement/KYC/tax per Stripe. Estimated delivery: 2–7 business days on the standard
Stripe payout schedule.

```
AE  AT  AU  BE  BG  BR  CA  CH  CY  CZ  DE  DK  EE  ES  FI  FR
GB  GI  GR  HK  HR  HU  ID  IE  IT  JP  LI  LT  LU  LV  MT  MX
MY  NL  NO  NZ  PH  PL  PT  RO  SE  SG  SI  SK  TH  US
```

Source: `stripe_connect` — <https://docs.stripe.com/connect/cross-border-payouts>
(checked 2026-08-05; documented as generally available, **not** confirmed for
Petabyte's specific account).

---

## Planned / not-implemented (do not advertise)

| Country | Provider / Product | Impl. | Availability | Why listed |
|---|---|---|---|---|
| NG (Nigeria) | Stripe Global Payouts | `not_implemented` | `planned` | Example of extending seller reach beyond Connect countries via a second Stripe product. Adapter not built. |
| KE (Kenya) | Circle USDC stablecoin | `not_implemented` | `planned` | Example of a stablecoin rail for a bank-payout-thin country. Requires explicit seller consent + wallet/sanctions screening before it could ever be routed. Adapter not built. |

These are illustrative of *how* coverage would grow (a second bank rail, then a
stablecoin rail), not claims of coverage.

---

## Blocked — sanctioned countries (never payable)

Payouts to these are hard-blocked in routing regardless of any dataset row, compliance
decision, or seller consent (`payout_capabilities.is_sanctioned` →
`payout_routing.select_rail` returns `blocked`):

```
CU (Cuba)   IR (Iran)   KP (North Korea)   SY (Syria)   RU (Russia)   BY (Belarus)
```

Source: `ofac_sanctions` —
<https://ofac.treasury.gov/sanctions-programs-and-country-information> (checked
2026-08-05). This list is a *floor*, not legal advice; a live launch needs a real
sanctions-screening provider (see the legal questions doc) and this list must be kept
current against OFAC/EU/UK/UN designations.

---

## How to grow the number honestly

The ACTIVE count rises **only** by doing real work, in this order per country:

1. **Approve the provider account.** Get Petabyte's live Stripe Connect platform
   account approved → flip `approved: true` on that country's row and set
   `availability_status: "active"`. That single, truthful edit makes the country ACTIVE
   because the adapter is already implemented and tested.
2. **Implement a new rail** where Connect doesn't reach. Build the adapter (real
   `send_payout`, real capability query), get it tested, get provider approval, then
   set `implementation_status: "implemented"` + `availability_status: "active"`.
3. **Re-run the check.** `make payout-coverage`. The number reflects reality.

There is exactly one prohibited shortcut: editing the dataset to mark a country
`active`/`approved`/`implemented` without the real thing behind it. The routing engine
would then try to pay through a rail that can't pay, and the coverage number would lie.
The CI coverage job runs `continue-on-error` precisely so no one is tempted to "make it
green" by faking data.

---

## Where this is enforced in code

- **Dataset:** `config/payout_country_capabilities.json`
- **Capability model + strict ACTIVE rule:** `lumaris_api/payout_capabilities.py`
- **Rail adapters (implemented vs. `NOT_IMPLEMENTED`):** `lumaris_api/payout_rails.py`
- **Routing (sanctions block, compliance fail-closed, consent gate):**
  `lumaris_api/payout_routing.py`
- **Obligations + batches (provider-neutral ledger of what we owe):** `lumaris_api/db.py`
- **Coverage check (CI + `make payout-coverage`):**
  `scripts/verify_payout_country_coverage.py`
- **Tests proving the invariants:** `lumaris_api/payout_test.py`
