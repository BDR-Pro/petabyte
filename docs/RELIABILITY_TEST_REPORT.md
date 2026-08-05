# Reliability & Payments QA Report

Role: QA / reliability / security / payments audit of the Petabyte transaction system
(seller onboarding → Stripe Connect → discovery → authorization → reservation →
dispatch → metering → capture → commission → seller payout).

Branch `claude/petabyte-funding-readiness-fun2q6`. **Stripe runs in TEST MODE only**
(enforced — see §Security). No live keys anywhere in repo, git history, or environment.

## Phase 0 — Stripe test-mode safety (hard gate)

| Check | Result |
|---|---|
| `sk_live_`/`rk_live_`/`pk_live_` in tracked files | Only in a code guard + docs; **no real key bodies** |
| Real key bodies (`(sk\|pk\|rk)_(test\|live)_…{16,}`) in repo | **none** |
| Live keys in full git history | **none** |
| Live keys in environment | **none** |
| **Enforcement that live mode HARD-FAILS** | **Added** (was missing — see Defect A) |

Result: **PASS — TEST MODE ONLY.** A live key now raises `LiveModeForbidden` at gateway
construction and at app startup; there is no silent fallback to live. The only escape
is a deliberate, loud production opt-in (`ENVIRONMENT=production` **and**
`STRIPE_ALLOW_LIVE=true`).

## Phase 1 — Baseline

Tooling present in this repo: `pytest`-style Python suites (custom `ok()` harness),
server-rendered frontend audited by `audit_frontend.py` (endpoint contract) +
`audit_js.py` (JS parse), PostgreSQL via the CI service / local PG. **Not present**
(honest gaps, not failures): a JS unit runner (Jest/Vitest), Playwright E2E, k6/Locust
load harness, `mypy`/`tsc` typecheck, `docker-compose`/`make dev`. E2E is exercised
in-process via FastAPI `TestClient`; load/concurrency is exercised with
`ThreadPoolExecutor` against the app. These absences are noted, not worked around.

Baseline (clean checkout, before this QA pass):

| Suite | SQLite | PostgreSQL |
|---|---|---|
| `smoke_test.py` | 499 PASS | PASS |
| `adversarial_test.py` (money under real parallel writers) | 14 PASS | 14 PASS |
| `stripe_test.py` (Stripe Connect flow) | 54 PASS | 54 PASS |
| `postgres_test.py` (exact NUMERIC, advisory lock, races) | — | 12 PASS |
| `tunnel_test.py` | 12 PASS | — |
| `demo_test.py` | 21 PASS | — |
| frontend contract + JS parse | PASS | — |

No flaky or skipped tests observed. `ruff` clean on the payment modules (repo-wide
semicolon style is intentional; lint job is non-blocking).

## Phase 2/3/4 — Defects found, reproduced, fixed, proven

Three defects were found by writing failing tests first, then fixed; each now has a
regression test.

### Defect A — CRITICAL (security): live Stripe mode not blocked
- **Repro:** `STRIPE_SECRET_KEY=sk_live_… get_gateway()` returned a live
  `RealStripeGateway` — no guard, silent live-mode path.
- **Impact:** a misconfiguration could move **real money**. Violates the test-mode-only
  mandate.
- **Fix:** `stripe_gateway.assert_test_mode()` hard-fails (`LiveModeForbidden`) on any
  live key, called from `RealStripeGateway.__init__`, `get_gateway()`, and app startup
  (`lifespan`). No live auto-selection from key shape. Opt-in requires
  `ENVIRONMENT=production` + `STRIPE_ALLOW_LIVE=true`.
- **Proof:** 5 regression assertions (test key passes; live secret/publishable keys
  blocked; opt-in only in production; opt-in without production still blocked).

### Defect B — HIGH (payments): duplicate partial refund double-counts
- **Repro:** two identical `POST /admin/payments/{id}/refund {amount:100}` calls →
  internal `refunded_amount` 100 → **200** and **two** `compute_refund` ledger legs,
  while Stripe refunded **once** (idempotency-keyed). Internal books diverged from Stripe.
- **Fix:** the refund/reversal ops now return early on a duplicate/concurrent claim
  (see Defect C's `_begin_op` contract) — no re-increment, no second ledger posting.
- **Proof:** duplicate identical partial refund leaves `refunded_amount == 100` and one
  Stripe refund.

### Defect C — HIGH (concurrency): capture/transfer could double-post the ledger
- **Repro:** 8 concurrent `capture` calls on one transaction → money captured once (PI
  `amount_received == 250`) but the `compute_capture` ledger leg posted **more than
  once** — `_begin_op` handed the in-flight op to a second worker (state `pending`), so
  both posted. Over-debited `external:payments` vs. what Stripe captured.
- **Fix:** `_begin_op` now claims the slot **atomically** via the unique
  idempotency-key constraint and returns `(op, proceed)`: `proceed` is True only for the
  creating worker (or a genuine retry of a `failed` op); a concurrent `pending` or an
  already-`succeeded` op returns `proceed=False` and the caller performs **no** side
  effect. Applied to capture, transfer, refund, reversal, cancel.
- **Proof:** 8-way concurrent capture and 8-way concurrent transfer each move money
  **once** and post **exactly one** ledger leg; verified on SQLite and PostgreSQL.

## Phase 3 — Payments, ledger & reconciliation

- All money is **integer minor units**; the buyer identity `captured == platform_fee +
  seller_net` holds; the Stripe processing fee is tracked separately.
- **Ledger:** double-entry, balanced across the full lifecycle; unique external
  references rejected; refunds/reversals are compensating entries (append-only).
- **Reconciliation (new, Phase 3.4):** `make reconcile` /
  `stripe_connect.reconcile_all()` compares internal records + ledger against Stripe and
  flags mismatches (captured vs PI `amount_received`, transfer/reversal state, refunded
  ≤ captured, the fee identity, ledger balance). A test injects a divergence and
  confirms it is **detected**.

## Phase 5 — Security & authorization

Server-computed amounts only (browser sets nothing financial); manual-capture
authorization verified server-side before execution; per-object authorization + IDOR
checks (a buyer/seller cannot read another's transaction; non-admins cannot list all
payments); admin financial actions require a reason + audit; signed webhooks over the
raw body, at-most-once; secrets from env; no card data through Petabyte;
`payout_providers.screen()` fails closed in live mode.

## Phase 6 — Load / concurrency

Concurrency is proven for the money-critical paths (reservation race, capture, transfer)
with real threads against the app, on SQLite and PostgreSQL. A dedicated k6/Locust HTTP
load harness is **not** included (noted gap); the invariant that matters under load —
**no duplicate money movement** — is asserted directly. All operations run against the
Stripe test-mode fake; **no live Stripe calls are possible** under any load.

## Phase 7 — Final validation

- Stripe strictly test mode everywhere; live mode hard-fails. ✅
- No live keys in repo, CI, or environment. ✅
- No real money movement possible (fake gateway offline; live guard). ✅
- Ledger and Stripe (test) data consistent; reconciliation passes and detects tamper. ✅

## Test results after fixes

`stripe_test.py`: **68 PASS** (was 54; +5 test-mode enforcement, +1 duplicate-refund,
+5 concurrency/reconciliation, +2 misc) on **SQLite and PostgreSQL**. All other suites
remain green. Commands: `make test-postgres`, `make stripe-test`, `make reconcile`,
`make stripe-demo`.

## Residual risks (unchanged from PRODUCTION_PAYMENT_CHECKLIST.md)

Live-Stripe-account items (Connect enablement, country/currency support, MoR/tax/dispute
liability), live-mode processing-fee capture, a scheduled reconciler service, KYC/AML
provider, publicly reachable webhook endpoint, and the buyer Stripe Elements front-end
remain to be done with real credentials — documented, not bypassed.
