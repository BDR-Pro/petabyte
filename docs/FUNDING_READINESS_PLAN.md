# Funding-Readiness Execution Plan

> ⚠️ **Superseded (2026-08-18).** This is a 2026-08-04 point-in-time snapshot kept for the
> audit trail. For current state read [`../FUNDING_READINESS.md`](../FUNDING_READINESS.md)
> (§0 "Current status" + §5 "Execution status") — most planned items below have since been
> executed.

Date: 2026-08-04 · Branch: `claude/petabyte-funding-readiness-fun2q6`
Companion document: [`FUNDING_READINESS_AUDIT.md`](FUNDING_READINESS_AUDIT.md) (findings + evidence).

## Baseline (verified before any change)

All existing suites pass on both engines, from a clean checkout:

| Suite | Engine | Result |
|---|---|---|
| `lumaris_api/smoke_test.py` (~208 assertions) | SQLite | PASS |
| `lumaris_api/adversarial_test.py` (14 checks: money conservation under races) | SQLite | PASS |
| `lumaris_gateway/tunnel_test.py` (12 checks: NAT traversal + failover) | SQLite | PASS |
| `run_tests.sh --postgres` (smoke + adversarial + 12 Postgres-only invariants) | PostgreSQL 16 | PASS |

What already genuinely works (verified in code + tests, not docs): double-entry
ledger with balance enforcement (`db.py::post`), escrow booking with atomic
capacity reservation and idempotency keys (`main.py::request_vm`), heartbeat +
reaper + refund-on-death, Ed25519 hardware attestation (honestly documented as
not-TEE in `stub.md`), payout state machine, org wallets, seller
blocker-diagnosis dashboard (`/seller/dashboard`), onboarding checklists
(`/onboarding`), admin console with kill switch and append-only audit log, and a
gateway with stable VM addresses across node failover.

## What blocks a credible investor demo today

1. **No demo mode at all.** No Makefile, no seed, no reset, no deterministic
   local run. An investor demo currently requires manually registering users and
   faking heartbeats by hand.
2. **Misleading savings math in two UIs.** `/marketplace` and `/app` divide every
   GPU's price by the H100 reference (`aws_reference`), manufacturing fake
   "−97%" savings for consumer cards — the exact failure `cloud_reference_for()`
   exists to prevent. The backend already returns a fair per-class
   `cloud_reference` per spec; the UI ignores it.
3. **Routing is not explainable or auditable.** `/solve` scores and selects but
   persists nothing and returns only a generic reason string.
4. **Metrics are thin.** `/marketplace/stats` returns 5 numbers; no date ranges,
   no GPU-hours, no take rate, no utilization, no demo/real separation.
5. **No due-diligence document set.** No ARCHITECTURE, THREAT_MODEL, DATA_FLOW,
   METRIC_DEFINITIONS, PRODUCTION_GAPS, ROADMAP, PRODUCT_DEMO, or investor brief.
6. **CI has no lint, dependency audit, secret scanning, or migration check**, and
   Alembic migrations are stale relative to the models (schema truth is
   `create_all` + `_ensure_columns`).

## Execution order

| # | Work item | Why this order |
|---|---|---|
| 1 | Fix misleading savings + broken `/gpu/{id}` hero links | Small, removes the worst "diligence lands here first" credibility hit |
| 2 | Routing decision records + buyer-visible explanation (`routing_decisions` table, `/solve` + `/launch` persist inputs/scores/selection; explanation shows VRAM fit, % vs next candidate, success rate) | Core differentiation story; needed before demo mode so the demo shows it |
| 3 | Trust-level ladder (`trust_level` computed from existing verified facts: `self_reported` → `agent_verified` → `benchmark_verified`; TEE stub explicitly NOT presented as hardware attestation) | Marketplace credibility; no new claims, only honest naming of existing state |
| 4 | Metrics: `/metrics/overview` with date range + demo/real separation, driven by ledger/booking queries | Feeds investor dashboard and demo narrative |
| 5 | Deterministic investor demo mode: `make investor-demo` / `make demo-reset` (dependency check → clean DB → schema → seed via the real HTTP API → simulated demo agent that heartbeats and completes jobs WITHOUT executing buyer code → health check → print URLs + accounts). All demo entities carry `is_demo` and display "Demo data"/"Simulated" badges | The single highest-value deliverable for a 5-minute demo |
| 6 | Demo test suite (`demo_test.py`): seeding, labelling, determinism, reset, metric separation | Rule: every new feature ships with tests |
| 7 | CI hardening: ruff lint, pip-audit, gitleaks secret scan, clean-database schema check, demo suite | Evidence of execution discipline |
| 8 | Repo hygiene: delete committed agent log, dedupe root/`docs/` duplicated md files, `.gitignore` fixes | Diligence hygiene |
| 9 | Documentation package: README, ARCHITECTURE, DATA_FLOW, THREAT_MODEL, METRIC_DEFINITIONS, PRODUCTION_GAPS, ROADMAP, PRODUCT_DEMO (5-minute script), INVESTOR_TECHNICAL_BRIEF | The diligence package itself |
| 10 | Final verification: full suites on both engines, demo start/reset, evidence record | Non-negotiable closing step |

## Deliberately deferred (documented in the audit, not built now)

- Unifying `desktop-app/` with `lumaris_agent/` (near-duplicate code) — refactor
  risk outweighs demo value this round; documented as P2.
- Real vendor TEE verification, live Stripe, KYC/AML — external dependencies;
  documented honestly in PRODUCTION_GAPS instead of being faked.
- NiceHash idle-mining polish — distraction from the core marketplace story;
  left as-is, opt-in, documented.

## Ground rules carried through every step

- No fabricated traction: seeded values always show a persistent "Demo data" badge.
- No weakening of auth, isolation, or money paths for demo convenience — the
  demo seeds through the same public API a real user hits.
- The simulated demo agent never executes buyer code; it returns clearly-labelled
  simulated output. Real execution still requires the real agent + Docker.
- Tests accompany every feature; nothing failing is deleted to go green.
