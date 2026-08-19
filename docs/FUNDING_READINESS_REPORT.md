# Funding-Readiness Report

> ⚠️ **Superseded (2026-08-18).** This is a 2026-08-04 point-in-time snapshot kept for the
> audit trail. For current state read [`../FUNDING_READINESS.md`](../FUNDING_READINESS.md)
> (§0 "Current status" + §5 "Execution status") — most gaps flagged below have since been
> closed in code.

Branch: `claude/petabyte-funding-readiness-fun2q6` · Date: 2026-08-04
Companion docs: [AUDIT](FUNDING_READINESS_AUDIT.md) · [PLAN](FUNDING_READINESS_PLAN.md) ·
[INVESTOR_TECHNICAL_BRIEF](INVESTOR_TECHNICAL_BRIEF.md) · [PRODUCTION_GAPS](PRODUCTION_GAPS.md)

---

## 1. Executive summary

**What was weak.** The core (double-entry ledger, escrow, attestation, concurrency
safety) was genuinely strong and tested — but it was wrapped in things that would fail
a five-minute demo and a diligence read: no demo mode at all; two UIs invented fake
"−95% vs cloud" discounts by dividing every GPU by the H100 price; dead `/gpu/undefined`
links on the landing and pricing pages; the production maintenance worker crashed on
startup (so nothing settled/expired/reaped in prod); routing selected a node but could
not explain or record *why*; trust was binary and risked reading the Ed25519 stub as
TEE; the investor page claimed confidential compute and payout rails were "fully built";
the payout sanctions screen approved everything even in live mode; a buyer-controlled
field reached a root `tar`; the agent auto-updater was unsigned root code; and the whole
due-diligence document set was missing.

**What changed (and why it improves fundability).**
- **Deterministic demo (`make investor-demo`)** — turns "trust me" into "watch this":
  the entire seller→buyer→settlement loop runs locally with clearly-labelled data and a
  reset, no paid credentials.
- **Explainable, auditable routing** — the platform now selects a node, shows the
  reason, and stores the full decision. This is the "routing layer, not a listing site"
  claim made real and inspectable.
- **Honest savings, trust ladder, and marketing copy** — every number an investor
  spot-checks now holds up; nothing claims more than the code delivers. Candor is the
  single fastest way to pass technical diligence.
- **P0 correctness/security** — maintenance worker starts; screen fails closed; traversal
  blocked; VM stubs refuse instead of faking success; updates opt-in + signature hook.
- **Investor/ops metrics + admin incident view** — real unit economics (GMV, 10% take,
  utilization, buyer savings, completion rate) from live queries, demo/real separated,
  plus an operator "why isn't this settling" panel.
- **Diligence document set + honest gap list** — a technical adviser can now understand
  the system, the threat model, the metrics, and exactly what is not built yet.

**The strongest five-minute demo now shows** (see §6): normalized verified supply →
seller diagnostics → a buyer booking with a written routing justification and a stored
audit record → job lifecycle → escrowed settlement on a balanced double-entry ledger →
seller earnings → live marketplace metrics with a persistent "Demo data" badge → an
admin audit trail and kill switch.

**What remains incomplete** (fully enumerated in PRODUCTION_GAPS): live payments,
KYC/AML, vendor TEE attestation, the payout-worker scheduler in deploy, a squashed
Alembic baseline, TLS-by-default, the release-signing pipeline, container-escape
verification on real hardware, and unifying the drifted desktop agent.

---

## 2. Change log (substantial changes)

### Honest savings + broken links + auditable routing (`35f6c84`)
- **Files:** `main.py`, `pages.py`, `static_dashboard.py`, `router.py`, `db.py`, `smoke_test.py`.
- **Before:** savings = price ÷ single H100 reference (fake discounts for consumer GPUs);
  hero/pricing linked `/gpu/{spec_id}` → `/gpu/undefined`; `/solve`,`/launch` returned a
  generic reason and stored nothing.
- **After:** per-GPU-class `cloud_reference` (shows nothing when no fair match); links use
  the public handle; `RoutingDecision` records intent + every candidate's factor scores +
  selection + plain-language explanation; deterministic tie-breaks; `/routing/decisions/{id}`.
- **Tests:** +14 (explanation wording, determinism, persistence, booking linkage, owner-only).
- **Investor rationale:** removes the worst credibility hit and makes the routing story evidence-backed.

### P0/P1 security + trust + honesty (`1fc5bc9`)
- **Files:** `tools/reaper.py`, `payout_providers.py`, `main.py`, `db.py`, `lumaris_agent/vm.py`,
  `lumaris_agent/update.sh`,`install.sh`,`uninstall.sh`,`petabyte-agent.service`,
  `installers/uninstall.sh`, `gateway.py` contract, `pages.py`, `static_dashboard.py`,
  `template.env`, `smoke_test.py`; removed 6 stale root docs + committed log + dead unit.
- **Before:** reaper crashed on import (no prod maintenance); `screen()` returned True in
  live mode; unvalidated `volume` → root `tar`; VM stubs returned fake "running"; unsigned
  root auto-update on by default; uninstall left the updater running; binary trust; "fully
  built" overclaims.
- **After:** reaper imports; screen fails closed (needs `SANCTIONS_SCREEN_PROVIDER`); volume
  slug-validated; VM backends `raise NotImplementedError`; auto-update opt-in + pinned-key
  verify hook + hardened unit; uninstall fixed; `trust_level_for` ladder; corrected copy.
- **Tests:** +trust ladder, +traversal rejection, +screen fail-closed.
- **Investor rationale:** closes the data-loss and RCE-class risks a technical reviewer will find, and stops overclaiming.

### Demo mode + metrics (`b72090a`)
- **Files:** new `demo.py`, `demo_run.sh`, `demo_test.py`, `metrics.py`, `Makefile`;
  `db.py` (`is_demo`), `main.py` (`/metrics/*`), `pages.py` (metrics page + badge).
- **Before:** no way to demonstrate the product; 5 hero numbers only.
- **After:** one-command deterministic demo through the real API with a simulated
  (non-executing) agent; `/metrics/overview` (scope + date range) and a dashboard.
- **Tests:** `demo_test.py` — 21 checks (labelling, ledger conservation, demo/real
  separation, take-rate == fee, gmv == fee + payouts, reset determinism, no fake TEE).
- **Investor rationale:** the single highest-value deliverable — a repeatable demo and real unit economics.

### CI hardening (`f7517c6`) & docs (`1f63848`) & admin incidents (`7447c87`)
- CI: demo suite, clean-DB migration check (SQLite+PG), ruff lint, pip-audit, gitleaks.
- Docs: ARCHITECTURE, DATA_FLOW, THREAT_MODEL, METRIC_DEFINITIONS, PRODUCTION_GAPS,
  ROADMAP, PRODUCT_DEMO, INVESTOR_TECHNICAL_BRIEF; honest README/RUNBOOK.
- `/admin/incidents`: failed/stalled transactions + reasons, with a UI panel (+4 tests).

---

## 3. Verification report (exact commands + results)

All from a clean checkout, Python 3.11, PostgreSQL 16.

| Step | Command | Result |
|---|---|---|
| Install | `pip install -r lumaris_api/requirements.txt` | OK (cryptography pin resolved) |
| Schema from clean DB (SQLite) | `python -c "import db; db.init_db()"` | `sqlite schema OK` |
| Schema from clean DB (Postgres) | same with `DATABASE_URL=postgresql+…` | `postgres schema OK` |
| Full suite, both engines | `cd lumaris_api && bash run_tests.sh --postgres` | **all suites passed** |
| — smoke (SQLite/PG) | `python smoke_test.py` | 499 PASS, 0 FAIL |
| — adversarial (money under races) | `python adversarial_test.py` | 14 passed, 0 failed |
| — gateway (NAT + failover) | `python tunnel_test.py` | 12 passed, 0 failed |
| — postgres-only invariants | `python postgres_test.py` | 12 passed, 0 failed |
| Frontend contract | `python audit_frontend.py` | 0 broken contracts |
| Rendered JS parses | `python audit_js.py` | 90 blocks, 0 broken |
| Demo honesty suite | `python demo_test.py` | 21 PASS, ALL DEMO CHECKS PASSED |
| Security: prod boot gate | `ENVIRONMENT=production PAYMENTS_MODE=sandbox … TestClient(app)` | **gate fired**: "Refusing to start in production with unsafe settings: PAYOUT_STUB, PAYMENTS_MODE=sandbox" |
| Security: payout screen | in `demo_test`/`smoke` | passes in stub; **fails closed** in live with no provider |
| Security: input validation | in `smoke` | traversal `volume` → 422 |
| Demo startup | `make investor-demo` | `healthz 200`; `/metrics?scope=demo` → GMV 12.27, take 10.0%, ledger balanced, 4 active sellers |
| Demo reset | `make demo-reset` (×2) | identical: 5 nodes, 6 bookings (4 completed, 1 running, 1 failed) — deterministic |

---

## 4. Honest readiness score (0–10)

| Dimension | Score | Evidence |
|---|---|---|
| Product clarity | **8** | One coherent thesis expressed in working software; nav, marketplace, routing explanation, metrics all consistent; overclaims removed. |
| Demo readiness | **9** | `make investor-demo` runs the full loop deterministically, labelled, with reset; 21-check honesty suite; verified healthy. |
| Buyer experience | **7** | Browse → routed booking with written justification → job → result → receipt; polished states. Real payments still sandbox. |
| Seller experience | **7** | One-command onboarding, attestation, `/seller/dashboard` blocker diagnosis + earnings. Payout worker not yet scheduled in deploy. |
| Transaction integrity | **9** | Double-entry ledger refusing unbalanced writes; exact NUMERIC on PG; idempotent booking/settlement; money conservation proven under concurrency. |
| Security | **6** | Strong authz/isolation/ledger and honest trust; but unsigned-update pipeline, container-escape, KYC/AML, TLS-by-default still open (documented). |
| Reliability | **7** | Heartbeat/reaper/failover/refund, retryable jobs, kill switch, incident view; reaper-in-prod fixed. Recovery-after-restart not yet a test. |
| Deployment | **5** | Solid idempotent provisioning + boot gate; but ungated auto-deploy, plaintext-until-certbot, secrets-in-argv, stale Alembic remain. |
| Technical documentation | **9** | Full DD set grounded in code, with an explicit gap list; README/RUNBOOK corrected. |
| Investor DD readiness | **8** | Audit table, threat model, metric definitions, honest gaps, and a demo; the hard questions have written answers (§7). |

---

## 5. Remaining risks (by milestone)

- **Before investor demos:** none blocking — the demo, honesty fixes, and P0s are done.
  Re-run `make demo-reset` before each session.
- **Before pilots:** payout-worker scheduler; TLS-by-default; deploy test-gate + health
  check; squashed Alembic baseline; `/login` app-level rate limit.
- **Before handling real money:** KYC/AML + sanctions provider; live payment provider
  review (Stripe `construct_event`); secrets out of argv; rotate historically-committed secrets.
- **Before executing untrusted customer workloads (at scale):** signed agent release
  pipeline; container-escape verification on real Docker+GPU; template/render isolation
  parity with the notebook path; unify the drifted desktop agent.
- **Before enterprise deployment:** vendor TEE attestation; SOC 2 track; data-residency
  beyond IP GeoIP; gateway auth+TLS; multi-region control-plane HA; dedicated scheduler.
- **Longer-term roadmap:** cross-provider routing adapters; demand-based auto-pricing;
  the data/routing moat (see ROADMAP).

---

## 6. Recommended five-minute demonstration script

See [PRODUCT_DEMO.md](PRODUCT_DEMO.md) for the full version. Summary beat-sheet:
`make investor-demo` → **/marketplace** (normalized supply, honest per-class savings,
"Demo data" badge) → **/gpu/{id}** (trust level + evidence + limits, no fake TEE) →
**/seller/dashboard** (why a seller is/ isn't earning) → **buyer launch** (routing
explanation + `/routing/decisions/{id}` audit) → **job → result → settlement** (ledger)
→ **/metrics** (GMV, 10% take, savings, utilization, completion; ledger-balanced signal;
demo/real toggle) → **/admin** (append-only audit log + kill switch + incidents).

---

## 7. The 15 hardest investor objections — answered from implemented evidence

1. **"Is this just a listings website?"** No — the buyer states intent, the platform
   selects and *justifies* the node and records the decision (`router.py`,
   `RoutingDecision`, `/routing/decisions/{id}`). The routing/verification/settlement
   layer is the product.
2. **"Your savings numbers are marketing fiction."** They're per-GPU-class, like-for-like,
   and suppressed when no fair reference exists (`cloud_reference_for`, METRIC_DEFINITIONS);
   the demo's buyer-savings figure is computed from settled bookings.
3. **"Can you actually move money correctly?"** Double-entry ledger that refuses unbalanced
   writes, exact `NUMERIC(20,8)`, idempotent settlement; `adversarial_test.py` proves
   `deposits == wallets + earnings + platform + escrow` under concurrent abuse, on Postgres.
4. **"What stops overselling a node under load?"** Atomic capacity reservation + guarded
   debits; the smoke/adversarial suites run parallel bookings and confirm exactly the
   capacity succeeds, never negative, never oversold.
5. **"Is the 'confidential computing' real?"** No, and we don't claim it is — the TEE
   verifier is a documented Ed25519 stub; the UI shows "CC pilot" and the detail page
   states the limit explicitly (`trust_level_for`, THREAT_MODEL, stub.md #3).
6. **"You run strangers' code on strangers' machines — how is that safe?"** Docker only,
   no host fallback; notebook path uses `--network none`, cap-drop, read-only, limits,
   timeout; buyer input that reaches a root `tar` is slug-validated. Escape-resistance on
   real hardware is an explicit open item (PRODUCTION_GAPS/THREAT_MODEL).
7. **"What's your take rate and is it real?"** 10% (`PLATFORM_TAKE_RATE`), deducted from
   the rental and split in the ledger; the metrics dashboard shows effective take rate =
   platform_revenue/GMV, which equals 10% on demo data.
8. **"Show me traction."** We show none we don't have — every seeded figure carries a
   "Demo data" badge and `scope=real` returns zero. That honesty is the point.
9. **"Does the demo actually work or is it a mock?"** `make investor-demo` runs the real
   API end-to-end deterministically; the agent is real (holds its key, signs results) but
   returns a labelled SIMULATED body — no buyer code executes in the demo.
10. **"What happens when a node dies mid-job?"** Reaper fails the VM over to another node
    at the *same stable address* (proven in `tunnel_test.py`) or refunds the escrow;
    there's a per-VM event timeline.
11. **"Are your payouts to sellers safe/compliant?"** State machine with reversal on
    failure, 24h destination cooling-off, and a sanctions screen that **fails closed** in
    live mode. Real KYC/AML integration is a documented pre-real-money gap.
12. **"Can a compromised server take over every seller machine?"** That was the top risk:
    the unsigned auto-updater is now opt-in, the unit is hardened, and `update.sh` has a
    pinned-key verify hook. A full signing pipeline is required before fleet-wide
    auto-update (PRODUCTION_GAPS) — stated, not hidden.
13. **"Do your migrations work from scratch?"** The app builds its schema from
    `create_all` + `_ensure_columns`; a CI job proves it comes up on empty SQLite and
    Postgres. Alembic is stale; a squashed baseline is on the roadmap (disclosed).
14. **"Where's the moat?"** Honestly, not yet — it accrues with volume in normalized
    supply telemetry, reliability history, the routing-decision corpus (already recorded
    per placement), and pricing/routing models trained on it (INVESTOR_TECHNICAL_BRIEF,
    ROADMAP). We don't claim one we don't have.
15. **"What breaks first if you 10× tomorrow?"** Deployment and ops: ungated auto-deploy,
    plaintext-until-certbot, no payout scheduler, single-node control plane. All listed in
    PRODUCTION_GAPS with the milestone each must be fixed by; none affect ledger correctness.
