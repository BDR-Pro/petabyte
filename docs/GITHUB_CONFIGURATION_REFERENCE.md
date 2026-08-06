# GitHub configuration reference

> **Generated** by `scripts/generate_config_docs.py` from `config/github_configuration_manifest.yaml`. Do not hand-edit — re-run the generator. The manifest is the single source of truth.

GitHub is the source of truth for deployment configuration. Non-sensitive values are **GitHub Variables**; credentials/keys/tokens/passwords are **GitHub Secrets**. At deploy time GitHub Actions resolves these and generates the server env file — nothing long-lived is hand-maintained on the server.

Set them under **Settings → Secrets and variables → Actions** (repository level), or per **Environment** (test / staging / production) for environment-specific values and protection rules.

Scope legend: **platform** = API server · **gpu** = seller GPU node agent · **deployment** = GitHub Actions → server (never written into the server runtime env).

## Variables (non-sensitive) (104)

| Name | Required | Scope | Default | Example | Used by | Validation | Production notes |
|---|---|---|---|---|---|---|---|
| `ADMIN_USERS` | no | platform | `info@petabyte.market` | `info@petabyte.market` | api/main.py | — | Comma-separated admin usernames/emails. |
| `ALLOWED_ORIGINS` | no | platform | *(empty)* | `…` | api/main.py | format: csv_or_empty | CORS origins — empty (same-origin) is the safe default; never '*' in prod. |
| `AUTO_SETTLE_ON_RESULT` | no | platform | `true` | `true` | api/main.py | format: bool; one of: true / false | — |
| `AWS_REFERENCE_PRICE` | no | platform | `12.29` | `12.29` | api/db.py, api/main.py | format: float | — |
| `AWS_REGION` | no | platform | `us-east-1` | `us-east-1` | api/notify_providers.py | — | — |
| `BACKUP_RESCHEDULE_GRACE_S` | no | platform | `900` | `900` | api/db.py | — | — |
| `BASE_DOMAIN`<br>`aka APP_DOMAIN` | no | platform | `petabyte.market` | `petabyte.market` | api/main.py | format: hostname | Public application domain. |
| `BIND` | no | platform | `127.0.0.1:8000` | `127.0.0.1:8000` | api/deploy/gunicorn_conf.py | — | gunicorn bind address; keep 127.0.0.1 behind nginx (never public). |
| `CAL_BOOKING_URL` | no | platform | *(empty)* | `…` | api/main.py | — | — |
| `CIRCLE_API` | no | platform | `https://api.circle.com/v1` | `https://api.circle.com/v1` | api/payout_providers.py | — | — |
| `DEFAULT_LANDING_VIDEO_ID` | no | platform | `UUSWYaxboDA` | `UUSWYaxboDA` | api/main.py | — | — |
| `EMAIL_FROM` | no | platform | `no-reply@petabyte.market` | `no-reply@petabyte.market` | api/notify_providers.py | — | — |
| `EMAIL_PROVIDER` | no | platform | `mailgun` | `mailgun` | api/notify_providers.py | one of: mailgun / ses / sendgrid / postmark | Notification email provider. |
| `EMAIL_TOKEN_TTL_MIN` | no | platform | `15` | `15` | api/db.py | format: int | — |
| `ENABLE_ELASTIC` | no | platform | `true` | `true` | — | format: bool; one of: true / false | Enable the Elastic logging stack (deploy/monitoring). (reserved: standardized in GitHub config). |
| `ENABLE_GRAFANA` | no | platform | `true` | `true` | — | format: bool; one of: true / false | Enable Grafana dashboards. (reserved: standardized in GitHub config). |
| `ENABLE_OTEL` | no | platform | `true` | `true` | — | format: bool; one of: true / false | Enable OpenTelemetry tracing. (reserved: standardized in GitHub config). |
| `ENABLE_PROMETHEUS` | no | platform | `true` | `true` | — | format: bool; one of: true / false | Enable Prometheus metrics scraping. (reserved: standardized in GitHub config). |
| `ENABLE_SENTRY` | no | platform | `false` | `false` | — | format: bool; one of: true / false | Enable Sentry error reporting (also needs SENTRY_DSN). (reserved: standardized in GitHub config). |
| `ENVIRONMENT`<br>`aka APP_ENV` | no | platform | `development` | `development` | api/main.py, api/stripe_gateway.py | one of: development / test / staging / production | Must be 'production' in prod; never leave stubs enabled. |
| `GEOIP_DB` | no | platform | *(empty)* | `…` | api/utils.py | — | — |
| `GEOIP_STUB` | no | platform | `true` | `true` | api/utils.py | format: bool; one of: true / false | GeoIP stub. |
| `GOOGLE_OAUTH_STUB` | no | platform | `false` | `false` | api/main.py | format: bool; one of: true / false | Google sign-in stub — MUST be false in production. |
| `GOOGLE_REDIRECT_URI` | no | platform | `https://petabyte.market/auth/google/callback` | `https://petabyte.market/auth/google/callback` | api/main.py | format: url | Google OAuth redirect URI. |
| `GPU_COUNT` | no | gpu | `1` | `1` | agent/provision.py | format: int | Manual GPU count override. |
| `GPU_METRICS_INTERVAL` | no | gpu | `10` | `10` | GPU node agent | format: int | Seconds between GPU metrics samples (agent/telemetry). (reserved: standardized in GitHub config). |
| `GPU_MODEL` | no | gpu | *(empty)* | `…` | agent/provision.py | — | Manual GPU model override when nvidia-smi is absent. |
| `HEARTBEAT_INTERVAL` | no | gpu | `15` | `15` | agent/task_fetcher.py | format: int | Seconds between node heartbeats (a.k.a. GPU_HEARTBEAT_INTERVAL). |
| `HEARTBEAT_TIMEOUT_S` | no | platform | `60` | `60` | api/db.py | format: int | Seconds before a silent node is reaped. |
| `IDLE_MINING` | no | gpu | `false` | `false` | agent/task_fetcher.py | format: bool | Enable idle NiceHash mining when no paid job is running. |
| `JOB_POLL_INTERVAL` | no | gpu | `5` | `5` | agent/task_fetcher.py | format: int | Seconds between /jobs/next polls. |
| `LEGACY_KEYS_FULL_ACCESS` | no | platform | `false` | `false` | api/main.py | format: bool; one of: true / false | Legacy scopeless-key escape hatch — MUST be false in production. |
| `LOG_LEVEL` | no | platform | `info` | `info` | api/deploy/gunicorn_conf.py | one of: debug / info / warning / error / critical / DEBUG / INFO / WARNING / ERROR / CRITICAL | Log verbosity. |
| `MAILCHIMP_AUDIENCE_ID` | no | platform | *(empty)* | `…` | api/main.py | — | — |
| `MAILGUN_DOMAIN` | no | platform | `petabyte.market` | `petabyte.market` | api/email_service.py | — | — |
| `MAILGUN_NEWSLETTER_DOMAIN` | no | platform | `news.petabyte.market` | `news.petabyte.market` | api/main.py | format: hostname | Mailgun sending subdomain for the newsletter (e.g. news.petabyte.market). Reuses MAILGUN_API_KEY. |
| `MAX_CONCURRENT_GPU_JOBS` | no | gpu | `1` | `1` | GPU node agent | format: int | Max concurrent paid jobs per GPU node (must stay bounded). (reserved: standardized in GitHub config). |
| `MAX_HOURS` | no | gpu | `24` | `24` | agent/provision.py | format: int | Max rentable hours offered. |
| `MIN_REPUTATION` | no | platform | `50` | `50` | api/db.py | format: int | — |
| `NB_CELL_TIMEOUT` | no | gpu | `120` | `120` | agent/notebook.py | format: int | Per-cell notebook timeout (s). |
| `NB_MAX_OUTPUT` | no | gpu | `1000000` | `1000000` | agent/notebook.py | format: int | Max notebook output bytes. |
| `NB_TIMEOUT` | no | gpu | `600` | `600` | agent/notebook.py | format: int | Notebook job hard timeout (s) — must stay bounded. |
| `NEWSLETTER_FROM` | no | platform | `updates@petabyte.market` | `updates@petabyte.market` | api/main.py | format: email_or_empty | From address campaigns are sent as (e.g. updates@petabyte.market). |
| `NEWSLETTER_LIST_ADDRESS` | no | platform | `newsletter@news.petabyte.market` | `newsletter@news.petabyte.market` | api/main.py | format: email_or_empty | Mailgun mailing-list address signups are added to (e.g. newsletter@news.petabyte.market). |
| `NEWSLETTER_PROVIDER` | no | platform | `mailgun` | `mailgun` | api/main.py | one of: mailgun / mailchimp / none | Newsletter backend. 'mailgun' adds signups to a Mailgun mailing list; 'mailchimp' uses the legacy audience; 'none' shows the honest 'not wired up' message. |
| `NEWSLETTER_REPLY_TO` | no | platform | `info@petabyte.market` | `info@petabyte.market` | api/main.py | format: email_or_empty | Reply-To for campaigns; a Mailgun Route forwards replies here (e.g. info@petabyte.market). |
| `NICEHASH_ADDRESS` | no | gpu | *(empty)* | `…` | agent/task_fetcher.py | — | NiceHash payout address for idle mining (shared across nodes). |
| `NICEHASH_API` | no | platform | `https://api2.nicehash.com` | `https://api2.nicehash.com` | api/nicehash.py | — | — |
| `NICEHASH_IMAGE` | no | gpu | `nicehash/nicehashminer:latest` | `nicehash/nicehashminer:latest` | agent/task_fetcher.py | — | Docker image for the idle NiceHash miner. |
| `NICEHASH_STUB` | no | platform | `true` | `true` | api/nicehash.py | format: bool; one of: true / false | NiceHash stub. |
| `NICEHASH_TAKE_RATE` | no | platform | `0.10` | `0.10` | api/tools/idle_reconcile.py | format: float | Platform commission on idle-mining revenue (idle_reconcile tool). |
| `NOTIFY_STUB` | no | platform | `true` | `true` | api/main.py, api/notify_providers.py | format: bool; one of: true / false | Email/notify stub — false to actually send. |
| `PAYMENTS_LIVE_ENABLED` | no | platform | `false` | `false` | api/db.py, api/main.py, api/stripe_gateway.py | format: bool; one of: true / false | Live requires PAYMENTS_LIVE_ENABLED=true AND STRIPE_ALLOW_LIVE=true AND ENVIRONMENT=production AND live keys. |
| `PAYMENTS_MODE` | no | platform | `sandbox` | `sandbox` | api/db.py, api/main.py | one of: sandbox / test / live | Payment mode label. |
| `PAYOUT_CAPABILITIES_PATH` | no | platform | *(empty)* | `…` | api/payout_capabilities.py | — | — |
| `PAYOUT_COOLING_OFF_H` | no | platform | `24` | `24` | api/db.py, api/stripe_connect.py | format: int | — |
| `PAYOUT_HOLD_DAYS` | no | platform | `14` | `14` | api/stripe_connect.py | format: int | Earnings risk-hold before biweekly payout. |
| `PAYOUT_HOLD_ON_REPORT` | no | platform | `true` | `true` | api/main.py | format: bool; one of: true / false | — |
| `PAYOUT_STUB` | no | platform | `true` | `true` | api/main.py, api/payout_providers.py | format: bool; one of: true / false | Payout provider stub. |
| `PETABYTE_API_URL` | **yes** | gpu | `https://petabyte.market` | `https://petabyte.market` | agent/attest_node.py, agent/provision.py, agent/task_fetcher.py, agent/ui.py, api/cli/petabyte.py, gateway/gateway.py | format: url | Public Petabyte API base URL the agent talks to. |
| `PETABYTE_SPEC_ID` | **yes** | gpu | *(empty)* | `60` | agent/task_fetcher.py, agent/ui.py | format: int | The spec id this node serves. |
| `PETABYTE_UPDATE_INTERVAL_S` | no | gpu | `3600` | `3600` | GPU node agent | format: int | Agent self-update check interval (s). |
| `PETABYTE_UPDATE_REPO` | no | gpu | *(empty)* | `…` | GPU node agent | — | Agent self-update source repo (optional). |
| `PLATFORM_AUTH_MARGIN_BPS` | no | platform | `2000` | `2000` | — | — | — |
| `PLATFORM_COMMISSION_BPS` | no | platform | *(empty)* | `…` | — | — | — |
| `PLATFORM_CURRENCY`<br>`aka DEFAULT_CURRENCY` | no | platform | `usd` | `usd` | api/pricing.py | — | Platform settlement currency. |
| `PLATFORM_DEFAULT_COUNTRY` | no | platform | `US` | `US` | api/stripe_connect.py | — | — |
| `PLATFORM_FIXED_FEE_MINOR` | no | platform | `0` | `0` | — | — | — |
| `PLATFORM_MAX_DURATION_S` | no | platform | `86400` | `86400` | — | — | — |
| `PLATFORM_MIN_CHARGE_MINOR` | no | platform | `50` | `50` | — | — | — |
| `PLATFORM_TAKE_RATE` | no | platform | `0.10` | `0.10` | api/db.py, api/pricing.py | format: float | — |
| `PRICE_PER_HOUR` | no | gpu | *(empty)* | `0.10` | agent/provision.py | format: float | Seller's offered price per GPU-hour (USD). |
| `PROVIDER` | no | gpu | *(empty)* | `…` | agent/provision.py | — | Provider/node display name (defaults to the machine hostname). |
| `PUBLIC_BASE_URL`<br>`aka APP_URL` | no | platform | *(empty)* | `https://…` | api/main.py | format: url_or_empty | Public base URL for building share/reset links. |
| `REAPER_DISABLED` | no | platform | `true` | `true` | api/main.py, api/stripe_demo.py | format: bool; one of: true / false | Keep true: the dedicated reaper service does the reaping. |
| `REAPER_INTERVAL_S` | no | platform | `20` | `20` | api/main.py, api/tools/reaper.py | format: int | — |
| `REFERRAL_MONTHLY_CAP` | no | platform | `25` | `25` | api/db.py | — | — |
| `REFERRAL_REWARD_USD` | no | platform | `20` | `20` | api/db.py | — | — |
| `S3_BUCKET` | no | platform | *(empty)* | `…` | api/utils.py | — | — |
| `S3_ENDPOINT` | no | platform | *(empty)* | `…` | api/utils.py | — | — |
| `S3_REGION` | no | platform | `us-east-1` | `us-east-1` | api/utils.py | — | — |
| `S3_SSE` | no | platform | `AES256` | `AES256` | api/utils.py | — | — |
| `S3_STUB` | no | platform | `true` | `true` | api/main.py, api/utils.py | format: bool; one of: true / false | S3 stub. |
| `SANCTIONS_SCREEN_PROVIDER` | no | platform | *(empty)* | `…` | api/payout_providers.py | — | — |
| `SANDBOX_IMAGE` | no | gpu | `python:3.12-slim` | `python:3.12-slim` | agent/notebook.py | — | Container image for the notebook sandbox. |
| `SELLER_AUDIT_SAMPLE_RATE` | no | platform | `0.25` | `0.25` | api/seller_audit.py | format: float | — |
| `SELLER_FRAUD_PENALTY` | no | platform | `40` | `40` | api/seller_audit.py | format: int | — |
| `STRIPE_ALLOW_LIVE` | no | platform | `false` | `false` | api/stripe_gateway.py | format: bool; one of: true / false | Second live gate; live keys refused unless true. |
| `STRIPE_API_VERSION` | no | platform | *(empty)* | `…` | api/stripe_gateway.py | — | — |
| `STRIPE_GATEWAY` | no | platform | `fake` | `fake` | api/main.py, api/stripe_demo.py, api/stripe_gateway.py | one of: fake / real | 'real' uses the Stripe SDK; anything else = in-process fake (tests only). |
| `STRIPE_MODE` | no | platform | `test` | `test` | api/stripe_gateway.py | one of: test / live | Declared Stripe mode; must match key prefixes. |
| `TEE_MEASUREMENT_ALLOWLIST` | no | platform | *(empty)* | `…` | api/utils.py | — | — |
| `TREMENDOUS_API` | no | platform | `https://api.tremendous.com/api/v2` | `https://api.tremendous.com/api/v2` | api/payout_providers.py | — | — |
| `TRUSTED_PROXIES` | no | platform | `127.0.0.1,::1` | `127.0.0.1,::1` | api/main.py | — | Reverse-proxy IPs trusted for X-Forwarded-For — never widen to spoofable. |
| `UNITS` | no | gpu | `1` | `1` | agent/provision.py | format: int | Identical rentable units on this node. |
| `USDC_CHAIN` | no | platform | `MATIC` | `MATIC` | api/payout_providers.py | — | — |
| `VRAM_GB` | no | gpu | *(empty)* | `60` | agent/provision.py | format: int | Manual VRAM override (GB). |
| `WALLET_MAX_TOPUP_MINOR` | no | platform | `500000` | `500000` | api/wallet_funding.py | format: int | — |
| `WALLET_MIN_TOPUP_MINOR` | no | platform | `500` | `500` | api/wallet_funding.py | format: int | — |
| `WEB_CONCURRENCY` | no | platform | `2` | `2` | api/deploy/gunicorn_conf.py | — | — |
| `WG_APPLY` | no | platform | `false` | `false` | api/utils.py | format: bool; one of: true / false | Apply WireGuard config. |
| `WG_ENDPOINT` | no | platform | *(empty)* | `…` | api/utils.py | — | — |
| `WG_INTERFACE` | no | platform | `wg0` | `wg0` | api/utils.py | — | — |
| `WG_PUBLIC_KEY` | no | platform | *(empty)* | `…` | api/utils.py | — | — |

## Secrets (credentials — never printed, no defaults) (34)

| Name | Required | Scope | Default | Example | Used by | Validation | Production notes |
|---|---|---|---|---|---|---|---|
| `AWS_ACCESS_KEY_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | — | — | — |
| `AWS_SECRET_ACCESS_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | — | — | — |
| `CAL_WEBHOOK_SECRET` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `CIRCLE_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |
| `CIRCLE_WALLET_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |
| `DATABASE_URL` | **yes** | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/alembic/env.py, api/db.py | format: url | SQLAlchemy database URL (Postgres in prod). |
| `DEPLOY_SSH_KEY` | **yes** | deployment | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | GitHub Actions deploy | — | Private SSH key GitHub Actions uses to deploy to the server. |
| `DROPLET_HOST` | **yes** | deployment | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | GitHub Actions deploy | — | Deploy target host (IP/DNS). |
| `DROPLET_USER` | **yes** | deployment | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | GitHub Actions deploy | — | Deploy SSH user. |
| `GATEWAY_TOKEN` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py, gateway/gateway.py | — | — |
| `GOOGLE_CLIENT_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `GOOGLE_CLIENT_SECRET` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `MAILCHIMP_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `MAILGUN_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/email_service.py, api/main.py | — | — |
| `NICEHASH_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/nicehash.py | — | — |
| `NICEHASH_API_SECRET` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/nicehash.py | — | — |
| `NICEHASH_ORG_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/nicehash.py | — | — |
| `PAYMENT_WEBHOOK_SECRET` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `PETABYTE_AGENT_KEY` | no | gpu | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | agent/crypto.py, agent/provision.py | — | Path to the node's Ed25519 signing key (attestation + signed results). |
| `PETABYTE_API_JWT` | no | gpu | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | agent/attest_node.py | — | Seller JWT (owner of the spec) used during node attestation/enrollment. |
| `PETABYTE_API_KEY` | **yes** | gpu | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | agent/provision.py, agent/task_fetcher.py, agent/ui.py | — | Encrypted node API key (X-API-KEY) minted at /create_api_key. |
| `POSTMARK_TOKEN` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/notify_providers.py | — | — |
| `SECRET_KEY` | **yes** | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/auth.py, api/main.py, api/stripe_demo.py | — | — |
| `SENDGRID_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/notify_providers.py | — | — |
| `SENTRY_DSN` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `SERVER_PRIVATE_KEY` | **yes** | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/audit_js.py, api/stripe_demo.py, api/utils.py | — | — |
| `STRIPE_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |
| `STRIPE_PUBLISHABLE_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py, api/stripe_gateway.py, api/wallet_funding.py | — | — |
| `STRIPE_SECRET_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/stripe_gateway.py | — | — |
| `STRIPE_WEBHOOK_SECRET` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/main.py | — | — |
| `TEE_TRUSTED_ROOT` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/utils.py | — | — |
| `TREMENDOUS_API_KEY` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |
| `TREMENDOUS_FUNDING_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |
| `TREMENDOUS_PRODUCT_ID` | no | platform | **NO DEFAULT** (secret) | `<set in GitHub Secrets>` | api/payout_providers.py | — | — |

---

**Safety defaults (never permissive):** live payments, auth-bypass stubs, disabled webhook verification, public DB/Redis, wildcard CORS, debug in prod, the fake payment gateway, unsigned seller comms, disabled TLS, unbounded job runtime, and unbounded upload size all default to the SAFE value. Production validation (`scripts/validate_github_configuration.py --env-name production`) refuses to deploy if any of them is left permissive.

## Environments

Use GitHub **Environments** to hold environment-specific config and protection rules. The deploy validates against `${{ vars.ENVIRONMENT || 'development' }}`:

- **test / staging** — production-grade infra on TEST money: `STRIPE_MODE=test`, `PAYMENTS_LIVE_ENABLED=false`, test keys only. A live key here is rejected.
- **production** — live money: `ENVIRONMENT=production`, `STRIPE_MODE=live`, `PAYMENTS_LIVE_ENABLED=true`, `STRIPE_ALLOW_LIVE=true`, `STRIPE_GATEWAY=real`, live keys + webhook secret, all stubs off, https URLs. Add environment protection (required reviewers) so a live deploy is a deliberate act.

## Rollout & emergency overrides

- **Rollout gate.** The deploy writes the server env from GitHub config only when the repository Variable `DEPLOY_CONFIG_FROM_GITHUB=true`. Until then the preflight is advisory and deploys stay code-only (the server env is untouched), so you can enter all Secrets first. Before flipping the gate, do the one-time migration of `SECRET_KEY`, `SERVER_PRIVATE_KEY`, and `DATABASE_URL` — copy the CURRENT values from `/etc/lumaris/lumaris.env` into GitHub Secrets so live sessions, encrypted API keys, and the database keep working.
- **Emergency change, right now.** You may edit `/etc/lumaris/lumaris.env` on the server and `sudo systemctl restart lumaris-api lumaris-reaper`. This is **temporary**: with the gate on, the next deploy regenerates the file from GitHub and your hand-edit is lost. Make it permanent by setting the value in GitHub, then deploy.
- **Pause GitHub-managed env.** Set `DEPLOY_CONFIG_FROM_GITHUB=false` (or unset it) to revert to code-only deploys that never touch the server env.
