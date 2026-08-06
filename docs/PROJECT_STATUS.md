# Project status

Living status of Petabyte's investor-readiness work. Newest facts on top; older sections
are marked **COMPLETE** rather than deleted. Engineering priority order (from the project
brief): reliability → correctness → security → financial integrity → observability →
automation → performance → UI polish.

> **Sandbox boundary (why some steps are handed off):** Claude Code runs in a sandbox that
> **cannot** SSH to the DigitalOcean buyer/seller Droplets or reach the observability
> server. Anything requiring those machines is turned into copy/paste commands in
> `docs/TESTING_EXCHANGE.md` (routine actions) and `docs/DEBUG_EXCHANGE.md` (diagnostics),
> with ready-to-run scripts in `docs/scripts/`. Implementation never stops on a sandbox
> limit — it continues and leaves you the exact commands.

_Last updated: 2026-08-06._

## Shipped (in the current branch)

| Area | State | Where |
|---|---|---|
| **GitHub config = source of truth** | ✅ manifest + validator + drift + docs + deploy-env generator (scope-filtered) + gated deploy | `scripts/*config*`, `config/github_configuration_manifest.yaml`, `docs/GITHUB_*` |
| **Observability core** | ✅ correlation context, JSON logs + redaction, OTel traces, bounded Prometheus metrics, degrade-safe | `lumaris_api/observability.py` |
| **API/settlement instrumentation** | ✅ request spans+metrics, transaction spine, capture/commission/transfer events, protected `/internal/metrics`, `/health/observability` | `lumaris_api/main.py`, `stripe_connect.py` |
| **Seller (ephemeral) observability** | ✅ heartbeat/reconnect/gpu-detect/suspicious events, offline-on-reap, scrape-time marketplace gauges (sellers online/offline/stale, GPUs by model/country, GPU-hours) — outbound-only, no seller scrape | `main.py`, `observability.py`, `docs/SELLER_OBSERVABILITY.md` |
| **Seller agent telemetry** | ✅ JSON logs, optional OTLP, W3C context from job envelope, heartbeat/job events, degrade-safe | `lumaris_agent/agent_telemetry.py`, `task_fetcher.py` |
| **Redis (optional)** | ✅ instrumented, circuit-broken, wired to rate-limit with in-process fallback | `lumaris_api/redis_client.py` |
| **Dashboards / alerts / collector** | ✅ 9 provisioned Grafana dashboards, alert+recording rules, OTel Collector + Prometheus configs | `observability/` |
| **Runbooks + docs** | ✅ 12 runbooks + 11 observability docs (audit, architecture, data dictionary, trace guide, investor demo, seller observability) | `docs/`, `docs/runbooks/` |
| **Newsletter (Mailgun)** | ✅ `news.petabyte.market`, From `updates@`, replies → `info@` | `main.py`, checklist |
| **Payments** | ✅ Stripe TEST-mode only, live-money fail-safes, real test PaymentIntents, no simulated-success | `stripe_connect.py`, `stripe_gateway.py` |
| **Tests** | ✅ config + observability + smoke suites wired into `run_tests.sh` + CI | `lumaris_api/*_test.py`, `.github/workflows/tests.yml` |

## Pending / next (honest gaps)

- **Live verification on real infra** (⛔ sandbox): confirm telemetry LANDS in
  Tempo/Loki/Prometheus and a controlled error reaches Sentry — run the remote tier of
  `scripts/observability_smoke_test.py` from the deploy runner / a Droplet. See
  `docs/TESTING_EXCHANGE.md`.
- **Frontend/browser telemetry** (browser OTel + Sentry) — deliberate next phase; app is
  server-rendered today.
- **Deeper spans**: per-query DB (SQLAlchemy instrumentation), per-webhook, per-validation
  step, container/CUDA sub-steps on the agent.
- **Payout country coverage → 100**: grows only via real provider approvals + implemented
  rails (tracked, honestly red until real).
- **DEPLOY_CONFIG_FROM_GITHUB gate**: flip to `true` after entering all GitHub Secrets
  (incl. the one-time SECRET_KEY/SERVER_PRIVATE_KEY/DATABASE_URL migration) — see
  `docs/GITHUB_MANUAL_SETUP_CHECKLIST.md`.

## Canonical operator files (keep in sync every change)

- `docs/PROJECT_STATUS.md` — this file.
- `docs/TESTING_EXCHANGE.md` — copy/paste commands per machine (append-only).
- `docs/DEBUG_EXCHANGE.md` — numbered diagnostic requests (append-only).
- `docs/scripts/` — ready-to-run bash scripts (`set -Eeuo pipefail`, progress, diagnostics).
