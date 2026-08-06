#!/usr/bin/env python3
"""Generate config/github_configuration_manifest.yaml — the single source of truth for
GitHub Variables (non-sensitive) and Secrets (credentials).

The manifest is built from lumaris_api/template.env (which the env-drift smoke guard keeps
complete for every var the Python code reads) plus curated metadata (scope, allowed
values, validation, required, notes) and the GPU-agent / deployment vars. Re-run this
after adding an env var so validation, drift-check, and the docs stay in sync:

    python scripts/build_config_manifest.py
"""
import os
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_ENV = os.path.join(ROOT, "lumaris_api", "template.env")
OUT = os.path.join(ROOT, "config", "github_configuration_manifest.yaml")

# ---- SECRET classification. Everything not a secret is a GitHub Variable. --------------
SECRET_EXACT = {
    "SECRET_KEY", "SERVER_PRIVATE_KEY", "DATABASE_URL", "PAYMENT_WEBHOOK_SECRET",
    "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MAILGUN_API_KEY", "SENDGRID_API_KEY",
    "POSTMARK_TOKEN", "MAILCHIMP_API_KEY", "CIRCLE_API_KEY", "CIRCLE_WALLET_ID",
    "TREMENDOUS_API_KEY", "TREMENDOUS_FUNDING_ID", "TREMENDOUS_PRODUCT_ID",
    "NICEHASH_API_KEY", "NICEHASH_API_SECRET", "NICEHASH_ORG_ID",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GATEWAY_TOKEN", "CAL_WEBHOOK_SECRET",
    "SENTRY_DSN", "TEE_TRUSTED_ROOT", "PETABYTE_API_KEY", "PETABYTE_AGENT_KEY",
    "DEPLOY_SSH_KEY", "DROPLET_HOST", "DROPLET_USER",
    # observability credentials
    "OTEL_EXPORTER_OTLP_HEADERS", "REDIS_URL", "PROMETHEUS_METRICS_TOKEN",
    "GRAFANA_SERVICE_ACCOUNT_TOKEN", "PROMETHEUS_REMOTE_WRITE_PASSWORD",
    "PROMETHEUS_REMOTE_WRITE_USERNAME", "LOKI_USERNAME", "LOKI_PASSWORD",
    "TEMPO_USERNAME", "TEMPO_PASSWORD",
}
# Public-looking values that are NOT secrets even though the name matches the heuristic.
NON_SECRET_EXACT = {"WG_PUBLIC_KEY", "GOOGLE_REDIRECT_URI", "STRIPE_API_VERSION",
                    "PAYOUT_CAPABILITIES_PATH", "MAILGUN_DOMAIN", "GEOIP_DB",
                    "EMAIL_TOKEN_TTL_MIN", "MAILGUN_NEWSLETTER_DOMAIN"}


def is_secret(name: str) -> bool:
    if name in NON_SECRET_EXACT:
        return False
    if name in SECRET_EXACT:
        return True
    return bool(re.search(r"(SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|_DSN$|CREDENTIAL)", name))


# ---- Dev/test-only vars: never deployment config, excluded from the manifest -----------
TEST_ONLY = {
    "BUYER_USER", "BUYER_PASS", "STRIPE_TEST_SECRET_KEY", "PAYOUT_TEST_ALLOW_DROP",
    "MAILGUN_TEST_RECIPIENT", "NO_COLOR", "INTERVAL", "BENCH_TOKENS_SEC",
    "DEMO_API_URL", "FASTAPI_SERVER_URL", "API_BASE", "API_KEY", "SPEC_ID", "AGENT_ENV",
}

# ---- GPU-agent + deployment vars (not in the platform template.env) --------------------
AGENT_VARS = {
    "PETABYTE_API_URL": {"required": True, "default": "https://petabyte.market",
                         "scope": ["gpu"], "format": "url",
                         "description": "Public Petabyte API base URL the agent talks to."},
    "PETABYTE_API_KEY": {"required": True, "default": None, "scope": ["gpu"],
                         "description": "Encrypted node API key (X-API-KEY) minted at /create_api_key."},
    "PETABYTE_SPEC_ID": {"required": True, "default": None, "scope": ["gpu"], "format": "int",
                         "description": "The spec id this node serves."},
    "PETABYTE_AGENT_KEY": {"required": False, "default": "~/.petabyte/agent_ed25519.key",
                           "scope": ["gpu"],
                           "description": "Path to the node's Ed25519 signing key (attestation + signed results)."},
    "HEARTBEAT_INTERVAL": {"required": False, "default": "15", "scope": ["gpu"], "format": "int",
                           "description": "Seconds between node heartbeats (a.k.a. GPU_HEARTBEAT_INTERVAL)."},
    "JOB_POLL_INTERVAL": {"required": False, "default": "5", "scope": ["gpu"], "format": "int",
                          "description": "Seconds between /jobs/next polls."},
    "PRICE_PER_HOUR": {"required": False, "default": None, "scope": ["gpu"], "format": "float",
                       "description": "Seller's offered price per GPU-hour (USD)."},
    "GPU_MODEL": {"required": False, "default": None, "scope": ["gpu"],
                  "description": "Manual GPU model override when nvidia-smi is absent."},
    "GPU_COUNT": {"required": False, "default": "1", "scope": ["gpu"], "format": "int",
                  "description": "Manual GPU count override."},
    "VRAM_GB": {"required": False, "default": None, "scope": ["gpu"], "format": "int",
                "description": "Manual VRAM override (GB)."},
    "UNITS": {"required": False, "default": "1", "scope": ["gpu"], "format": "int",
              "description": "Identical rentable units on this node."},
    "MAX_HOURS": {"required": False, "default": "24", "scope": ["gpu"], "format": "int",
                  "description": "Max rentable hours offered."},
    "NB_TIMEOUT": {"required": False, "default": "600", "scope": ["gpu"], "format": "int",
                   "description": "Notebook job hard timeout (s) — must stay bounded."},
    "NB_CELL_TIMEOUT": {"required": False, "default": "120", "scope": ["gpu"], "format": "int",
                        "description": "Per-cell notebook timeout (s)."},
    "NB_MAX_OUTPUT": {"required": False, "default": "1000000", "scope": ["gpu"], "format": "int",
                      "description": "Max notebook output bytes."},
    "SANDBOX_IMAGE": {"required": False, "default": "python:3.12-slim", "scope": ["gpu"],
                      "description": "Container image for the notebook sandbox."},
    "PETABYTE_UPDATE_REPO": {"required": False, "default": None, "scope": ["gpu"],
                             "description": "Agent self-update source repo (optional)."},
    "PETABYTE_UPDATE_INTERVAL_S": {"required": False, "default": "3600", "scope": ["gpu"],
                                   "format": "int", "description": "Agent self-update check interval (s)."},
    "PETABYTE_API_JWT": {"required": False, "default": None, "secret": True, "scope": ["gpu"],
                         "description": "Seller JWT (owner of the spec) used during node attestation/enrollment."},
    "PROVIDER": {"required": False, "default": None, "scope": ["gpu"],
                 "description": "Provider/node display name (defaults to the machine hostname)."},
    # idle NiceHash mining on the GPU node (off by default)
    "IDLE_MINING": {"required": False, "default": "false", "scope": ["gpu"], "format": "bool",
                    "description": "Enable idle NiceHash mining when no paid job is running."},
    "NICEHASH_ADDRESS": {"required": False, "default": None, "scope": ["gpu"],
                         "description": "NiceHash payout address for idle mining (shared across nodes)."},
    "NICEHASH_IMAGE": {"required": False, "default": "nicehash/nicehashminer:latest", "scope": ["gpu"],
                       "description": "Docker image for the idle NiceHash miner."},
    "NICEHASH_TAKE_RATE": {"required": False, "default": "0.10", "scope": ["platform"], "format": "float",
                           "description": "Platform commission on idle-mining revenue (idle_reconcile tool)."},
    # deployment (GitHub Actions -> server) — all SECRETS
    "DEPLOY_SSH_KEY": {"required": True, "default": None, "secret": True, "scope": ["deployment"],
                       "description": "Private SSH key GitHub Actions uses to deploy to the server."},
    "DROPLET_HOST": {"required": True, "default": None, "secret": True, "scope": ["deployment"],
                     "description": "Deploy target host (IP/DNS)."},
    "DROPLET_USER": {"required": True, "default": None, "secret": True, "scope": ["deployment"],
                     "description": "Deploy SSH user."},
}

# ---- Curated metadata for important platform vars (allowed values / validation / notes) --
CURATED = {
    "ENVIRONMENT": {"allowed": ["development", "test", "staging", "production"],
                    "aka": "APP_ENV",
                    "description": "Application environment. In production the app REFUSES to boot with any stub on.",
                    "prod_notes": "Must be 'production' in prod; never leave stubs enabled."},
    "BASE_DOMAIN": {"aka": "APP_DOMAIN", "format": "hostname",
                    "description": "Public application domain."},
    "PUBLIC_BASE_URL": {"aka": "APP_URL", "format": "url_or_empty",
                        "description": "Public base URL for building share/reset links."},
    "LOG_LEVEL": {"allowed": ["debug", "info", "warning", "error", "critical",
                              "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                  "description": "Log verbosity."},
    "STRIPE_MODE": {"allowed": ["test", "live"], "description": "Declared Stripe mode; must match key prefixes."},
    "PAYMENTS_MODE": {"allowed": ["sandbox", "test", "live"], "description": "Payment mode label."},
    "PAYMENTS_LIVE_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                              "description": "MASTER live-money switch. Must be false unless deliberately going live.",
                              "prod_notes": "Live requires PAYMENTS_LIVE_ENABLED=true AND STRIPE_ALLOW_LIVE=true AND ENVIRONMENT=production AND live keys."},
    "STRIPE_ALLOW_LIVE": {"allowed": ["true", "false"], "format": "bool",
                          "description": "Second live gate; live keys refused unless true."},
    "STRIPE_GATEWAY": {"allowed": ["fake", "real"],
                       "description": "'real' uses the Stripe SDK; anything else = in-process fake (tests only)."},
    "GOOGLE_OAUTH_STUB": {"allowed": ["true", "false"], "format": "bool",
                          "description": "Google sign-in stub — MUST be false in production."},
    "PAYOUT_STUB": {"allowed": ["true", "false"], "format": "bool", "description": "Payout provider stub."},
    "S3_STUB": {"allowed": ["true", "false"], "format": "bool", "description": "S3 stub."},
    "GEOIP_STUB": {"allowed": ["true", "false"], "format": "bool", "description": "GeoIP stub."},
    "NICEHASH_STUB": {"allowed": ["true", "false"], "format": "bool", "description": "NiceHash stub."},
    "NOTIFY_STUB": {"allowed": ["true", "false"], "format": "bool",
                    "description": "Email/notify stub — false to actually send."},
    "LEGACY_KEYS_FULL_ACCESS": {"allowed": ["true", "false"], "format": "bool",
                                "description": "Legacy scopeless-key escape hatch — MUST be false in production."},
    "EMAIL_PROVIDER": {"allowed": ["mailgun", "ses", "sendgrid", "postmark"],
                       "description": "Notification email provider."},
    "REAPER_DISABLED": {"allowed": ["true", "false"], "format": "bool",
                        "description": "Keep true: the dedicated reaper service does the reaping."},
    "WG_APPLY": {"allowed": ["true", "false"], "format": "bool", "description": "Apply WireGuard config."},
    "GOOGLE_REDIRECT_URI": {"format": "url", "description": "Google OAuth redirect URI."},
    "DATABASE_URL": {"format": "url", "description": "SQLAlchemy database URL (Postgres in prod)."},
    "HEARTBEAT_TIMEOUT_S": {"format": "int", "description": "Seconds before a silent node is reaped."},
    "REAPER_INTERVAL_S": {"format": "int"},
    "EMAIL_TOKEN_TTL_MIN": {"format": "int"},
    "PAYOUT_HOLD_DAYS": {"format": "int", "description": "Earnings risk-hold before biweekly payout."},
    "PAYOUT_COOLING_OFF_H": {"format": "int"},
    "PAYOUT_HOLD_ON_REPORT": {"allowed": ["true", "false"], "format": "bool"},
    "AUTO_SETTLE_ON_RESULT": {"allowed": ["true", "false"], "format": "bool"},
    "WALLET_MIN_TOPUP_MINOR": {"format": "int"},
    "WALLET_MAX_TOPUP_MINOR": {"format": "int"},
    "SELLER_AUDIT_SAMPLE_RATE": {"format": "float"},
    "SELLER_FRAUD_PENALTY": {"format": "int"},
    "PLATFORM_TAKE_RATE": {"format": "float"},
    "MIN_REPUTATION": {"format": "int"},
    "AWS_REFERENCE_PRICE": {"format": "float"},
    "PLATFORM_CURRENCY": {"aka": "DEFAULT_CURRENCY", "description": "Platform settlement currency."},
    "BIND": {"description": "gunicorn bind address; keep 127.0.0.1 behind nginx (never public)."},
    "TRUSTED_PROXIES": {"description": "Reverse-proxy IPs trusted for X-Forwarded-For — never widen to spoofable."},
    "ALLOWED_ORIGINS": {"format": "csv_or_empty",
                        "description": "CORS origins — empty (same-origin) is the safe default; never '*' in prod."},
    "ADMIN_USERS": {"description": "Comma-separated admin usernames/emails."},
    # --- Newsletter (Mailgun mailing list on the news. sending subdomain) ---
    "NEWSLETTER_PROVIDER": {"allowed": ["mailgun", "mailchimp", "none"],
                            "description": "Newsletter backend. 'mailgun' adds signups to a Mailgun "
                                           "mailing list; 'mailchimp' uses the legacy audience; 'none' "
                                           "shows the honest 'not wired up' message."},
    "MAILGUN_NEWSLETTER_DOMAIN": {"format": "hostname",
                                  "description": "Mailgun sending subdomain for the newsletter (e.g. "
                                                 "news.petabyte.market). Reuses MAILGUN_API_KEY."},
    "NEWSLETTER_LIST_ADDRESS": {"format": "email_or_empty",
                                "description": "Mailgun mailing-list address signups are added to "
                                               "(e.g. newsletter@news.petabyte.market)."},
    "NEWSLETTER_FROM": {"format": "email_or_empty",
                        "description": "From address campaigns are sent as (e.g. updates@petabyte.market)."},
    "NEWSLETTER_REPLY_TO": {"format": "email_or_empty",
                            "description": "Reply-To for campaigns; a Mailgun Route forwards replies "
                                           "here (e.g. info@petabyte.market)."},
    # --- Observability (telemetry is degrade-safe; never blocks payments or jobs) ---
    "OBSERVABILITY_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                              "description": "Master switch for telemetry (logs/metrics/traces)."},
    "OBSERVABILITY_FAILURE_MODE": {"allowed": ["degrade", "strict"],
                                   "description": "On export failure: 'degrade' keeps serving; 'strict' raises.",
                                   "prod_notes": "Keep 'degrade' — telemetry must never block payments/jobs."},
    "OBSERVABILITY_EXPORT_TIMEOUT_SECONDS": {"format": "int",
                                             "description": "OTLP export timeout (bounded)."},
    "OBSERVABILITY_QUEUE_SIZE": {"format": "int", "description": "Bounded OTLP export queue size."},
    "OBSERVABILITY_BATCH_SIZE": {"format": "int", "description": "OTLP export batch size."},
    "LOG_FORMAT": {"allowed": ["json", "text"], "description": "Log format — json in all deployments."},
    "LOG_REDACTION_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                              "description": "Redact secrets/PII from logs. MUST be true in prod.",
                              "prod_notes": "Never disable in production."},
    "OTEL_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                     "description": "Enable OpenTelemetry tracing export."},
    "OTEL_SERVICE_NAMESPACE": {"description": "OTel service.namespace (petabyte)."},
    "OTEL_SERVICE_NAME": {"description": "OTel service.name for the API (petabyte-api)."},
    "OTEL_EXPORTER_OTLP_PROTOCOL": {"allowed": ["grpc", "http", "http/protobuf"],
                                    "description": "OTLP transport to the Collector."},
    "OTEL_EXPORTER_OTLP_ENDPOINT": {"format": "url_or_empty",
                                    "description": "OTLP endpoint of the OpenTelemetry Collector "
                                                   "(e.g. http://<obs>:4317). Blank -> tracing no-ops."},
    "OTEL_TRACE_SAMPLE_RATIO": {"format": "float",
                                "description": "Trace sample ratio (1.0 in test/pilot/investor demo)."},
    "OTEL_METRICS_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "OTEL_LOGS_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "PROMETHEUS_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "PROMETHEUS_METRICS_PATH": {"description": "Protected Prometheus scrape path (default /internal/metrics)."},
    "LOKI_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "TEMPO_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "GRAFANA_ENABLED": {"allowed": ["true", "false"], "format": "bool"},
    "GPU_METRICS_ENABLED": {"allowed": ["true", "false"], "format": "bool", "scope": ["gpu"],
                            "description": "Collect GPU metrics on the seller node (DCGM/NVML)."},
    "AGENT_TELEMETRY_ENABLED": {"allowed": ["true", "false"], "format": "bool", "scope": ["gpu"],
                                "description": "Seller-agent telemetry export (degrade-safe if obs down)."},
    "PETABYTE_HOST_ROLE": {"description": "OTel resource attribute petabyte.host_role (e.g. api, worker)."},
    "SENTRY_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                       "description": "Enable Sentry (needs SENTRY_DSN)."},
    "SENTRY_TRACES_SAMPLE_RATE": {"format": "float"},
    "SENTRY_PROFILES_SAMPLE_RATE": {"format": "float"},
    "SENTRY_MAX_BREADCRUMBS": {"format": "int"},
    "REDIS_NAMESPACE": {"description": "Key namespace prefix for Redis (petabyte)."},
    "REDIS_ENABLED": {"allowed": ["true", "false"], "format": "bool",
                      "description": "Use Redis for rate-limit/idempotency/lock coordination "
                                     "(degrades to in-process when off/unavailable). Never the ledger."},
}

# Observability tooling config that GitHub holds but the API does not read at runtime
# (used by the deploy, the Grafana provisioning, and the smoke test). Documented so the
# operator has the full list. Secrets never carry a default.
OBSERVABILITY_EXTRA = {
    "OBSERVABILITY_SERVER_HOST": {"default": None, "scope": ["observability"],
                                  "description": "Observability server host (private IP/DNS)."},
    "PROMETHEUS_URL": {"default": None, "scope": ["observability"], "secret": False,
                       "format": "url", "description": "Prometheus base URL (Grafana + smoke test)."},
    "GRAFANA_URL": {"default": None, "scope": ["observability"], "secret": False,
                    "format": "url", "description": "Grafana base URL."},
    "LOKI_URL": {"default": None, "scope": ["observability"], "secret": False,
                 "format": "url", "description": "Loki base URL."},
    "TEMPO_URL": {"default": None, "scope": ["observability"], "secret": False,
                  "format": "url", "description": "Tempo base URL."},
    "SENTRY_ENVIRONMENT": {"default": None, "scope": ["observability"], "secret": False,
                           "description": "Sentry environment label (defaults to ENVIRONMENT)."},
    "OBSERVABILITY_REQUIRED": {"default": "false", "scope": ["observability"], "secret": False,
                               "description": "Preflight control: when true the deploy FAILS if "
                                              "observability is off/unconfigured (default true in "
                                              "production, false elsewhere)."},
    "DEPLOY_CONFIG_FROM_GITHUB": {"default": "false", "scope": ["deployment"], "secret": False,
                                  "description": "Rollout gate. When 'true' the deploy generates the "
                                                 "server env from GitHub config and pushes it; until "
                                                 "then deploys stay code-only. Flip to true after "
                                                 "entering all Secrets."},
    # tooling credentials — secrets, no defaults, not asserted required (depends on the
    # actual auth config of the prepared observability server).
    "PROMETHEUS_REMOTE_WRITE_USERNAME": {"secret": True, "scope": ["observability"],
                                         "description": "Prometheus remote-write basic-auth user."},
    "PROMETHEUS_REMOTE_WRITE_PASSWORD": {"secret": True, "scope": ["observability"],
                                         "description": "Prometheus remote-write basic-auth password."},
    "LOKI_USERNAME": {"secret": True, "scope": ["observability"], "description": "Loki push auth user."},
    "LOKI_PASSWORD": {"secret": True, "scope": ["observability"], "description": "Loki push auth password."},
    "TEMPO_USERNAME": {"secret": True, "scope": ["observability"], "description": "Tempo push auth user."},
    "TEMPO_PASSWORD": {"secret": True, "scope": ["observability"], "description": "Tempo push auth password."},
    "GRAFANA_SERVICE_ACCOUNT_TOKEN": {"secret": True, "scope": ["observability"],
                                      "description": "Grafana service-account token (provisioning/smoke)."},
}

# Optional observability toggles the deployment layer standardizes on. Consumed by the
# deploy/monitoring layer (reserved: not yet read by the Python app) — documented so
# GitHub config is the single place to flip them.
RESERVED_VARS = {
    "ENABLE_ELASTIC": ("true", ["true", "false"], "Enable the Elastic logging stack (deploy/monitoring)."),
    "ENABLE_PROMETHEUS": ("true", ["true", "false"], "Enable Prometheus metrics scraping."),
    "ENABLE_GRAFANA": ("true", ["true", "false"], "Enable Grafana dashboards."),
    "ENABLE_OTEL": ("true", ["true", "false"], "Enable OpenTelemetry tracing."),
    "ENABLE_SENTRY": ("false", ["true", "false"], "Enable Sentry error reporting (also needs SENTRY_DSN)."),
    "GPU_METRICS_INTERVAL": ("10", None, "Seconds between GPU metrics samples (agent/telemetry)."),
    "MAX_CONCURRENT_GPU_JOBS": ("1", None, "Max concurrent paid jobs per GPU node (must stay bounded)."),
}


def parse_template_env():
    out = {}
    with open(TEMPLATE_ENV) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if re.fullmatch(r"[A-Z][A-Z0-9_]+", k):
                out[k] = v.strip()
    return out


def build_doc() -> dict:
    """Build the manifest document in memory (used by main() and the drift checker)."""
    tmpl = parse_template_env()
    variables, secrets = {}, {}

    def add(name, *, required, default, scope, secret, description="",
            allowed=None, fmt=None, aka=None, prod_notes=None, example=None):
        entry = {"required": bool(required),
                 "default": (None if secret else default),
                 "scope": scope, "description": description or ""}
        if allowed:
            entry["allowed"] = allowed
        if fmt:
            entry["format"] = fmt
        if aka:
            entry["aka"] = aka
        if prod_notes:
            entry["production_notes"] = prod_notes
        if example is not None:
            entry["example"] = example
        (secrets if secret else variables)[name] = entry

    # platform vars from template.env
    for name, default in tmpl.items():
        if name in TEST_ONLY:
            continue
        cur = CURATED.get(name, {})
        sec = cur.get("secret", is_secret(name))
        add(name, required=cur.get("required", name in ("SECRET_KEY", "SERVER_PRIVATE_KEY",
                                                        "DATABASE_URL")),
            default=(default if default != "" else None),
            scope=cur.get("scope", ["platform"]), secret=sec,
            description=cur.get("description", ""), allowed=cur.get("allowed"),
            fmt=cur.get("format"), aka=cur.get("aka"), prod_notes=cur.get("prod_notes"))

    # GPU-agent + deployment vars
    for name, m in AGENT_VARS.items():
        sec = m.get("secret", is_secret(name))
        add(name, required=m.get("required", False), default=m.get("default"),
            scope=m.get("scope", ["gpu"]), secret=sec, description=m.get("description", ""),
            fmt=m.get("format"))

    # observability tooling config (URLs + tooling credentials) not read by the API itself
    for name, m in OBSERVABILITY_EXTRA.items():
        sec = m.get("secret", is_secret(name))
        add(name, required=m.get("required", False), default=m.get("default"),
            scope=m.get("scope", ["observability"]), secret=sec,
            description=m.get("description", ""), fmt=m.get("format"))

    # reserved observability/gpu toggles (variables)
    for name, (default, allowed, desc) in RESERVED_VARS.items():
        add(name, required=False, default=default,
            scope=["platform"] if name.startswith("ENABLE_") else ["gpu"],
            secret=False, description=desc + " (reserved: standardized in GitHub config).",
            allowed=allowed, fmt=("bool" if allowed else "int"))

    return {
        "_meta": {
            "generated_by": "scripts/build_config_manifest.py",
            "source_of_truth": "GitHub Variables (non-sensitive) + GitHub Secrets (credentials)",
            "note": "Secrets never carry a real default. Re-run the builder after adding an env var.",
        },
        "variables": dict(sorted(variables.items())),
        "secrets": dict(sorted(secrets.items())),
    }


def render_yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, default_flow_style=False, width=100)


def main():
    doc = build_doc()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(render_yaml(doc))
    print(f"wrote {OUT}: {len(doc['variables'])} variables, {len(doc['secrets'])} secrets")


if __name__ == "__main__":
    main()
