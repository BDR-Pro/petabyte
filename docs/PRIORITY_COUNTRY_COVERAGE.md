# Priority-Market Payout Capability

A per-capability verification of the **20 highest-value GPU-supply markets** we track for
seller-payout readiness. This is a **watch list** — which markets we verify — layered on
top of the normalized capability dataset (`config/payout_country_capabilities.json`). It
makes **no capability claim of its own**: every market is resolved to its *real* payout
rail, currency, and status from the dataset rows (or to `not_supported` / `blocked_sanctioned`
when it has no row / is embargoed).

> **Honesty contract.** `active_today` — payable right now — is the *only* "supported"
> number. The shipped dataset is honestly **0 active** until a real end-to-end payout is
> verified for a country (Stripe still runs in test mode; the Connect account is approved
> but no country has been live-verified). "Capable" means *a rail exists on file*, not that
> money moves today. See `docs/GLOBAL_PAYOUT_COVERAGE.md` and
> `docs/PAYMENTS_AND_PAYOUTS_ROADMAP.md`.

## The 20 priority markets (verified 2026-08-05)

| CC | Country | Rail | Settlement | Status |
|----|---------|------|-----------|--------|
| US | United States | `connect_express` | usd | pending_provider_approval |
| GB | United Kingdom | `connect_express` | gbp | pending_provider_approval |
| DE | Germany | `connect_express` | eur | pending_provider_approval |
| CA | Canada | `connect_express` | cad | pending_provider_approval |
| FR | France | `connect_express` | eur | pending_provider_approval |
| NL | Netherlands | `connect_express` | eur | pending_provider_approval |
| SE | Sweden | `connect_express` | sek | pending_provider_approval |
| AU | Australia | `connect_express` | aud | pending_provider_approval |
| JP | Japan | `connect_express` | jpy | pending_provider_approval |
| SG | Singapore | `connect_express` | sgd | pending_provider_approval |
| PL | Poland | `connect_express` | pln | pending_provider_approval |
| ES | Spain | `connect_express` | eur | pending_provider_approval |
| IT | Italy | `connect_express` | eur | pending_provider_approval |
| BR | Brazil | `connect_express` | brl | pending_provider_approval |
| AE | United Arab Emirates | `connect_express` | aed | pending_provider_approval |
| IN | India | — | — | **not_supported** |
| KR | South Korea | — | — | **not_supported** |
| NG | Nigeria | `global_payouts` | usd | **not_implemented** (planned) |
| KE | Kenya | `usdc_stablecoin` | usdc | **not_implemented** (planned) |
| RU | Russia | — | — | **blocked_sanctioned** |

**Summary:** 20 markets · **0 active today** · 17 capable (rail on file) · 2 not supported ·
1 blocked. Every honest outcome bucket is represented on purpose.

### Why these outcomes

- **15 Stripe Connect markets** (`pending_provider_approval`): the connected-account adapter
  is implemented and sandbox-verified, but no country flips to `active` until a real
  end-to-end payout is verified against the live-approved Connect account.
- **IN, KR — `not_supported`:** Stripe Connect does **not** support these as
  connected-account (recipient) countries for the platform's US cross-border payout model,
  and no alternative rail is implemented. They resolve to `not_supported` rather than
  silently defaulting to a rail that would fail — a fail-honest outcome.
- **NG (Stripe Global Payouts), KE (Circle USDC):** a rail is *planned* but the adapter is
  `not_implemented`; they can never count as payable until built + approved (KE also
  requires seller stablecoin consent + wallet screening).
- **RU — `blocked_sanctioned`:** embargoed; the sanctions gate returns no capability rows
  regardless of any dataset entry.

## How to regenerate / verify

```bash
# Human-readable report (exits 0 unless a market resolves to a contradictory status):
make priority-coverage
# or:
python3 scripts/verify_payout_country_coverage.py --priority

# Machine-readable JSON (for the frontend / DD bundle):
python3 scripts/verify_payout_country_coverage.py --priority --json

# The hermetic per-capability test (invariants, not a hardcoded pass table):
cd lumaris_api && python3 priority_country_test.py
```

## Programmatic access

- **Library:** `lumaris_api/payout_capabilities.py`
  - `priority_countries()` → the watch-list codes
  - `country_capability("US")` → one normalized capability record
  - `priority_capability_matrix()` → all 20 + a status breakdown
- **Public API (read-only, no secrets):**
  - `GET /payments/coverage` → the full priority matrix
  - `GET /payments/coverage?country=DE` → a single country's capability record

## Editing the watch list

The list lives in `_meta.priority_countries` in
`config/payout_country_capabilities.json` (with display-name fallbacks for off-dataset
markets in `_meta.priority_country_names`). It is the single source of truth — do **not**
introduce a parallel hardcoded country array elsewhere. Changing a market's *capability*
(rail, currency, approval) means editing its row in `countries[]`, never the watch list;
and a row only becomes `active` after a real payout is verified, never to make a check pass.
