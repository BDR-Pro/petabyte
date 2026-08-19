# Observability Configuration

How observability is configured, where each setting comes from, what it does, and how
the system behaves when a telemetry backend fails.

## Where configuration comes from

All runtime config flows from **GitHub Variables and Secrets** into the server's
environment at deploy time. Set each value under **Settings → Secrets and variables →
Actions** (or per Environment), exactly as described in
[`GITHUB_MANUAL_SETUP_CHECKLIST.md`](./GITHUB_MANUAL_SETUP_CHECKLIST.md). On deploy,
the workflow regenerates the server env and restarts the services, so every change
takes effect on the next deploy. The `configuration-preflight` CI job validates the
config and fails the deploy if anything required is missing or unsafe.

- **Variables** = non-sensitive knobs (feature flags, endpoints, ratios). Shown as
  `NAME=default`.
- **Secrets** = sensitive values (tokens, DSNs, URLs with credentials). Shown as
  `NAME=<what to put>` and only ever entered in the GitHub Secrets UI — never committed.

The checklist already carries the coarse feature toggles
(`ENABLE_OTEL`, `ENABLE_PROMETHEUS`, `ENABLE_SENTRY`, `ENABLE_GRAFANA`,
`ENABLE_ELASTIC`, `LOG_LEVEL`). The finer-grained observability variables below are
read directly by `lumaris_api/observability.py`.

## Observability environment variables

| Variable | Default | What it does |
|---|---|---|
| `OBSERVABILITY_ENABLED` | `true` | Master switch for all telemetry. When false, logging stays but tracing/metrics become cheap no-ops. |
| `OBSERVABILITY_FAILURE_MODE` | `degrade` | `degrade` = telemetry errors are swallowed and never break the request/settlement path. `strict` = telemetry errors propagate (dev/test only — **never** in production). |
| `OTEL_ENABLED` | `true` | Enable OpenTelemetry tracing (gated by `OBSERVABILITY_ENABLED`). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(empty)_ | OTLP endpoint of the OpenTelemetry Collector. If empty, tracing initializes to a no-op even when enabled. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http` — selects the OTLP exporter transport. |
| `OTEL_TRACE_SAMPLE_RATIO` | `1.0` | Head sampling ratio. `1.0` = always on; `<1.0` uses `ParentBased(TraceIdRatioBased(ratio))` so a sampled parent keeps its children. |
| `PROMETHEUS_ENABLED` | `true` | Enable the Prometheus metric set (also gated by `OTEL_METRICS_ENABLED`). |
| `PROMETHEUS_METRICS_PATH` | `/internal/metrics` | Scrape path. Deliberately **not** `/metrics` (that serves the investor HTML dashboard). |
| `PROMETHEUS_METRICS_TOKEN` _(secret)_ | _(empty)_ | Bearer token required to scrape `/internal/metrics`. If set, the token is **required**; if unset, access is restricted to loopback / trusted proxies. |
| `LOG_FORMAT` | `json` | `json` = structured one-line-per-event logs (for Loki). Anything else = plain text (local dev). |
| `LOG_REDACTION_ENABLED` | `true` | Centralized redaction of secrets/PII by key name and value pattern before anything is logged or exported. Keep true everywhere. |
| `LOG_LEVEL` | `info` | Root log verbosity. |
| `SENTRY_DSN` _(secret)_ | _(empty)_ | Sentry project DSN. Enables error reporting (with `ENABLE_SENTRY=true`). |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Sentry performance-trace sampling rate (10% of transactions by default). |
| `REDIS_URL` _(secret)_ | _(empty)_ | Redis connection URL (with credentials). Optional — absence triggers in-process degrade (`redis.unavailable`). |
| `OTEL_EXPORTER_OTLP_HEADERS` _(secret)_ | _(empty)_ | Auth headers for the OTLP exporter (e.g. bearer/API key for the Collector). |

Supporting identity/resource variables also read by the instrumentation:
`OTEL_SERVICE_NAME` (defaults to `petabyte-api`), `OTEL_SERVICE_NAMESPACE`
(`petabyte`), `DEPLOYMENT_ENVIRONMENT`/`ENVIRONMENT`/`APP_ENV` (the `environment`
label), `RELEASE_VERSION`/`GITHUB_SHA` (release/version), and `PETABYTE_HOST_ROLE`
(the `host_role` Loki label). Tuning knobs:
`OBSERVABILITY_EXPORT_TIMEOUT_SECONDS` (5), `OBSERVABILITY_QUEUE_SIZE` (2048),
`OBSERVABILITY_BATCH_SIZE` (512).

## How each service identifies itself

Each service calls `init_observability(<service_name>)` at startup (the API calls it
with `SERVICE.API`). That sets the OTLP `service.name` and the Loki `service` label,
attaches `service.namespace`, `service.version` (release/SHA),
`deployment.environment`, and `petabyte.host_role` as resource attributes, and
installs the JSON log formatter + metric registry once (idempotent).

## How failures degrade

The whole point of `OBSERVABILITY_FAILURE_MODE=degrade` (the production default) is
that **telemetry can never break the app**:

- **Missing libraries / disabled features** → `init_tracing()` / `init_metrics()`
  return false and every helper (`span`, `event`, `inc_metric`, …) becomes a no-op.
  Log lines `otel.init.skipped` / `metrics.init.skipped` record why.
- **No OTLP endpoint configured** → tracing stays a no-op; the app runs normally.
- **Collector/Prometheus/Loki/Tempo/Sentry unreachable at runtime** → exports fail in
  the background, `petabyte_telemetry_export_failures_total{exporter,environment}`
  increments, and the app is unaffected. Exporters self-recover when the backend
  returns. See `runbooks/OBSERVABILITY_PIPELINE_FAILURE.md`.
- **`event()` / `span()` raising** → suppressed under `degrade` (re-raised under
  `strict`). The transition-telemetry emitter in the settlement path additionally
  swallows all exceptions so telemetry can never block a state change.
- **Redis unreachable** → in-process fallback with a `redis.unavailable` event; not a
  telemetry failure per se but the same degrade philosophy.

Confirm the live state any time via `GET /health/observability`.
