# Petabyte Observability

Version-controlled configuration for the Petabyte observability stack:
**Prometheus** (metrics), **Loki** (structured logs), **Tempo** (traces) and
**Grafana** (dashboards), fed by an **OpenTelemetry Collector**. Every config
here is internally consistent with the telemetry the platform already emits
(`lumaris_api/observability.py`, `lumaris_api/metrics.py`).

## What's here

```text
observability/
├── docker-compose.yml              # one-command local/self-hosted stack (Grafana public ONLY)
├── .env.example                    # copy to .env; Grafana admin password + root_url + env
├── compose/                        # compose-local backend configs (plain HTTP, internal net)
│   ├── prometheus.compose.yml      # scrapes self/loki/tempo/collector (loads the same rules)
│   ├── loki-config.yaml            # single-binary Loki, filesystem storage
│   ├── tempo-config.yaml           # Tempo, OTLP in, filesystem storage
│   └── otel-collector-config.yaml  # OTLP in -> Tempo(traces)/Loki(logs)/Prometheus(metrics)
├── grafana/
│   ├── build_dashboards.py         # generator — emits the 7 canonical dashboards (source of truth)
│   ├── validate_dashboards.py      # guard — every panel metric must exist; unique uids; balanced PromQL
│   ├── dashboards/                 # version-controlled dashboards (JSON), auto-provisioned
│   │   │                           #  --- the 7 canonical (generated) ---
│   │   ├── executive.json               uid: petabyte-executive
│   │   ├── marketplace.json             uid: petabyte-marketplace
│   │   ├── payments.json                uid: petabyte-settlement       (Payments & Stripe)
│   │   ├── gpu-fleet.json               uid: petabyte-seller-fleet     (Seller GPU Fleet)
│   │   ├── api.json                     uid: petabyte-api
│   │   ├── infrastructure.json          uid: petabyte-infra
│   │   ├── security.json                uid: petabyte-security
│   │   │                           #  --- retained auxiliaries ---
│   │   ├── workers_queue.json           uid: petabyte-workers          (queue alert links)
│   │   ├── transaction_trace.json       uid: petabyte-transaction-trace
│   │   └── investor_demo.json           uid: petabyte-investor-demo
│   └── provisioning/
│       ├── dashboards/petabyte.yaml     # file provider -> /etc/grafana/dashboards
│       └── datasources/datasources.yaml # Prometheus(uid=prometheus), Loki(uid=loki), Tempo(uid=tempo)
├── otel-collector/
│   └── config.yaml                 # PRODUCTION collector scaffold (TLS + bearer auth)
├── prometheus/
│   ├── prometheus.yml              # PRODUCTION scrape config + remote_write scaffold
│   └── rules/petabyte_rules.yaml   # recording + alerting rules (shared by both stacks)
└── README.md
```

## Quickstart — `docker compose up -d`

```bash
cd observability
cp .env.example .env          # set GF_SECURITY_ADMIN_PASSWORD (required)
docker compose up -d          # Grafana + Prometheus + Loki + Tempo + OTel collector
# Grafana -> http://127.0.0.1:3000  (front it with the TLS reverse proxy for data.petabyte.market)
```

Grafana comes up with the three datasources **and all dashboards already loaded** from
`grafana/dashboards/` — no manual "Import dashboard". Point your app/agent's
`OTEL_EXPORTER_OTLP_ENDPOINT` at the collector, and add the `petabyte-api` scrape target in
`compose/prometheus.compose.yml` (commented example included) to light up the app panels.

**Editing a dashboard:** change `grafana/build_dashboards.py`, run
`python observability/grafana/build_dashboards.py`, then
`python observability/grafana/validate_dashboards.py`. CI regenerates and `git diff --exit-code`s
the output, so the committed JSON can never drift from the generator, and every referenced metric
is checked to actually exist.

### Only Grafana is public

- **Grafana** is the sole public UI (`data.petabyte.market`). In compose it binds to
  `127.0.0.1:3000` (loopback) so only the host's TLS reverse proxy can reach it.
- **Prometheus, Loki, Tempo and the OTel collector publish NO host ports** — they are reachable
  only on the internal `obs` docker network. They are never exposed to the public internet.
- Set `GF_SERVER_ROOT_URL=https://data.petabyte.market` (in `.env`). A correct root URL behind the
  proxy avoids the reverse-proxy storage-partition class of Grafana frontend errors
  (e.g. `localStorage.getItem is not a function`).

## How it's provisioned

- **Datasources** and the **dashboard provider** are provisioned declaratively
  from `grafana/provisioning/`. Compose mounts `provisioning/` at
  `/etc/grafana/provisioning` and the dashboard JSON at **`/etc/grafana/dashboards`**
  (read-only), and the provider (`provisioning/dashboards/petabyte.yaml`) points at
  that same path. The dashboards path is deliberately **outside** `/var/lib/grafana`
  (the persistent `grafana-data` named volume) — mounting it *inside* the named volume
  could let the volume mask the files, which is what left the `Petabyte` folder created
  but empty. Grafana loads them on startup and keeps them in sync with this repo
  (`allowUiUpdates: false`).
- **The deploy proves provisioning, not just liveness.** After reload, the deploy
  workflow runs `grafana/verify_provisioning.py` against the local Grafana API and only
  succeeds if the health check passes **and** the datasources are provisioned **and**
  every dashboard UID from the committed JSON is present in the `Petabyte` folder. On a
  mismatch it dumps non-secret diagnostics (host/container files, mounts, provisioning
  log lines, expected-vs-observed UIDs), rolls back to the last good config, and fails.
  Run it locally for the static config check: `python observability/grafana/verify_provisioning.py`.
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
