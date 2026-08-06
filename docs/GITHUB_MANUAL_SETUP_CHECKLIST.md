# GitHub manual setup checklist

> **Generated** by `scripts/generate_config_docs.py`. Work top to bottom. Create each **Variable** and **Secret** in GitHub under **Settings → Secrets and variables → Actions** (or per **Environment**). This list is complete — you should not need to search the repository.

Format below: Variables are shown as `NAME=default` (the value the app uses if you don't override it). Secrets are shown as `NAME=<what to put>` — **never** commit or paste a real secret into a file; only enter it in the GitHub Secrets UI.

After entering everything, the `configuration-preflight` CI job validates it and **fails the deploy** if anything required is missing or unsafe. A deploy applies the config by regenerating the server env and restarting the services (so every change takes effect on the next deploy).

Legend: 🔴 required · ⚪ optional (default is safe).

## 1. Platform (API server)

### Variables — platform

Non-sensitive server config. Override any line in GitHub Variables; leave the rest and the shown default is used.

```ini
ADMIN_USERS=info@petabyte.market   # optional: Comma-separated admin usernames/emails.
ALLOWED_ORIGINS=   # optional: CORS origins — empty (same-origin) is the safe default; never '*' in prod.
AUTO_SETTLE_ON_RESULT=true   # optional: 
AWS_REFERENCE_PRICE=12.29   # optional: 
AWS_REGION=us-east-1   # optional: 
BACKUP_RESCHEDULE_GRACE_S=900   # optional: 
BASE_DOMAIN=petabyte.market   # optional: Public application domain.
BIND=127.0.0.1:8000   # optional: gunicorn bind address; keep 127.0.0.1 behind nginx (never public).
CAL_BOOKING_URL=   # optional: 
CIRCLE_API=https://api.circle.com/v1   # optional: 
DEFAULT_LANDING_VIDEO_ID=UUSWYaxboDA   # optional: 
EMAIL_FROM=no-reply@petabyte.market   # optional: 
EMAIL_PROVIDER=mailgun   # optional: Notification email provider.
EMAIL_TOKEN_TTL_MIN=15   # optional: 
ENABLE_ELASTIC=true   # optional: Enable the Elastic logging stack (deploy/monitoring). (reserved: standardized in GitHub config).
ENABLE_GRAFANA=true   # optional: Enable Grafana dashboards. (reserved: standardized in GitHub config).
ENABLE_OTEL=true   # optional: Enable OpenTelemetry tracing. (reserved: standardized in GitHub config).
ENABLE_PROMETHEUS=true   # optional: Enable Prometheus metrics scraping. (reserved: standardized in GitHub config).
ENABLE_SENTRY=false   # optional: Enable Sentry error reporting (also needs SENTRY_DSN). (reserved: standardized in GitHub config).
ENVIRONMENT=development   # optional: Application environment. In production the app REFUSES to boot with any stub on.
GEOIP_DB=   # optional: 
GEOIP_STUB=true   # optional: GeoIP stub.
GOOGLE_OAUTH_STUB=false   # optional: Google sign-in stub — MUST be false in production.
GOOGLE_REDIRECT_URI=https://petabyte.market/auth/google/callback   # optional: Google OAuth redirect URI.
GRAFANA_ENABLED=true   # optional: 
HEARTBEAT_TIMEOUT_S=60   # optional: Seconds before a silent node is reaped.
LEGACY_KEYS_FULL_ACCESS=false   # optional: Legacy scopeless-key escape hatch — MUST be false in production.
LOG_FORMAT=json   # optional: Log format — json in all deployments.
LOG_LEVEL=info   # optional: Log verbosity.
LOG_REDACTION_ENABLED=true   # optional: Redact secrets/PII from logs. MUST be true in prod.
LOKI_ENABLED=true   # optional: 
MAILCHIMP_AUDIENCE_ID=   # optional: 
MAILGUN_DOMAIN=petabyte.market   # optional: 
MAILGUN_NEWSLETTER_DOMAIN=news.petabyte.market   # optional: Mailgun sending subdomain for the newsletter (e.g. news.petabyte.market). Reuses MAILGUN_API_KEY.
MIN_REPUTATION=50   # optional: 
NEWSLETTER_FROM=updates@petabyte.market   # optional: From address campaigns are sent as (e.g. updates@petabyte.market).
NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market   # optional: Mailgun mailing-list address signups are added to (e.g. newsletter@news.petabyte.market).
NEWSLETTER_PROVIDER=mailgun   # optional: Newsletter backend. 'mailgun' adds signups to a Mailgun mailing list; 'mailchimp' uses the legacy audience; 'none' shows the honest 'not wired up' message.
NEWSLETTER_REPLY_TO=info@petabyte.market   # optional: Reply-To for campaigns; a Mailgun Route forwards replies here (e.g. info@petabyte.market).
NICEHASH_API=https://api2.nicehash.com   # optional: 
NICEHASH_STUB=true   # optional: NiceHash stub.
NICEHASH_TAKE_RATE=0.10   # optional: Platform commission on idle-mining revenue (idle_reconcile tool).
NOTIFY_STUB=true   # optional: Email/notify stub — false to actually send.
OBSERVABILITY_BATCH_SIZE=512   # optional: OTLP export batch size.
OBSERVABILITY_ENABLED=true   # optional: Master switch for telemetry (logs/metrics/traces).
OBSERVABILITY_EXPORT_TIMEOUT_SECONDS=5   # optional: OTLP export timeout (bounded).
OBSERVABILITY_FAILURE_MODE=degrade   # optional: On export failure: 'degrade' keeps serving; 'strict' raises.
OBSERVABILITY_QUEUE_SIZE=2048   # optional: Bounded OTLP export queue size.
OTEL_ENABLED=true   # optional: Enable OpenTelemetry tracing export.
OTEL_EXPORTER_OTLP_ENDPOINT=   # optional: OTLP endpoint of the OpenTelemetry Collector (e.g. http://<obs>:4317). Blank -> tracing no-ops.
OTEL_EXPORTER_OTLP_PROTOCOL=grpc   # optional: OTLP transport to the Collector.
OTEL_LOGS_ENABLED=true   # optional: 
OTEL_METRICS_ENABLED=true   # optional: 
OTEL_SERVICE_NAME=petabyte-api   # optional: OTel service.name for the API (petabyte-api).
OTEL_SERVICE_NAMESPACE=petabyte   # optional: OTel service.namespace (petabyte).
OTEL_TRACE_SAMPLE_RATIO=1.0   # optional: Trace sample ratio (1.0 in test/pilot/investor demo).
PAYMENTS_LIVE_ENABLED=false   # optional: MASTER live-money switch. Must be false unless deliberately going live.
PAYMENTS_MODE=sandbox   # optional: Payment mode label.
PAYOUT_CAPABILITIES_PATH=   # optional: 
PAYOUT_COOLING_OFF_H=24   # optional: 
PAYOUT_HOLD_DAYS=14   # optional: Earnings risk-hold before biweekly payout.
PAYOUT_HOLD_ON_REPORT=true   # optional: 
PAYOUT_STUB=true   # optional: Payout provider stub.
PETABYTE_HOST_ROLE=   # optional: OTel resource attribute petabyte.host_role (e.g. api, worker).
PLATFORM_AUTH_MARGIN_BPS=2000   # optional: 
PLATFORM_COMMISSION_BPS=   # optional: 
PLATFORM_CURRENCY=usd   # optional: Platform settlement currency.
PLATFORM_DEFAULT_COUNTRY=US   # optional: 
PLATFORM_FIXED_FEE_MINOR=0   # optional: 
PLATFORM_MAX_DURATION_S=86400   # optional: 
PLATFORM_MIN_CHARGE_MINOR=50   # optional: 
PLATFORM_TAKE_RATE=0.10   # optional: 
PROMETHEUS_ENABLED=true   # optional: 
PROMETHEUS_METRICS_PATH=/internal/metrics   # optional: Protected Prometheus scrape path (default /internal/metrics).
PUBLIC_BASE_URL=   # optional: Public base URL for building share/reset links.
REAPER_DISABLED=true   # optional: Keep true: the dedicated reaper service does the reaping.
REAPER_INTERVAL_S=20   # optional: 
REDIS_ENABLED=false   # optional: Use Redis for rate-limit/idempotency/lock coordination (degrades to in-process when off/unavailable). Never the ledger.
REDIS_NAMESPACE=petabyte   # optional: Key namespace prefix for Redis (petabyte).
REFERRAL_MONTHLY_CAP=25   # optional: 
REFERRAL_REWARD_USD=20   # optional: 
S3_BUCKET=   # optional: 
S3_ENDPOINT=   # optional: 
S3_REGION=us-east-1   # optional: 
S3_SSE=AES256   # optional: 
S3_STUB=true   # optional: S3 stub.
SANCTIONS_SCREEN_PROVIDER=   # optional: 
SELLER_AUDIT_SAMPLE_RATE=0.25   # optional: 
SELLER_FRAUD_PENALTY=40   # optional: 
SENTRY_ENABLED=true   # optional: Enable Sentry (needs SENTRY_DSN).
SENTRY_MAX_BREADCRUMBS=30   # optional: 
SENTRY_PROFILES_SAMPLE_RATE=0.0   # optional: 
SENTRY_TRACES_SAMPLE_RATE=0.1   # optional: 
STRIPE_ALLOW_LIVE=false   # optional: Second live gate; live keys refused unless true.
STRIPE_API_VERSION=   # optional: 
STRIPE_GATEWAY=fake   # optional: 'real' uses the Stripe SDK; anything else = in-process fake (tests only).
STRIPE_MODE=test   # optional: Declared Stripe mode; must match key prefixes.
TEE_MEASUREMENT_ALLOWLIST=   # optional: 
TEMPO_ENABLED=true   # optional: 
TREMENDOUS_API=https://api.tremendous.com/api/v2   # optional: 
TRUSTED_PROXIES=127.0.0.1,::1   # optional: Reverse-proxy IPs trusted for X-Forwarded-For — never widen to spoofable.
USDC_CHAIN=MATIC   # optional: 
WALLET_MAX_TOPUP_MINOR=500000   # optional: 
WALLET_MIN_TOPUP_MINOR=500   # optional: 
WEB_CONCURRENCY=2   # optional: 
WG_APPLY=false   # optional: Apply WireGuard config.
WG_ENDPOINT=   # optional: 
WG_INTERFACE=wg0   # optional: 
WG_PUBLIC_KEY=   # optional: 
```

### Secrets — platform

Enter each in GitHub Secrets. Required ones (🔴) must be set before the first deploy — the preflight fails closed if they are missing.

- **`AWS_ACCESS_KEY_ID`** — ⚪ optional. AWS IAM user with S3 backup access.
- **`AWS_SECRET_ACCESS_KEY`** — ⚪ optional. AWS IAM user with S3 backup access (the matching secret).
- **`CAL_WEBHOOK_SECRET`** — ⚪ optional. Cal.com → the demo booking webhook's signing secret.
- **`CIRCLE_API_KEY`** — ⚪ optional. Circle dashboard (only if using USDC payouts).
- **`CIRCLE_WALLET_ID`** — ⚪ optional. Circle dashboard (only if using USDC payouts).
- **`DATABASE_URL`** — 🔴 required. postgresql+psycopg2://USER:PASS@HOST:5432/DB. One-time migration: read the current value from /etc/lumaris/lumaris.env on the server so sessions/data survive.
- **`GATEWAY_TOKEN`** — ⚪ optional. Generate: `openssl rand -hex 16` (VM gateway route resolution).
- **`GOOGLE_CLIENT_ID`** — ⚪ optional. Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 client.
- **`GOOGLE_CLIENT_SECRET`** — ⚪ optional. Google Cloud Console → the same OAuth client's secret.
- **`MAILCHIMP_API_KEY`** — ⚪ optional. Mailchimp → Account → Extras → API keys (only if NEWSLETTER_PROVIDER=mailchimp).
- **`MAILGUN_API_KEY`** — ⚪ optional. Mailgun → Settings → API Keys (a Sending API key). Also powers the newsletter.
- **`NICEHASH_API_KEY`** — ⚪ optional. NiceHash → API keys (only if using idle-mining fallback pricing).
- **`NICEHASH_API_SECRET`** — ⚪ optional. NiceHash → API keys (the matching secret).
- **`NICEHASH_ORG_ID`** — ⚪ optional. NiceHash → organization id.
- **`OTEL_EXPORTER_OTLP_HEADERS`** — ⚪ optional. See the reference doc.
- **`PAYMENT_WEBHOOK_SECRET`** — ⚪ optional. Stripe deposits webhook signing secret (whsec_…).
- **`POSTMARK_TOKEN`** — ⚪ optional. Postmark (only if EMAIL_PROVIDER=postmark).
- **`PROMETHEUS_METRICS_TOKEN`** — ⚪ optional. See the reference doc.
- **`REDIS_PASSWORD`** — ⚪ optional. See the reference doc.
- **`REDIS_URL`** — ⚪ optional. See the reference doc.
- **`SECRET_KEY`** — 🔴 required. Generate once: `openssl rand -hex 32`. Rotating it logs everyone out.
- **`SENDGRID_API_KEY`** — ⚪ optional. SendGrid (only if EMAIL_PROVIDER=sendgrid).
- **`SENTRY_DSN`** — ⚪ optional. Sentry → project → Settings → Client Keys (DSN).
- **`SERVER_PRIVATE_KEY`** — 🔴 required. Generate a Fernet key: `python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'`. Rotating it makes existing encrypted API keys undecryptable — migrate the current value.
- **`STRIPE_API_KEY`** — ⚪ optional. Legacy deposits key — same source as STRIPE_SECRET_KEY.
- **`STRIPE_PUBLISHABLE_KEY`** — ⚪ optional. Stripe Dashboard → API keys (pk_test_… / pk_live_…).
- **`STRIPE_SECRET_KEY`** — ⚪ optional. Stripe Dashboard → Developers → API keys. Use sk_test_… (test); only sk_live_… when deliberately going live.
- **`STRIPE_WEBHOOK_SECRET`** — ⚪ optional. Stripe Dashboard → Developers → Webhooks → signing secret (whsec_…), or `stripe listen`.
- **`TEE_TRUSTED_ROOT`** — ⚪ optional. Base64 vendor attestation root public key (confidential computing only).
- **`TREMENDOUS_API_KEY`** — ⚪ optional. Tremendous dashboard (only if using Tremendous payouts).
- **`TREMENDOUS_FUNDING_ID`** — ⚪ optional. Tremendous dashboard (funding source id).
- **`TREMENDOUS_PRODUCT_ID`** — ⚪ optional. Tremendous dashboard (product id).

## 2. Deployment (GitHub Actions → server)

These let the deploy workflow reach the server. They are **never** written into the server's runtime env.

### Secrets — deployment

- **`DEPLOY_SSH_KEY`** — 🔴 required. The PRIVATE SSH key authorized on the server (e.g. id_ed25519). Never commit it.
- **`DROPLET_HOST`** — 🔴 required. The API server's public IP or DNS name.
- **`DROPLET_USER`** — 🔴 required. The deploy SSH user on the server (e.g. root or a deploy user).

## 3. GPU node (seller agent)

Config for a seller's GPU machine running the agent. The GPU node **never** receives any platform secret (Stripe, DB, admin, signing key).

### Variables — GPU node

```ini
AGENT_TELEMETRY_ENABLED=true   # optional: Seller-agent telemetry export (degrade-safe if obs down).
GPU_COUNT=1   # optional: Manual GPU count override.
GPU_METRICS_ENABLED=true   # optional: Collect GPU metrics on the seller node (DCGM/NVML).
GPU_METRICS_INTERVAL=10   # optional: Seconds between GPU metrics samples (agent/telemetry). (reserved: standardized in GitHub config).
GPU_MODEL=   # optional: Manual GPU model override when nvidia-smi is absent.
HEARTBEAT_INTERVAL=15   # optional: Seconds between node heartbeats (a.k.a. GPU_HEARTBEAT_INTERVAL).
IDLE_MINING=false   # optional: Enable idle NiceHash mining when no paid job is running.
JOB_POLL_INTERVAL=5   # optional: Seconds between /jobs/next polls.
MAX_CONCURRENT_GPU_JOBS=1   # optional: Max concurrent paid jobs per GPU node (must stay bounded). (reserved: standardized in GitHub config).
MAX_HOURS=24   # optional: Max rentable hours offered.
NB_CELL_TIMEOUT=120   # optional: Per-cell notebook timeout (s).
NB_MAX_OUTPUT=1000000   # optional: Max notebook output bytes.
NB_TIMEOUT=600   # optional: Notebook job hard timeout (s) — must stay bounded.
NICEHASH_ADDRESS=   # optional: NiceHash payout address for idle mining (shared across nodes).
NICEHASH_IMAGE=nicehash/nicehashminer:latest   # optional: Docker image for the idle NiceHash miner.
PETABYTE_API_URL=https://petabyte.market   # REQUIRED: Public Petabyte API base URL the agent talks to.
PETABYTE_SPEC_ID=   # REQUIRED: The spec id this node serves.
PETABYTE_UPDATE_INTERVAL_S=3600   # optional: Agent self-update check interval (s).
PETABYTE_UPDATE_REPO=   # optional: Agent self-update source repo (optional).
PRICE_PER_HOUR=   # optional: Seller's offered price per GPU-hour (USD).
PROVIDER=   # optional: Provider/node display name (defaults to the machine hostname).
SANDBOX_IMAGE=python:3.12-slim   # optional: Container image for the notebook sandbox.
UNITS=1   # optional: Identical rentable units on this node.
VRAM_GB=   # optional: Manual VRAM override (GB).
```

### Secrets — GPU node

- **`PETABYTE_AGENT_KEY`** — ⚪ optional. Path to the node's Ed25519 signing key (attestation + signed results).
- **`PETABYTE_API_JWT`** — ⚪ optional. The seller's login JWT (spec owner) — used once during node attestation.
- **`PETABYTE_API_KEY`** — 🔴 required. Minted per GPU node: POST /create_api_key (set on the node, not the platform).

## 4. Newsletter (Mailgun) — one-time Mailgun setup

The newsletter runs on the Mailgun sending subdomain **news.petabyte.market**, sends **From `updates@petabyte.market`**, and forwards replies to **`info@petabyte.market`**. The signup form adds subscribers to a Mailgun mailing list. Configure in this order:

1. In Mailgun, add + verify the sending domain `news.petabyte.market` (DNS: SPF, DKIM, and a tracking CNAME).
2. Create a **mailing list** on that domain (e.g. `newsletter@news.petabyte.market`) and set its From name/address to `updates@petabyte.market`.
3. Add a Mailgun **Route** that forwards replies to that list/address on to `info@petabyte.market`.
4. Set the GitHub Variables `NEWSLETTER_PROVIDER=mailgun`, `MAILGUN_NEWSLETTER_DOMAIN=news.petabyte.market`, `NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market`, `NEWSLETTER_FROM=updates@petabyte.market`, `NEWSLETTER_REPLY_TO=info@petabyte.market` (defaults already match). The newsletter reuses the `MAILGUN_API_KEY` secret — no extra key needed.

---

### Validate after entering everything

```bash
# locally, with the same values exported, or let CI's configuration-preflight run it:
python scripts/validate_github_configuration.py --env-name test        # test/staging
python scripts/validate_github_configuration.py --env-name production   # production
```

Secrets are reported only as `NAME=SET` / `MISSING` — values are never printed.
