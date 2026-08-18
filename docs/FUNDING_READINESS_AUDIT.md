# Funding-Readiness Audit — Petabyte

> ⚠️ **Superseded (2026-08-18).** This is a 2026-08-04 point-in-time snapshot kept for the
> audit trail. For current state read [`../FUNDING_READINESS.md`](../FUNDING_READINESS.md)
> (§0 "Current status" + §5 "Execution status") — most gaps flagged below have since been
> closed in code.

Date: 2026-08-04 · Branch: `claude/petabyte-funding-readiness-fun2q6`
Method: full source read of `lumaris_api/`, `lumaris_agent/`, `desktop-app/`,
`lumaris_gateway/`, `.github/workflows/`, `deploy/`, `docs/`; baseline test runs on
SQLite **and** PostgreSQL 16; verification of documentation claims against code.
Companion: [`FUNDING_READINESS_PLAN.md`](FUNDING_READINESS_PLAN.md).

## Baseline (recorded before any change)

| Suite | Engine | Result |
|---|---|---|
| `smoke_test.py` | SQLite | PASS |
| `adversarial_test.py` (money conservation under races) | SQLite | PASS (14/14) |
| `lumaris_gateway/tunnel_test.py` | SQLite | PASS (12/12) |
| `smoke + adversarial + postgres_test.py` | PostgreSQL 16 | PASS (incl. 12 PG-only invariants) |

The core is genuinely strong: a double-entry ledger that refuses unbalanced writes,
escrow booking with atomic capacity reservation and idempotency keys, exact NUMERIC
money verified in Postgres, heartbeat/reaper/refund, Ed25519 attestation (honestly
documented as non-TEE), and concurrency tests proving no oversell and money
conservation under parallel writers. The weaknesses were in production wiring,
seller-side safety, honesty of a few claims, demonstrability, and the diligence
document set.

## Severity key

- **P0** — blocks a credible demo, or a serious security / data-loss risk.
- **P1** — materially affects investor confidence or the core transaction.
- **P2** — useful polish or future scalability.
- **Remove/defer** — not valuable at this funding stage.

## Findings

| # | Finding | Evidence (file:line) | Sev | Investor impact | Recommended action | Effort | Implemented | Verification |
|---|---|---|---|---|---|---|---|---|
| 1 | Production maintenance service could not start: `tools/reaper.py` had no `sys.path` insert, so `import db` fails under its systemd unit. With `REAPER_DISABLED=true` on web workers, **nothing reaped dead nodes, expired VMs, settled bookings, or repriced** in prod. | `tools/reaper.py:6`; `deploy/lumaris-reaper.service:11`; `main.py` maintenance gate | P0 | A "silent money bug" — the platform silently stops settling. Fatal in diligence. | Add the `sys.path.insert` its siblings already have; verify import. | S | ✅ Yes | `python tools/reaper.py` imports; verified in-repo |
| 2 | Marketplace + `/app` computed "vs cloud" savings by dividing **every** GPU's price by the single H100 reference, manufacturing fake ~90%+ discounts for consumer cards — the exact thing `cloud_reference_for()` exists to prevent. | `pages.py` marketplace JS; `static_dashboard.py:277`; `main.py cloud_reference_for` | P0 | An investor spot-checking a 4090 "−95% vs cloud" instantly distrusts every number. | Use the per-class `cloud_reference` per spec; show nothing when no fair comparison exists. | S | ✅ Yes | smoke suite; visual on `/marketplace` |
| 3 | Landing hero + pricing page linked `/gpu/{s.spec_id}` but the endpoint returns `id` (public handle) → dead links to `/gpu/undefined`. | `pages.py` hero + pricing JS | P0 | Dead links on the two most-visited pages read as an unfinished product. | Use `s.id` (the public handle the API returns). | S | ✅ Yes | links resolve on `/` and `/pricing` |
| 4 | No demo mode at all — no seed, reset, or one-command run. A demo required hand-registering users and faking heartbeats. | (absence) | P0 | Cannot deliver a repeatable five-minute investor demo. | `make investor-demo` / `demo-reset`: deps check → schema → labelled seed → health check → print accounts+URLs → serve. | L | ✅ Yes | `make investor-demo`; `demo_test.py` (21 checks) |
| 5 | Routing (`/solve`, `/launch`) selected a node but persisted nothing and returned only a generic reason. | `router.py`; `main.py` solve/launch (pre-change) | P1 | The core "intelligent routing" story had no evidence a buyer or reviewer could inspect. | `routing_decisions` table records intent + every candidate's factor scores + selection + a plain-language explanation; deterministic tie-breaks; owner/admin-readable audit. | M | ✅ Yes | smoke suite (determinism, persistence, explanation, owner-only) |
| 6 | Unsigned agent auto-update runs as **root** every 6h (Linux `update.sh`; desktop `updater.py` size-check only). A compromised server/GitHub account = root RCE on every seller machine. | `lumaris_agent/update.sh`; `petabyte-agent-update.timer`; `desktop-app/updater.py:86`; `release-desktop.yml` (no signing) | P0 | The single finding a security-minded technical DD reviewer will find themselves. | Make auto-update **opt-in** (`PETABYTE_AUTO_UPDATE=true`); add pinned-key signature verification hook in `update.sh`; harden the systemd unit; document signing as required before fleet-wide auto-update. | M | ✅ Partial (opt-in + verify hook + hardening; full release-signing pipeline documented as a gap) | `PRODUCTION_GAPS.md`; install.sh reads env; update.sh verify block |
| 7 | Payout sanctions/AML `screen()` returned `True` on **both** stub and live paths — approving every real destination unscreened. | `payout_providers.py:18` (pre-change) | P1 | Compliance red flag for anyone who will handle real money. | Fail **closed** in live mode; require `SANCTIONS_SCREEN_PROVIDER`. | S | ✅ Yes | smoke test (`screen()` fail-closed) |
| 8 | Buyer-controlled task `volume` interpolated into a root `tar` on seller machines with no validation → path traversal. | `main.py` TaskCreateModel; `lumaris_agent/task_fetcher.py` tar path | P1 | Untrusted-input-to-root on a stranger's machine — the platform's core risk. | Strict slug validation server-side; reject traversal. | S | ✅ Yes | smoke test (traversal rejected 422) |
| 9 | Agent VM backends returned **fabricated** `status:"running"` with hardcoded `192.168.1.100/101`; Docker-absent path returned a fake "simulated" VM reported as a real result. | `lumaris_agent/vm.py:350-374`, `:274` (pre-change) | P1 | A VM rental that reports success for a machine that doesn't exist is a live-fire hazard and a diligence trap. | `raise NotImplementedError`; Docker-absent path refuses so escrow is refunded. | S | ✅ Yes | agent `vm.py` parses; code review |
| 10 | Trust was binary (attested or not); the Ed25519 stub risked being read as hardware/TEE attestation. | `db.py`; `main.py` spec responses (pre-change) | P1 | Overstating verification is the fastest way to lose technical credibility. | Honest ladder: `self_reported → agent_verified → benchmark_verified`, awarded only on evidence; TEE shown as "CC pilot", never vendor-attested. | M | ✅ Yes | smoke tests; `/marketplace/specs` `trust` field |
| 11 | No investor/ops metrics beyond 5 hero numbers; no date range, no demo/real separation, no unit economics. | `main.py marketplace_stats` (pre-change) | P1 | No evidence surface for GMV, take rate, utilization, savings, reliability. | `/metrics/overview` (scope=all\|demo\|real, date range) + `/metrics` dashboard, all from real queries, with a persistent "Demo data" badge and definitions. | L | ✅ Yes | `demo_test.py` metric consistency; `/metrics` page |
| 12 | Investor page asserted "Infrastructure — **fully built**" over Confidential Compute (Firecracker/QEMU), automated payout rails, and idle-fallback — all stubbed. Mislabeled "169 security assertions". | `pages.py` INVESTORS_HTML (pre-change) | P1 | Directly contradicts the repo's own `/security` page and `docs/isolation-roadmap.md`. | Split into built-vs-roadmap; move stubs to a labelled roadmap column; correct assertion count; relabel. | S | ✅ Yes | visual on `/investors`; JS audit |
| 13 | Templates page documented `POST /deployments {image:...}` — a call the endpoint rejects — contradicting the deliberate managed-templates-only security posture. | `pages.py` TEMPLATES_HTML (pre-change) | P1 | A copy-paste example that 422s reads as broken; also undercuts a good security decision. | Replace with a working `{template:...}` example; state the curated-only posture. | S | ✅ Yes | smoke test updated; JS audit |
| 14 | `uninstall.sh` (both copies) removed the wrong path (`/opt/petabyte` vs installed `/opt/petabyte-agent`) and left the **root auto-update timer running** after "uninstall". | `lumaris_agent/uninstall.sh`; `installers/uninstall.sh` (pre-change) | P1 | For a consumer-facing "run it on your PC" pitch, an uninstall that doesn't uninstall is reputationally severe. | Fix paths; disable+remove update units. | S | ✅ Yes | script review |
| 15 | Gateway resolved a VM handle by reading `node_id`/`spec_id`, but `/vm/{id}/route` returned `current_spec_id` → every gateway resolution returned empty; the test hid it with a DB resolver. | `gateway.py:140`; `main.py` route response (pre-change) | P1 | The stable-address VM-failover product didn't work end-to-end over HTTP. | Return `node_id` in the route response. | S | ✅ Yes | code review; contract aligned |
| 16 | Alembic migrations are stale: 3 `add_column` migrations, **zero `create_table`** for 30 models; `alembic upgrade head` from a clean DB fails. Schema truth is `create_all()` + hand-rolled `_ensure_columns()`. | `alembic/versions/*`; `db.py init_db/_ensure_columns` | P1 | A DD reviewer running the documented migration path hits an immediate failure. | Document `create_all` as the current mechanism + clean-DB schema check in CI; squashed baseline migration is the follow-up. | M | ✅ Partial (clean-DB build check in `make verify` + `PRODUCTION_GAPS.md`; squashed baseline deferred) | `make verify` builds schema from empty DB |
| 17 | CI ran tests only — no lint, dependency-vuln scan, secret scan, migration/clean-DB check, or agent import test. | `.github/workflows/tests.yml` | P1 | "Evidence of execution" is thin without these gates. | Add ruff, pip-audit, gitleaks, clean-DB schema build, demo suite to CI. | M | ✅ Yes | `.github/workflows/tests.yml` new jobs |
| 18 | `desktop-app/` is a drifted fork of `lumaris_agent/` (≈585 lines duplicated); the **shipped** Windows fork lost isolation flags and binds containers to all interfaces. | `desktop-app/task_fetcher.py:222` vs `lumaris_agent/task_fetcher.py:267` | P1 | The same bug fixed twice; the shipped copy is the less-safe one. | Extract a shared core package after signing lands. | L | ⛔ Deferred (documented) | `PRODUCTION_GAPS.md` |
| 19 | Withdrawals: `request_payout` queues, but `process_payouts` has no timer/cron/unit → queued payouts never send. | `tools/payout_worker.py`; deploy units | P1 | "Automated payout rails" don't run on a schedule in prod. | Ship `lumaris-payout.service` + `.timer`; install in `deploy.sh`. | M | ⛔ Deferred (documented; sandbox-labelled today) | `PRODUCTION_GAPS.md` |
| 20 | Root and `docs/` held 6 duplicate/stale docs (root `RLtest.md`/`stub.md` carried wrong assertion counts); committed empty agent log; dead duplicate root reaper unit. | root `*.md` vs `docs/*.md`; `lumaris_agent/petabyte_agent.log`; `deploy/lumaris-reaper.service` | P2 | Drifted docs and stray artifacts read as sloppiness in DD. | Delete root duplicates (keep `docs/`); remove log + dead unit. | S | ✅ Yes | `ls`; git status |
| 21 | Missing DD document set: no ARCHITECTURE, DATA_FLOW, THREAT_MODEL, METRIC_DEFINITIONS, PRODUCTION_GAPS, ROADMAP, PRODUCT_DEMO, INVESTOR_TECHNICAL_BRIEF. | `docs/` (absence) | P1 | A technical adviser has nothing to read. | Author all of them, grounded in verified code. | L | ✅ Yes | files under `docs/` |
| 22 | `nicehash.py` puts BTC/day into a USD field and swallows all errors; reachable only from an unscheduled script. | `nicehash.py:54,57` | Remove/defer | Distraction from the core marketplace story. | Leave stubbed + documented; do not surface as revenue. | S | ⛔ Deferred (documented) | `PRODUCTION_GAPS.md` |
| 23 | `deploy-server.yml` auto-deploys prod on every push to `main` with no test gate/concurrency/health-check; SSH key written before `chmod`; `StrictHostKeyChecking=no`. | `.github/workflows/deploy-server.yml` | P1 | Ungated prod deploys are an operational risk. | Gate on tests, add concurrency + `/healthz` gate, harden key handling. | M | ⛔ Deferred (documented) | `PRODUCTION_GAPS.md` |
| 24 | Fresh deploys serve prod over plaintext HTTP until a human runs certbot; secrets pass through `env $(xargs)` (visible in `ps`). | `nginx-lumaris.conf:7`; `deploy.sh:206` | P1 | Cleartext JWTs in the startup window; local secret exposure. | TLS-by-default in `deploy.sh`; `EnvironmentFile`/`set -a` instead of argv. | M | ⛔ Deferred (documented) | `PRODUCTION_GAPS.md` |

## What is now demonstrable that wasn't

The full loop runs from one command (`make investor-demo`) against a clean local
DB with no paid credentials: five verified demo sellers across regions and trust
levels, three funded buyers, explainable routing with a stored audit record, jobs
progressing through states, settlement into a balanced double-entry ledger, seller
earnings, a live metrics dashboard with a persistent "Demo data" badge, and an admin
audit trail — every seeded entity labelled and separable from real data.
