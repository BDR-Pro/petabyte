# Global Buyer & Seller Coverage — Implementation Report

**Date:** 2026-08-05 &nbsp;•&nbsp; **Scope:** provider-neutral payout routing so buyers
can pay in from many countries and sellers can be paid out in many countries via
multiple rails.

This report states, honestly, **what was built, what was not, and what the real
coverage number is.** It is written to be checked against the code, not believed on
faith. The guiding rule throughout: *never claim reach we don't have.* The coverage
check is engineered to stay red until reach is real.

---

## Definition of success — answered honestly

| Success criterion | Status | Truth |
|---|---|---|
| Buyers can pay from many countries | **Partial (by Stripe)** | Buyer-side acceptance rides on Stripe PaymentIntents/Checkout (broad global card + local-method support in test mode). Buyer reach is not the bottleneck and is not gated by a payout rail — only by sanctions/eligibility. |
| Sellers can be paid out in many countries | **Architecture done, reach = 0 active** | The provider-neutral rail + obligation + routing + aggregation layer is built and tested. But **0 countries are ACTIVE** because Stripe live-account approval hasn't happened. 46 are implemented + `pending_provider_approval`. |
| Multiple payout rails, provider-neutral | **Done (1 real, others honest stubs)** | `PayoutRailType` = Connect / Global Payouts / Stripe stablecoin / Circle stablecoin / manual review. Only `STRIPE_CONNECT` is implemented; the rest return `NOT_IMPLEMENTED` and *raise* on send. No fake success anywhere. |
| Obligations independent of any provider AND of the ledger | **Done** | `PayoutObligation` records what we owe a seller at settlement, provider-neutral, and survives provider swaps/failures. It is separate from the double-entry ledger — the ledger is the accounting truth; the obligation is the payout intent. |
| One obligation is never paid twice | **Done + tested** | Claim guard (`UPDATE … WHERE batch_id IS NULL AND state='available'`) + FK + a direct Connect transfer marking the linked obligation `paid`. Tested under aggregation and re-run. |
| Small payments aggregate into one payout | **Done + tested** | `create_and_send_batch` sums a seller's available obligations into one `PayoutBatch`, one external transfer, reconciling to the exact sum, with a below-threshold hold. |
| Sanctioned countries blocked | **Done + tested** | Hard block before any rail is considered; cannot be overridden by consent or a compliance decision. |
| Compliance fails closed | **Done + tested** | No `APPROVED`, unexpired sanctions decision → no payout. |
| Stablecoin requires explicit consent | **Done + tested** | Never auto-selected; requires timestamped consent + a verified method + an implemented rail (none exist yet, so it can never fire today). |
| Coverage test that fails below 100 and can't be gamed | **Done** | `scripts/verify_payout_country_coverage.py` exits non-zero at 0/100 and only counts genuinely active rows. |
| We report the ACTUAL verified number, not an aspiration | **Done** | **0 / 100 active.** Stated plainly here, in the coverage doc, and by the CI job. |

**One-line summary:** the *machinery* for global payouts is built, provider-neutral, and
tested; the *reach* is honestly zero-active today and grows only through real provider
approvals and shipped adapters.

---

## What was built (the 15 pieces)

1. **Country capability model** — `config/payout_country_capabilities.json` +
   `payout_capabilities.py`. Single source of truth; strict ACTIVE definition
   (implemented ∧ active ∧ approved ∧ not-sanctioned).
2. **Rail abstraction** — `payout_rails.py`: a common `PayoutRail` shape
   (`get_country_capability`, `send_payout`) with one real adapter (Connect) and honest
   `NOT_IMPLEMENTED` adapters for the rest.
3. **Real rail** — `StripeConnectPayoutRail` uses the existing gateway to transfer to a
   seller's connected account, gated on `payout_ready`.
4. **Unimplemented rails don't lie** — Global Payouts / stablecoin adapters report
   `NOT_IMPLEMENTED` and raise `NotImplementedRail` on send; excluded from coverage.
5. **Provider-neutral obligations** — `PayoutObligation` in `db.py`, created at capture,
   independent of the ledger and of any provider.
6. **Aggregation** — `PayoutBatch` + `create_and_send_batch`: many small obligations →
   one external payout, deterministic idempotency key over the exact obligation set.
7. **Routing engine** — `select_rail()`: sanctions block → compliance gate → priority
   rail scan → amount/currency/recipient filters → consent gate for stablecoin →
   explanation stored on the batch.
8. **Compliance model** — `ComplianceDecision`, fail-closed `compliance_ok()` with
   expiry.
9. **Sanctions controls** — hard block list + `is_sanctioned`, enforced in both
   capability lookup and routing.
10. **Stablecoin consent model** — `PayoutMethodRail` with `consented_at` +
    `verification_state`; routing refuses stablecoin without it.
11. **Tax hooks** — `withholding_minor`, `tax_form_required`, `pricing_snapshot` recorded
    at settlement (computation itself is future work; see legal doc §4–5).
12. **Provider resilience** — on rail failure a batch is marked `failed` and its
    obligations are *released back to available* for retry on another rail; nothing is
    lost or double-sent.
13. **DB additions** — 4 new tables, additive, build clean from an empty DB on SQLite and
    Postgres (proven by the migration CI job).
14. **Coverage + financial tests** — `payout_test.py` (24 assertions) + the coverage
    script, wired into `run_tests.sh`, the `Makefile`, and CI (both engines).
15. **Documentation** — this report, `GLOBAL_PAYOUT_COVERAGE.md`, and
    `GLOBAL_PAYOUT_LEGAL_QUESTIONS.md`.

---

## What was NOT built (stated so no one assumes it exists)

- **No live end-to-end verification.** The Stripe **platform account is approved with
  Connect enabled** (owner-confirmed), but the code still runs in test mode and **no
  country has had a live payout verified**, so 0 countries are `active`. (Approval
  states are defined in `GLOBAL_PAYOUT_COVERAGE.md`.)
- **No implemented non-Connect rail.** Global Payouts, Stripe stablecoin, and Circle
  USDC are stubs that refuse to send.
- **No tax computation/filing.** Fields to hold the data exist; the 1099/1042-S/DAC7 and
  withholding *logic* does not.
- **No seller clawback / rolling reserve** for post-payout chargebacks.
- **No dedicated buyer-country strategy classifier or a payout-method onboarding UI**
  beyond the existing Connect onboarding — routing and obligations are backend-complete,
  but the seller-facing "bank vs. stablecoin, per country" UI is not built.
- **No real sanctions-screening integration** — the block list is manual and must be
  maintained; a provider is required before live payouts.

Every one of these is a *known gap*, not a hidden one. See
`GLOBAL_PAYOUT_LEGAL_QUESTIONS.md` for the legal/compliance blockers behind them.

---

## Verified numbers (as of 2026-08-05)

```
ACTIVE (verified + implemented + approved + not-sanctioned): 0 / 100
PENDING_PROVIDER_APPROVAL (implemented, awaiting Stripe live): 46
NOT_IMPLEMENTED (planned rails):                                2
BLOCKED (sanctioned):                                          6
```

Tests: `payout` 24/24 (SQLite + Postgres), `stripe` 68/68, `smoke`/`adversarial`/`tunnel`
green. Coverage check exits non-zero by design.

Reproduce:
```
make payout-test        # 24/24
make payout-coverage    # prints 0/100, exits 1 (honest shortfall)
make test               # full SQLite suite incl. payout
make test-postgres      # both engines
```

---

## The path to real coverage

Per country, in order: (1) get the provider account approved → flip `approved:true` +
`availability_status:"active"` on the already-implemented row; or (2) implement a new
rail where Connect doesn't reach, test it, get it approved, then activate. Re-run the
coverage check. The number moves only when reality does. Editing the dataset to force a
pass is the one thing explicitly prohibited — and the reason the CI check runs as a
visible, un-gameable signal rather than a box someone can tick.
