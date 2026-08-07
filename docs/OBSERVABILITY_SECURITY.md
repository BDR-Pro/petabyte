# Observability Security

The observability stack handles money-adjacent counters, correlation ids, and logs.
It must be locked down at least as tightly as the platform itself. Default posture:
**nothing public, encrypted in transit, authenticated everywhere, least privilege.**

## Nothing public

- No observability component (Prometheus, Loki, Tempo, the OpenTelemetry Collector,
  Grafana) is exposed to the public internet on an open port.
- The API's Prometheus endpoint is `/internal/metrics` (not `/metrics`, which serves
  the public investor HTML). Money-adjacent counters must never be world-readable.
- The API itself binds to `127.0.0.1:8000` (`BIND`) behind nginx; the obs backends
  live on the private network / obs server.

## Firewall allowlist

- Each obs component accepts connections only from known source IPs: the Petabyte
  servers (as telemetry producers / scrape targets) and operator access.
- Default-deny inbound; explicitly allow the Collector's OTLP port from Petabyte hosts,
  Prometheus → `/internal/metrics` from the scrape source, and Grafana only from
  operator/allowlisted networks.
- The GPU node's DCGM exporter is scraped only from the private network, never public.

## TLS everywhere

- All telemetry transport is TLS: OTLP export (`OTEL_EXPORTER_OTLP_ENDPOINT` over TLS),
  Prometheus remote-write / scrape, Loki push, Tempo, and Grafana.
- **Never disable certificate verification** to "get it working" — fix the trust chain
  instead. (This mirrors the agent-proxy CA rule for the platform.)
- `OTEL_EXPORTER_OTLP_HEADERS` carries the exporter's auth credential and is a secret.

## Authentication on every backend

- **Prometheus remote-write / scrape**: authenticated. Scraping `/internal/metrics`
  requires the `PROMETHEUS_METRICS_TOKEN` bearer token; when a token is configured
  there is **no** silent loopback bypass. With no token, access is restricted to
  loopback / trusted proxies only.
- **Loki**: push and query require auth; no anonymous ingestion or read.
- **Tempo**: authenticated read/write.
- **Grafana**: no anonymous access; named accounts with roles.

## Read-only investor Grafana account

- The **Investor Demo** dashboard is viewed through a dedicated **read-only** Grafana
  account (Viewer role) scoped to the demo dashboards only.
- That account cannot edit dashboards, add data sources, run arbitrary queries against
  sensitive datasources, or see admin/settlement internals beyond the curated panels.
- Investor demos run in **Stripe test mode / no real money** (see
  `INVESTOR_OBSERVABILITY_DEMO.md`); the read-only account reinforces that boundary.

## Redis hardening

- Redis is `bind`-restricted (not `0.0.0.0`), password-authenticated
  (`REDIS_URL` carries credentials and is a secret), and firewalled to the platform
  hosts only.
- Redis holds no financial truth; even so it must not be reachable from outside the
  private network.

## Private network / WireGuard between hosts

- Prefer a private network (or WireGuard, `WG_*` variables) between the Petabyte
  servers and the observability server so OTLP/scrape/query traffic never traverses the
  public internet.
- Telemetry, scrape, and query traffic should ride the private interface; public
  interfaces expose only what nginx serves.

## GPU node isolation (least privilege)

- The GPU node (seller agent) **never** receives any platform observability admin
  credential — no Grafana admin, no Prometheus/Loki/Tempo write-admin token, no
  Collector admin.
- Consistent with the platform rule that the GPU node never receives any platform
  secret (Stripe, DB, admin, signing key). It only holds its own `PETABYTE_API_KEY`
  and optional node signing key.
- GPU telemetry (DCGM metrics, agent logs/traces) is exported outbound to the Collector
  over an authenticated, TLS'd path — the node is a producer, not an administrator.

## Redaction and secret hygiene in telemetry

- Centralized redaction (`LOG_REDACTION_ENABLED=true`) strips secrets and PII by key
  name and by value pattern (Stripe `sk_`/`rk_`/`whsec_` keys, client secrets, bearer
  tokens, PAN-like digit runs, emails) **before** anything is logged or exported.
- Keep redaction on in every environment. Never disable it to debug — you'd risk
  leaking card data, tokens, cookies, DSNs, or DB/Redis URLs into Loki/Tempo/Sentry.
- Business ids (transaction/job/buyer/seller/gpu) are correlation identifiers, not
  secrets, and are safe to carry in log/trace bodies; they are still never used as
  metric labels (bounded cardinality).
