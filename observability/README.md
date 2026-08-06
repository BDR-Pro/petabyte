# Petabyte Observability

Version-controlled configuration for the Petabyte observability stack:
**Prometheus** (metrics), **Loki** (structured logs), **Tempo** (traces) and
**Grafana** (dashboards), fed by an **OpenTelemetry Collector**. Every config
here is internally consistent with the telemetry the platform already emits
(`lumaris_api/observability.py`, `lumaris_api/metrics.py`).

## What's here

```
observability/
├── grafana/
│   ├── dashboards/                 # 8 version-controlled dashboards (JSON)
│   │   ├── executive_marketplace.json   uid: petabyte-executive
│   │   ├── transaction_trace.json       uid: petabyte-transaction-trace
│   │   ├── api.json                     uid: petabyte-api
│   │   ├── workers_queue.json           uid: petabyte-workers
│   │   ├── seller_agent_fleet.json      uid: petabyte-seller-fleet
│   │   ├── stripe_settlement.json       uid: petabyte-settlement
│   │   ├── infrastructure.json          uid: petabyte-infra
│   │   └── investor_demo.json           uid: petabyte-investor-demo (read-only)
│   └── provisioning/
│       ├── dashboards/petabyte.yaml     # file provider -> /var/lib/grafana/dashboards
│       └── datasources/datasources.yaml # Prometheus(uid=prometheus), Loki(uid=loki), Tempo(uid=tempo)
├── otel-collector/
│   └── config.yaml                 # OTLP in (grpc :4317 / http :4318) -> Tempo/Loki/Prometheus
├── prometheus/
│   ├── prometheus.yml              # scrape config + remote_write scaffold
│   └── rules/petabyte_rules.yaml   # recording + alerting rules
└── README.md
```

## How it's provisioned

- **Datasources** and the **dashboard provider** are provisioned declaratively
  from `grafana/provisioning/`. Mount `provisioning/` at
  `/etc/grafana/provisioning` and the dashboard JSON at
  `/var/lib/grafana/dashboards` (read-only). Grafana loads them on startup and
  keeps them in sync with this repo (`allowUiUpdates: false`).
- Datasources reference each other by stable **uid** (`prometheus`, `loki`,
  `tempo`). Dashboards and alerts reference the same uids and the dashboard uids
  above, so cross-links (Loki `trace_id` -> Tempo; Tempo -> Loki; alert
  `dashboard` annotations) resolve without manual wiring.
- **Prometheus** loads `rules/petabyte_rules.yaml` (recording rules
  `petabyte:http_error_ratio`, `petabyte:queue_oldest_seconds`,
  `petabyte:job_success_ratio`, ... plus alerting rules) and `remote_write`s to
  the central obs server.
- The **OTel Collector** receives OTLP traces + logs from the app and fans out
  to Tempo and Loki; it tail-samples so 100% of error traces and all traces
  carrying `payment.mode` or `run_id` span attributes are kept.
- All URLs/credentials are supplied via environment variables at deploy time
  (`${PROMETHEUS_URL}`, `${LOKI_URL}`, `${TEMPO_URL}`, `${GRAFANA_*}`, bearer
  token files, ...). Nothing sensitive is committed.

## How the app emits to it

- **Metrics** are exposed by the app at **`/internal/metrics`** (NOT `/metrics`,
  which serves the investor HTML page). Prometheus scrapes it with a
  `bearer_token_file` (`PROMETHEUS_METRICS_TOKEN`). Metric names/labels come from
  `init_metrics()` in `lumaris_api/observability.py` and use only bounded-
  cardinality labels — no ids as labels.
- **Traces + logs** are exported over OTLP to the collector
  (`OTEL_EXPORTER_OTLP_ENDPOINT`, auth via `OTEL_EXPORTER_OTLP_HEADERS`). Logs
  are structured JSON with a stable `event_name` and correlation ids
  (`trace_id`, `transaction_id`, `job_id`, ...) in the **body**, not as labels.
- **Service names** (`petabyte-web`, `petabyte-api`, `petabyte-worker`,
  `petabyte-scheduler`, `petabyte-stripe-webhook`, `petabyte-seller-agent`,
  `petabyte-gpu-executor`, `petabyte-result-validator`, `petabyte-settlement`)
  are the OTLP `service.name` and the Loki `service` label.
- **GPU** metrics come from the NVIDIA **DCGM exporter**; host/DB/cache metrics
  from **node_exporter / postgres_exporter / redis_exporter**.
- **Financial data is always separated by `payment_mode`** (test, live, sandbox,
  pilot, demo, real). Dashboards never mix real and test money in one panel.

## Security note (non-negotiable)

- **Nothing in this stack is public.** Prometheus, Loki, Tempo, the OTel
  Collector and Grafana run on the **private network / WireGuard** only.
- **TLS + authentication everywhere**: OTLP ingestion requires a bearer token
  and TLS; `/internal/metrics` requires a bearer token; Grafana talks to the
  backends with `${GRAFANA_*}` credentials; Prometheus `remote_write` uses
  `basic_auth` from secret files.
- **No credentials are committed.** All secrets are env-var placeholders resolved
  at deploy time from the secret store.
- Logs are redacted at the source (secrets, card data, tokens, PII) before they
  ever leave the app — see `redact()` in `lumaris_api/observability.py`.
- Runbooks referenced by alert annotations live under `docs/runbooks/`.
