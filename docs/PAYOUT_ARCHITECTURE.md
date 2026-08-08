# Payout architecture

Petabyte is a two-sided compute marketplace. **Buyer payment** and **seller payout** are
separate concerns and use separate rails. This document describes how seller eligibility,
payout obligations, and payout execution work, and the provider-agnostic boundary that lets
Petabyte add payout rails without touching marketplace logic.

## The core eligibility rule

```
a seller may accept paid jobs
    IF
the seller has >= 1 verified, enabled, payout-ready payout RAIL
```

It is **not** "the seller's Stripe Connect account is payout-ready." Stripe Connect is one
rail; it is not synonymous with eligibility.

Every marketplace call site asks the single centralized service — never a provider's fields:

```python
import payout_readiness
payout_readiness.get_seller_payout_readiness(db, seller)   # structured result
payout_readiness.is_seller_payout_ready(db, seller_id)     # bool convenience
```

Structured result:

```json
{
  "ready": true,
  "provider": "stripe",
  "rail": "stripe_connect",
  "country": "US",
  "reason": null,
  "why_blocked": null,
  "requirements_due": [],
  "requirements_past_due": []
}
```

`reason` (when not ready) is a machine code: `no_payout_rail`, `verification_required`,
`capabilities_pending`, or `restricted`. `GET /payments/payout/readiness` returns this
rail-neutral result to the seller UI (no provider secrets, bank numbers, or identity data).

Adding a rail = adding one resolver to `payout_readiness._RAIL_RESOLVERS`. The buyer quote,
the `authorize` gate, and the `can_accept_paid_jobs` flag all flow through the service, so a new
rail makes sellers eligible **without changing any marketplace code**. `payout_readiness_test.py`
proves this (a synthetic future rail makes a seller with no Connect account eligible), and proves
`authorize` refuses whenever the service says not-ready even with a fully-ready Connect account.

## Funds flow (buyer payment is decoupled from seller payout)

```
BUYER
  |  Stripe PaymentIntent (manual capture)   <- buyer payment rail
  v
PETABYTE API
  +--> ComputeTransaction (state machine)
  +--> Ledger (double-entry, AUTHORITATIVE)
  +--> PayoutObligation (provider-neutral, mode-aware, 14-day risk hold)
  v
Payout Router (payout_routing.select_rail, at disbursement time)
  +----------------+----------------------+-----------------------+
  v                v                      v                       v
StripeConnect   StripeGlobalPayouts    stablecoin/USDC        ManualReview
(implemented)   (NOT_IMPLEMENTED)      (NOT_IMPLEMENTED)      (fallback)
  +----------------+----------------------+-----------------------+
                              v
                           SELLER
```

The ledger — not any provider — is the authoritative record of what Petabyte owes. Seller
balance is never inferred by summing Stripe payouts. All rails consume the same
`PayoutObligation` / `PayoutBatch` accounting.

## Components

| Module | Responsibility |
|--------|----------------|
| `payout_readiness.py` | **Seller eligibility.** "Does the seller have a usable rail?" The one place marketplace logic asks. |
| `payout_rails.py` | The `PayoutRail` interface + concrete rails. `StripeConnectPayoutRail` is implemented; `StripeGlobalPayoutRail` / stablecoin rails are explicit `NOT_IMPLEMENTED` (no fakes). |
| `payout_capabilities.py` | Country/rail capability matrix from `config/payout_country_capabilities.json`; sanctions-aware; strict `implemented + active` definition of "covered". |
| `payout_routing.py` | Picks the legally-available rail at disbursement, aggregates obligations into batches, fails closed without an approved compliance decision. |
| `payout_providers.py` | Provider send-adapters (stub/real seams). |
| `stripe_connect.py` | The Connect rail's account lifecycle, buyer PaymentIntent authorize/capture, and the held obligation on capture. |

## Stripe Connect vs Stripe Global Payouts

- **Connect (implemented):** readiness requires `details_submitted AND charges_enabled AND
  payouts_enabled AND transfers_capability == "active"` (`ConnectedAccount.payout_ready()`).
  This module never weakens those checks — it only centralizes the decision.
- **Global Payouts (not implemented):** exists as an explicit `NOT_IMPLEMENTED` rail behind the
  capability matrix. It must **not** be implemented as "pretend Connect": its recipient
  lifecycle, verification, requirements, and payout semantics differ. Implementing it requires
  verifying Stripe's **current** official API and compliance-approved countries first — the code
  never invents endpoints or claims country support.

## TEST / LIVE isolation

`ConnectedAccount.gateway_mode`, `ComputeTransaction.mode`, `PayoutObligation.mode`, and
`PayoutBatch.mode` are immutable and mode-aware. A TEST obligation can never enter a LIVE payout
and vice versa. A fake connected account can never be reused once the process runs the real
gateway (`ConnectedAccountModeMismatch`, fail closed).

## The 14-day hold

Capture creates a **held** `PayoutObligation` (`accrued`), available only after the configured
risk hold (`PAYOUT_HOLD_DAYS`, default 14). The hold is clock-injectable for tests
(`db.payout_hold_elapsed(obl, now=…)`) — there is no runtime HTTP clock override, and LIVE never
bypasses the hold.

## What is verified vs not

- **Verified:** Stripe Connect rail end-to-end in TEST mode (onboarding → readiness → buyer
  authorize → manual capture → held obligation), the provider-agnostic readiness pivot, and
  TEST/LIVE isolation.
- **Not verified / not implemented:** real Stripe Global Payouts and stablecoin rails (gated
  `NOT_IMPLEMENTED`); per-country legal enablement remains an explicit, config-driven decision.
