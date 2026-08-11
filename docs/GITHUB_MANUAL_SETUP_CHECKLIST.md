# GitHub manual setup checklist

> **Generated** by `scripts/generate_config_docs.py`. The setup is now tiny: create **one** Variable (`ENV_VARS`) holding all non-secret config, set the small set of **Secrets** individually, and flip one gate. You should not need to search the repo.

**GitHub → Settings → Secrets and variables → Actions.**

Legend: 🔴 required · ⚪ optional (default is safe).

## 1. Create the `ENV_VARS` Variable

Under **Variables**, create **`ENV_VARS`** and paste the bundle below (all non-secret config as `KEY=value;` pairs — newlines are fine). Regenerate any time with `python scripts/env_bundle.py generate`. **Never put a secret in here** — the deploy rejects any secret-classified key found in `ENV_VARS`.

```ini
ADMIN_USERS=info@petabyte.market;
ALLOWED_ORIGINS=;
AUTO_SETTLE_ON_RESULT=true;
AWS_REFERENCE_PRICE=12.29;
AWS_REGION=us-east-1;
BACKUP_RESCHEDULE_GRACE_S=900;
BASE_DOMAIN=petabyte.market;
BIND=127.0.0.1:8000;
CAL_BOOKING_URL=;
CIRCLE_API=https://api.circle.com/v1;
CONNECT_REFRESH_URL=;
CONNECT_RETURN_URL=;
DEFAULT_LANDING_VIDEO_ID=UUSWYaxboDA;
EMAIL_FROM=no-reply@petabyte.market;
EMAIL_PROVIDER=mailgun;
EMAIL_TOKEN_TTL_MIN=15;
ENABLE_ELASTIC=true;
ENABLE_GRAFANA=true;
ENABLE_OTEL=true;
ENABLE_PROMETHEUS=true;
ENABLE_SENTRY=false;
ENVIRONMENT=development;
GEOIP_DB=;
GEOIP_STUB=true;
GOOGLE_OAUTH_STUB=false;
GOOGLE_REDIRECT_URI=https://petabyte.market/auth/google/callback;
GRAFANA_ENABLED=true;
GRAFANA_URL=;
HEARTBEAT_TIMEOUT_S=60;
LEGACY_KEYS_FULL_ACCESS=false;
LOG_FORMAT=json;
LOG_LEVEL=info;
LOG_REDACTION_ENABLED=true;
LOKI_ENABLED=true;
LOKI_URL=;
MAILCHIMP_AUDIENCE_ID=;
MAILGUN_DOMAIN=petabyte.market;
MIN_REPUTATION=50;
NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market;
NEWSLETTER_PROVIDER=mailgun;
NICEHASH_API=https://api2.nicehash.com;
NICEHASH_STUB=true;
NICEHASH_TAKE_RATE=0.10;
NOTIFY_STUB=true;
OBSERVABILITY_BATCH_SIZE=512;
OBSERVABILITY_ENABLED=true;
OBSERVABILITY_EXPORT_TIMEOUT_SECONDS=5;
OBSERVABILITY_FAILURE_MODE=degrade;
OBSERVABILITY_QUEUE_SIZE=2048;
OBSERVABILITY_REQUIRED=false;
OBSERVABILITY_SERVER_HOST=;
OTEL_ENABLED=true;
OTEL_EXPORTER_OTLP_ENDPOINT=;
OTEL_EXPORTER_OTLP_PROTOCOL=grpc;
OTEL_LOGS_ENABLED=true;
OTEL_METRICS_ENABLED=true;
OTEL_SERVICE_NAME=petabyte-api;
OTEL_SERVICE_NAMESPACE=petabyte;
OTEL_TRACE_SAMPLE_RATIO=1.0;
PAYMENTS_LIVE_ENABLED=false;
PAYMENTS_MODE=sandbox;
PAYOUT_CAPABILITIES_PATH=;
PAYOUT_COOLING_OFF_H=24;
PAYOUT_HOLD_DAYS=14;
PAYOUT_HOLD_ON_REPORT=true;
PAYOUT_READINESS_MAX_AGE_S=2592000;
PAYOUT_STUB=true;
PETABYTE_HOST_ROLE=;
PETABYTE_OFFLINE_TEST=;
PLATFORM_AUTH_MARGIN_BPS=2000;
PLATFORM_COMMISSION_BPS=;
PLATFORM_CURRENCY=usd;
PLATFORM_DEFAULT_COUNTRY=US;
PLATFORM_FIXED_FEE_MINOR=0;
PLATFORM_MAX_DURATION_S=86400;
PLATFORM_MIN_CHARGE_MINOR=50;
PLATFORM_TAKE_RATE=0.10;
PROMETHEUS_ENABLED=true;
PROMETHEUS_METRICS_PATH=/internal/metrics;
PROMETHEUS_URL=;
PUBLIC_BASE_URL=;
REAPER_DISABLED=true;
REAPER_INTERVAL_S=20;
REDIS_ENABLED=false;
REDIS_NAMESPACE=petabyte;
REFERRAL_MONTHLY_CAP=25;
REFERRAL_REWARD_USD=20;
RESERVATION_RECLAIM_STUCK_S=93600;
S3_BUCKET=;
S3_ENDPOINT=;
S3_REGION=us-east-1;
S3_SSE=AES256;
S3_STUB=true;
SANCTIONS_SCREEN_PROVIDER=;
SELLER_AUDIT_SAMPLE_RATE=0.25;
SELLER_FRAUD_PENALTY=40;
SENTRY_DSN=;
SENTRY_ENABLED=true;
SENTRY_ENVIRONMENT=;
SENTRY_MAX_BREADCRUMBS=30;
SENTRY_PROFILES_SAMPLE_RATE=0.0;
SENTRY_RELEASE=;
SENTRY_TRACES_SAMPLE_RATE=0.1;
STRIPE_ALLOW_LIVE=false;
STRIPE_API_VERSION=;
STRIPE_FEE_BPS=290;
STRIPE_FEE_FIXED_MINOR=30;
STRIPE_GATEWAY=fake;
STRIPE_MODE=test;
TEE_ATTESTATION_TTL_S=;
TEE_MEASUREMENT_ALLOWLIST=;
TEE_REQUIRE_HARDWARE=;
TEE_VERIFIER=;
TEMPO_ENABLED=true;
TEMPO_URL=;
TREMENDOUS_API=https://api.tremendous.com/api/v2;
TRUSTED_PROXIES=127.0.0.1,::1;
USDC_CHAIN=MATIC;
WALLET_MAX_TOPUP_MINOR=500000;
WALLET_MIN_TOPUP_MINOR=500;
WEB_CONCURRENCY=2;
WG_APPLY=false;
WG_ENDPOINT=;
WG_INTERFACE=wg0;
WG_PUBLIC_KEY=;
```

Edit values in place before pasting (e.g. `ENVIRONMENT=production;`, `STRIPE_MODE=live;` when going live). Anything you omit falls back to the safe manifest default. Validate a bundle locally with `python scripts/env_bundle.py validate` (reads `$ENV_VARS`, a `--file`, or stdin).

## 2. Create the `DEPLOY_CONFIG_FROM_GITHUB` Variable

Set **`DEPLOY_CONFIG_FROM_GITHUB=false`** while you finish setup. Flip it to **`true`** once `ENV_VARS` + all required Secrets are in — then the deploy generates the server env from GitHub and pushes it (atomically, with health check + auto-rollback). These two are the ONLY standalone Variables; every other non-secret value lives in `ENV_VARS`.

## 3. Secrets (individually managed — NOT in ENV_VARS)

Create each under **Secrets**. Required ones (🔴) must exist before the first gated deploy — the preflight fails closed if any is missing. Values are never printed anywhere.

### Platform secrets

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
- **`SERVER_PRIVATE_KEY`** — 🔴 required. Generate a Fernet key: `python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'`. Rotating it makes existing encrypted API keys undecryptable — migrate the current value.
- **`STRIPE_API_KEY`** — ⚪ optional. Legacy deposits key — same source as STRIPE_SECRET_KEY.
- **`STRIPE_PUBLISHABLE_KEY`** — ⚪ optional. Stripe Dashboard → API keys (pk_test_… / pk_live_…).
- **`STRIPE_SECRET_KEY`** — ⚪ optional. Stripe Dashboard → Developers → API keys. Use sk_test_… (test); only sk_live_… when deliberately going live.
- **`STRIPE_WEBHOOK_SECRET`** — ⚪ optional. Stripe Dashboard → Developers → Webhooks → signing secret (whsec_…), or `stripe listen`.
- **`TEE_TRUSTED_ROOT`** — ⚪ optional. Base64 vendor attestation root public key (confidential computing only).
- **`TREMENDOUS_API_KEY`** — ⚪ optional. Tremendous dashboard (only if using Tremendous payouts).
- **`TREMENDOUS_FUNDING_ID`** — ⚪ optional. Tremendous dashboard (funding source id).
- **`TREMENDOUS_PRODUCT_ID`** — ⚪ optional. Tremendous dashboard (product id).

### Deployment secrets (GitHub Actions → server; never in the runtime env)

- **`DEPLOY_SSH_KEY`** — 🔴 required. The PRIVATE SSH key authorized on the server (e.g. id_ed25519). Never commit it.
- **`DROPLET_SSH_KNOWN_HOSTS`** — 🔴 required. Pinned SSH host key(s) for the deploy target. Generate with `ssh-keyscan -t ed25519,rsa <host>`, then VERIFY the fingerprint out-of-band before pinning — compare `ssh-keygen -lf` of the scanned key against the fingerprint from the droplet's own console (e.g. `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` over the provider console). ssh-keyscan output is unauthenticated and can be MITM'd, so pinning it unverified only trusts-on-first-use. Verifies the server before any secret is transferred; the deploy fails closed if unset.
- **`DROPLET_SSH_KNOWN_HOSTS_OBSERV`** — ⚪ optional. Pinned SSH host key(s) for the observability VM. REQUIRED by deploy-observability.yml, which fails closed without it (no trust-on-first-use). Generate with `ssh-keyscan -t ed25519,rsa <observ-host>` and verify the fingerprint out-of-band (provider console) before pinning.

## 4. GPU node (seller agent) — configured on the node, not the platform

A seller's GPU machine gets its OWN config (it never receives any platform secret). Generate its bundle with `python scripts/env_bundle.py generate --scope gpu` and set its secrets on the node:

```ini
AGENT_TELEMETRY_ENABLED=true;
GPU_COUNT=1;
GPU_METRICS_ENABLED=true;
GPU_METRICS_INTERVAL=10;
GPU_MODEL=;
HEARTBEAT_INTERVAL=15;
IDLE_MINING=false;
JOB_POLL_INTERVAL=5;
MAX_CONCURRENT_GPU_JOBS=1;
MAX_HOURS=24;
NB_CELL_TIMEOUT=120;
NB_MAX_OUTPUT=1000000;
NB_TIMEOUT=600;
NICEHASH_ADDRESS=;
NICEHASH_IMAGE=nicehash/nicehashminer:latest;
PETABYTE_API_URL=https://petabyte.market;
PETABYTE_SPEC_ID=;
PETABYTE_UPDATE_INTERVAL_S=3600;
PETABYTE_UPDATE_REPO=;
PRICE_PER_HOUR=;
PROVIDER=;
SANDBOX_IMAGE=python:3.12-slim;
UNITS=1;
VRAM_GB=;
```

### GPU node secrets

- **`PETABYTE_AGENT_KEY`** — ⚪ optional. Path to the node's Ed25519 signing key (attestation + signed results).
- **`PETABYTE_API_JWT`** — ⚪ optional. The seller's login JWT (spec owner) — used once during node attestation.
- **`PETABYTE_API_KEY`** — 🔴 required. Minted per GPU node: POST /create_api_key (set on the node, not the platform).

## 5. Newsletter (Mailgun) — one-time Mailgun setup

The newsletter runs on the Mailgun sending subdomain **news.petabyte.market**, sends **From `updates@petabyte.market`**, and forwards replies to **`info@petabyte.market`**. The signup form adds subscribers to a Mailgun mailing list. Configure in this order:

1. In Mailgun, add + verify the sending domain `news.petabyte.market` (DNS: SPF, DKIM, and a tracking CNAME).
2. Create a **mailing list** on that domain (e.g. `newsletter@news.petabyte.market`) and set its From name/address to `updates@petabyte.market` on the list itself.
3. Add a Mailgun **Route** that forwards replies to that list/address on to `info@petabyte.market`.
4. The newsletter keys are already in the `ENV_VARS` bundle above (`NEWSLETTER_PROVIDER=mailgun`, `NEWSLETTER_LIST_ADDRESS=newsletter@news.petabyte.market`) — defaults match, no change needed. From / Reply-To and reply-forwarding are configured **on the list in Mailgun** (steps 2–3), not via env vars. The newsletter reuses the `MAILGUN_API_KEY` **Secret** — no extra key.

---

### Validate after entering everything

```bash
# validate the ENV_VARS bundle itself (syntax, no secrets, known keys):
ENV_VARS="$(pbpaste)" python scripts/env_bundle.py validate   # or --file bundle.txt
# full preflight (bundle + Secrets + safety rules); CI runs this on every deploy:
python scripts/validate_github_configuration.py --env-name auto
```

Secrets are reported only as `NAME=SET` / `MISSING` — values are never printed. A secret accidentally placed in `ENV_VARS`, an unknown key, a duplicate, or a leftover legacy individual Variable all FAIL the preflight.
