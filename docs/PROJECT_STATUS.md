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

_Last updated: 2026-08-18._

## Observability Droplet repair — IMPLEMENTATION READY — WAITING FOR OPERATOR EXECUTION

The observability stack at `/opt/petabyte-observability` came up with five failures. A
complete, idempotent repair is implemented in the repo; it must be run **on the Droplet**
(the sandbox cannot SSH there).

**Failure summary → root cause → fix:**

| # | Failure | Root cause | Fix (in `docs/scripts/repair_observability_stack.sh`) |
|---|---|---|---|
| 1 | Grafana: `yaml: line 27: found unknown escape character` | A regex `\s` inside a **double-quoted** YAML scalar in the datasource file; YAML double quotes reject `\s`. | Emit datasources with regexes **single-quoted** (no escape processing). Also fixed in the repo reference `observability/grafana/provisioning/datasources/datasources.yaml`. |
| 2 | OTel Collector: `service.telemetry.metrics has invalid key: address` | `…metrics.address` was deprecated (v0.111) and **removed** (v0.123). | Use the supported `readers:` (OTel-SDK) syntax. Also fixed in `observability/otel-collector/config.yaml`. |
| 3 | Tempo: `field ingester/compactor not found in type app.Config` | Config didn't match the running binary schema. | Write a canonical single-binary + local-storage config valid for the pinned **Tempo 2.6.1** (WAL/blocks on the existing volume). |
| 4 | Loki: health check may be inaccurate | Wrong/early probe. | Probe `/ready` with a `start_period`. |
| 5 | Redis: health check uses the password incorrectly | Password not read from container env. | `redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping` from the container env — never printed. |

**Also:** removes all `:latest` tags and pins Grafana 11.4.0, Prometheus v2.54.1, Loki
3.2.1, Tempo 2.6.1, OTel Collector-contrib 0.111.0, Redis 7.4.1, Node Exporter v1.8.2,
cAdvisor v0.49.1. Backs up first, **preserves .env + volumes + credentials**, validates
(`docker compose config` + `otelcol validate`), restarts, verifies every service, prints a
sanitized summary, and supports `--rollback`.

**Repair implementation status:** ✅ script + embedded copy/paste (`docs/DEBUG_EXCHANGE.md`
#2) + run/verify/rollback instructions (`docs/TESTING_EXCHANGE.md`) complete and
syntax-validated in CI-style checks.
**Remaining manual action:** run it on the Droplet and paste the output back. The stack is
**not** declared fixed until that output confirms all services healthy.

## Config architecture — ONE `ENV_VARS` bundle (current)

Non-secret configuration is now a **single** GitHub Repository Variable, `ENV_VARS`
(`KEY=value;` pairs, newlines allowed), instead of 100+ individual Variables. Secrets stay
individual. Only two standalone Variables remain: `ENV_VARS` + `DEPLOY_CONFIG_FROM_GITHUB`.

- **Parser** (`scripts/env_vars.py`): treats `ENV_VARS` as DATA (never eval/sourced) —
  semicolon split, trims, ignores blanks, splits on the FIRST `=` (so `DATABASE_OPTIONS=sslmode=require`
  works), validates names `^[A-Z_][A-Z0-9_]*$`, rejects duplicates / null bytes /
  newline-injected values / entries without `=`; shell syntax is kept as literal text.
- **Secret guard**: a secret-classified key inside `ENV_VARS` FAILS the deploy with a
  sanitized error (value never printed), backed by a defense-in-depth denylist.
- **Precedence**: GitHub Secrets > `ENV_VARS` > manifest defaults (secret & non-secret keys
  are disjoint, so no ambiguity). Legacy individual Variables are detected and reported —
  the two sources are never silently mixed.
- **Generation**: the deploy generates `/etc/lumaris/lumaris.env` from `ENV_VARS` + Secrets
  + safe defaults, atomically (temp → validate → 0600 → install), backs up the old env,
  restarts, health-checks, and **auto-rolls-back** on failure. Never printed in logs.
- **Dev tool** (`scripts/env_bundle.py`): `generate` (paste-ready bundle, never secrets),
  `validate`, `list`.
- Docs: `docs/GITHUB_MANUAL_SETUP_CHECKLIST.md` is now "paste one Variable + set Secrets".

## Shipped (in the current branch)

| Area | State | Where |
|---|---|---|
| **GitHub config = ONE ENV_VARS bundle** | ✅ parser + secret-guard + precedence + env_bundle tool + atomic deploy w/ rollback | `scripts/env_vars.py`, `scripts/env_bundle.py`, `scripts/config_context.py` |
| **GitHub config = source of truth** | ✅ manifest + validator + drift + docs + deploy-env generator (scope-filtered) + gated deploy | `scripts/*config*`, `config/github_configuration_manifest.yaml`, `docs/GITHUB_*` |
| **Observability core** | ✅ correlation context, JSON logs + redaction, OTel traces, bounded Prometheus metrics, degrade-safe | `lumaris_api/observability.py` |
| **API/settlement instrumentation** | ✅ request spans+metrics, transaction spine, capture/commission/transfer events, protected `/internal/metrics`, `/health/observability` | `lumaris_api/main.py`, `stripe_connect.py` |
| **Seller (ephemeral) observability** | ✅ heartbeat/reconnect/gpu-detect/suspicious events, offline-on-reap, scrape-time marketplace gauges (sellers online/offline/stale, GPUs by model/country, GPU-hours) — outbound-only, no seller scrape | `main.py`, `observability.py`, `docs/SELLER_OBSERVABILITY.md` |
| **Seller agent telemetry** | ✅ JSON logs, optional OTLP, W3C context from job envelope, heartbeat/job events, degrade-safe | `lumaris_agent/agent_telemetry.py`, `task_fetcher.py` |
| **Redis (optional)** | ✅ instrumented, circuit-broken, wired to rate-limit with in-process fallback | `lumaris_api/redis_client.py` |
| **Dashboards / alerts / collector** | ✅ 9 provisioned Grafana dashboards, alert+recording rules, OTel Collector + Prometheus configs | `observability/` |
| **Runbooks + docs** | ✅ 12 runbooks + 11 observability docs (audit, architecture, data dictionary, trace guide, investor demo, seller observability) | `docs/`, `docs/runbooks/` |
| **Newsletter (Mailgun)** | ✅ `news.petabyte.market`, From `updates@`, replies → `info@` | `main.py`, checklist |
| **Payments** | ✅ Stripe Connect (separate charges + transfers, manual capture, `construct_event` webhook verify), minor-unit ledger accounts (`*:minor`), processing-fee leg, `charge.refunded` clawback, TEST-mode-only live-money fail-safes | `stripe_connect.py`, `stripe_gateway.py`, `db.py` |
| **Deploy safety** | ✅ prod deploy gated on the full test suite (`workflow_call`), payout systemd timer, TLS-by-default (certbot), env backup + `/healthz` gate + auto-rollback | `.github/workflows/deploy-server.yml`, `lumaris_api/deploy/` |
| **Schema / migrations** | ✅ squashed Alembic baseline + CI up/down `migration` job on Postgres; `init_db()` backstop | `lumaris_api/alembic/`, `docs/MIGRATIONS.md` |
| **Auth hardening** | ✅ JWT `jti` + revocation denylist + entropy gate, signed double-submit CSRF, optional TOTP 2FA, app-level `/login` limiter | `lumaris_api/auth.py`, `deps.py`, `totp.py` |
| **Agent isolation + signed updates** | ✅ `_isolation_flags` on every buyer container (+gVisor), Ed25519 fail-closed update channel, hardened loopback-only desktop agent | `lumaris_agent/`, `desktop-app/`, `scripts/sign_release.py` |
| **CLI / distribution** | ✅ `petabyte-client` pip package (`petabyte launch`, bundled model hub, MIT), PyPI release workflow, browser desktop-release upload (`/admin/desktop`), download-first `/install`, `/faq` | `pyproject.toml`, `lumaris_api/cli/`, `.github/workflows/release-cli.yml` |
| **Disaster recovery** | ✅ S3 DB backups + restore drill + freshness gauge/alert | `lumaris_api/backup.py`, `scripts/backup_database.py`, `docs/BACKUP_RUNBOOK.md` |
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
