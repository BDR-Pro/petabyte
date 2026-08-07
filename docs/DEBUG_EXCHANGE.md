# Debug exchange

When Claude needs information from your servers, it appends a **numbered debug request**
here instead of just asking. You open the latest `PENDING` request, run the one script (or
commands), and paste the output back. Claude then marks it `RESOLVED`/`FAILED` and appends
the next step.

**Protocol**
- Requests are numbered and **never deleted**.
- Status is one of: `PENDING` (waiting on you) · `RUNNING` (you're executing) ·
  `RESOLVED` (fixed/understood) · `FAILED` (needs another round).
- Scripts referenced live in `docs/scripts/` (bash, `set -Eeuo pipefail`, print progress,
  collect diagnostics, meaningful exit codes).
- Secrets are never printed into this file. Export them in your shell first.

---

## DEBUG REQUEST #1 — verify seller telemetry reaches the platform  · Status: **PENDING**

**Reason:** confirm the ephemeral-seller telemetry path works end to end — the seller
agent's OUTBOUND heartbeat is observed by the platform, increments
`petabyte_seller_heartbeats_total`, and shows up as `petabyte_sellers_online >= 1`.

**Run on:** Seller GPU Droplet (`165.22.236.63`), then the Platform server.

**Commands (seller):**
```bash
bash /opt/petabyte/docs/scripts/debug_gpu_agent.sh
```
**Commands (platform):**
```bash
export PROMETHEUS_METRICS_TOKEN="<paste — do NOT commit>"
curl -fsS -H "Authorization: Bearer $PROMETHEUS_METRICS_TOKEN" \
  https://petabyte.market/internal/metrics \
  | grep -E '^petabyte_(sellers_online|seller_heartbeats_total|gpus_online|agents_online)'
```

**Expected information / success:**
- Agent JSON logs show `agent.startup` then repeating `agent.heartbeat`.
- `curl https://petabyte.market/heartbeat`-driven counters rise:
  `petabyte_seller_heartbeats_total` increasing, `petabyte_sellers_online >= 1`,
  `petabyte_gpus_online >= 1`.
- No `authentication` / `403` / `404` errors in the agent log.

**Next action after you paste results:** if heartbeats are sent but counters don't move →
check API-key scope (`node`) and `PETABYTE_SPEC_ID` ownership; if the agent can't POST →
DNS/TLS/egress from the seller box (it must reach `https://petabyte.market` outbound); if
counters move but `sellers_online` stays 0 → heartbeat staleness/`HEARTBEAT_TIMEOUT_S`.

---

## DEBUG REQUEST #2 — repair the observability stack  · Status: **PENDING**

**Reason:** the observability Droplet at `/opt/petabyte-observability` has five known
failures (Grafana datasource escape error, OTel Collector `service.telemetry.metrics.address`
invalid key, Tempo `ingester/compactor not found`, Loki health-check accuracy, Redis
health-check password). This runs the idempotent repair: it backs up, rewrites only the
broken configs, pins all images (no `:latest`), preserves volumes + credentials, validates,
restarts, and verifies. It does **not** delete data or regenerate passwords.

**Run on:** the observability Droplet (as root).

### Option A — the file is already in the repo checkout on the Droplet
```bash
cd /opt/petabyte-observability
sudo bash /opt/petabyte/docs/scripts/repair_observability_stack.sh
```

### Option B — copy/paste without transferring any file
```bash
cat > /root/repair_observability_stack.sh <<'SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
# =============================================================================
# repair_observability_stack.sh
#
# Idempotent, safe-to-rerun repair for the Petabyte observability Droplet at
# /opt/petabyte-observability. Fixes the five known failures without deleting
# data, regenerating passwords, or recreating the Droplet:
#
#   1. Grafana datasource provisioning: "yaml: line 27: found unknown escape
#      character" — a regex `\s` inside a DOUBLE-QUOTED YAML scalar. YAML double
#      quotes only allow a small set of escapes, so `\s` is illegal. Fix: emit the
#      datasource file with regexes in SINGLE quotes (no escape processing).
#   2. OpenTelemetry Collector: "service.telemetry.metrics has invalid key:
#      address" — `service.telemetry.metrics.address` was deprecated (v0.111) and
#      REMOVED (v0.123). Fix: use the supported `readers:` (OpenTelemetry SDK)
#      syntax for the pinned Collector version.
#   3. Tempo: "field ingester/compactor not found in type app.Config" — the config
#      did not match the running binary's schema. Fix: write a canonical, valid
#      single-binary + local-storage config for the pinned Tempo version.
#   4. Loki: starts, but the health check may be inaccurate. Fix: probe `/ready`
#      (200 "ready") with a start_period, not a wrong path.
#   5. Redis: health check uses the password incorrectly. Fix: `redis-cli -a
#      "$REDIS_PASSWORD" --no-auth-warning ping` reading the password from the
#      container env — never printed, never in the compose file literally.
#
# It ALSO removes every `:latest` image tag and pins explicit, mutually
# compatible versions (see PINS below), preserves the existing .env + Docker
# volumes + credentials, backs everything up first, validates before restart,
# and rolls back on request.
#
# Usage:
#   sudo bash repair_observability_stack.sh            # repair
#   sudo bash repair_observability_stack.sh --rollback # restore newest backup
#   sudo bash repair_observability_stack.sh --rollback 20260806-101500
# =============================================================================

ROOT="${OBS_ROOT:-/opt/petabyte-observability}"
COMPOSE="$ROOT/docker-compose.yml"
BACKUPS="$ROOT/backups"
TS="$(date +%Y%m%d-%H%M%S)"
MAP="$ROOT/.repair_service_map"

# ---- Pinned, compatible versions (NO :latest). Rationale in comments. --------
# Grafana 11.x: provisioning schema used below (datasources v1, derivedFields,
#   tracesToLogsV2) is stable across 10.4→11.x.
PIN_GRAFANA="grafana/grafana:11.4.0"
# Prometheus v2.x: v3 renamed some flags; v2.54.1 matches the scrape/rule syntax here.
PIN_PROMETHEUS="prom/prometheus:v2.54.1"
# Loki 3.x: TSDB schema v13 + native OTLP ingestion at /otlp (used by the Collector).
PIN_LOKI="grafana/loki:3.2.1"
# Tempo 2.6.x: the canonical single-binary config below matches this schema exactly.
PIN_TEMPO="grafana/tempo:2.6.1"
# Collector-contrib 0.111.0: introduced the `service.telemetry.metrics.readers`
#   syntax used below and still ships the exporters we use (otlp, prometheus,
#   otlphttp). We standardise on -contrib (superset of core).
PIN_OTELCOL="otel/opentelemetry-collector-contrib:0.111.0"
# Redis 7.4.x: stable; requirepass + ACL unchanged.
PIN_REDIS="redis:7.4.1"
# Node Exporter / cAdvisor: current stable, pinned.
PIN_NODE="prom/node-exporter:v1.8.2"
PIN_CADVISOR="gcr.io/cadvisor/cadvisor:v0.49.1"

# ------------------------------------------------------------------ helpers ---
c_reset=$'\e[0m'; c_b=$'\e[1m'; c_g=$'\e[32m'; c_y=$'\e[33m'; c_r=$'\e[31m'
log()  { printf '%s==>%s %s\n' "$c_b" "$c_reset" "$*"; }
ok()   { printf '   %sOK%s   %s\n' "$c_g" "$c_reset" "$*"; }
warn() { printf '   %s!!%s   %s\n' "$c_y" "$c_reset" "$*"; }
die()  { printf '%sERROR:%s %s\n' "$c_r" "$c_reset" "$*" >&2; exit 1; }

compose() { docker compose -f "$COMPOSE" "$@"; }

on_err() {
  local ec=$?
  printf '\n%sRepair aborted (exit %s).%s Backup preserved under %s\n' \
    "$c_r" "$ec" "$c_reset" "$BACKUPS/$TS" >&2
  exit "$ec"
}
trap on_err ERR

# ------------------------------------------------------------------ rollback --
rollback() {
  local want="${1:-}"
  [ -d "$BACKUPS" ] || die "no backups directory at $BACKUPS"
  local dir
  if [ -n "$want" ]; then dir="$BACKUPS/$want"; else
    dir="$BACKUPS/$(ls -1 "$BACKUPS" | sort | tail -1)"; fi
  [ -d "$dir" ] || die "backup not found: $dir"
  log "Rolling back from $dir"
  for item in docker-compose.yml .env prometheus loki tempo otel-collector grafana; do
    if [ -e "$dir/$item" ]; then
      rm -rf "$ROOT/$item"
      cp -a "$dir/$item" "$ROOT/$item"
      ok "restored $item"
    fi
  done
  ( cd "$ROOT" && docker compose up -d )
  ok "stack restarted from backup $dir"
  exit 0
}

# --------------------------------------------------------- preflight + backup -
[ "${1:-}" = "--rollback" ] && { shift || true; rollback "${1:-}"; }

log "Verifying $ROOT"
[ -d "$ROOT" ] || die "$ROOT does not exist — is this the observability Droplet?"
[ -f "$COMPOSE" ] || die "$COMPOSE not found"
command -v docker >/dev/null || die "docker not installed"
docker compose version >/dev/null 2>&1 || die "docker compose v2 required"

log "Backing up current config to $BACKUPS/$TS"
mkdir -p "$BACKUPS/$TS"
for item in docker-compose.yml .env prometheus loki tempo otel-collector grafana/provisioning; do
  if [ -e "$ROOT/$item" ]; then
    mkdir -p "$BACKUPS/$TS/$(dirname "$item")"
    cp -a "$ROOT/$item" "$BACKUPS/$TS/$item"
  fi
done
ok "backup complete (data volumes + .env untouched; nothing deleted)"

# Ensure pyyaml for the in-place, structure-preserving compose edit.
if ! python3 -c 'import yaml' 2>/dev/null; then
  log "Installing python3 yaml (needed to edit compose in place)"
  (apt-get update -y && apt-get install -y python3-yaml) >/dev/null 2>&1 \
    || pip3 install --quiet pyyaml \
    || die "could not install pyyaml"
fi

# ----------------------------------------------------------- fix everything ---
# A single Python pass: (a) pin images (drops :latest), (b) fix/normalise the
# healthchecks for redis/loki/grafana/prometheus, (c) discover each service's
# config bind mount and write the corrected config there (source of truth is the
# mount the container actually uses), and (d) emit a KIND=service map for bash.
# Volumes, networks, ports, env_file and every other field are preserved as-is.
log "Rewriting broken configs + pinning images (preserving volumes/creds)"
OBS_ROOT="$ROOT" \
PIN_GRAFANA="$PIN_GRAFANA" PIN_PROMETHEUS="$PIN_PROMETHEUS" PIN_LOKI="$PIN_LOKI" \
PIN_TEMPO="$PIN_TEMPO" PIN_OTELCOL="$PIN_OTELCOL" PIN_REDIS="$PIN_REDIS" \
PIN_NODE="$PIN_NODE" PIN_CADVISOR="$PIN_CADVISOR" MAP="$MAP" \
python3 - <<'PYEOF'
import os, yaml

ROOT = os.environ["OBS_ROOT"]
COMPOSE = os.path.join(ROOT, "docker-compose.yml")

PINS = {
    "grafana/grafana": os.environ["PIN_GRAFANA"],
    "prom/prometheus": os.environ["PIN_PROMETHEUS"],
    "grafana/loki": os.environ["PIN_LOKI"],
    "grafana/tempo": os.environ["PIN_TEMPO"],
    "otel/opentelemetry-collector": os.environ["PIN_OTELCOL"],
    "otel/opentelemetry-collector-contrib": os.environ["PIN_OTELCOL"],
    "redis": os.environ["PIN_REDIS"],
    "bitnami/redis": os.environ["PIN_REDIS"],
    "prom/node-exporter": os.environ["PIN_NODE"],
    "quay.io/prometheus/node-exporter": os.environ["PIN_NODE"],
    "gcr.io/cadvisor/cadvisor": os.environ["PIN_CADVISOR"],
    "google/cadvisor": os.environ["PIN_CADVISOR"],
}

def repo_of(image):
    image = (image or "").split("@")[0]
    # strip tag: last ':' only if it's a tag (no '/') after it
    if ":" in image and "/" in image.rsplit(":", 1)[0] + "x":
        base, tag = image.rsplit(":", 1)
        if "/" not in tag:
            image = base
    return image

def kind_of(repo):
    if "grafana/grafana" in repo: return "grafana"
    if "prometheus" in repo and "node" not in repo: return "prometheus"
    if "loki" in repo: return "loki"
    if "tempo" in repo: return "tempo"
    if "opentelemetry-collector" in repo: return "otel"
    if repo.endswith("/redis") or repo == "redis": return "redis"
    if "node-exporter" in repo: return "node"
    if "cadvisor" in repo: return "cadvisor"
    return None

# ---- corrected config contents (valid for the pinned versions) --------------
GRAFANA_DS = r'''# Managed by repair_observability_stack.sh. Regexes are SINGLE-quoted so YAML
# never tries to process backslash escapes (this is what caused the
# "found unknown escape character" provisioning error). Datasources point at the
# in-compose service DNS names over the private network (no auth headers, no
# secrets in this file).
apiVersion: 1
datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      httpMethod: POST
      timeInterval: 15s
  - name: Loki
    uid: loki
    type: loki
    access: proxy
    url: http://loki:3100
    jsonData:
      # Link a log's trace_id to the Tempo trace. SINGLE-quoted regex on purpose.
      derivedFields:
        - name: trace_id
          matcherRegex: '"trace_id"\s*:\s*"([a-fA-F0-9]+)"'
          url: '${__value.raw}'
          datasourceUid: tempo
          urlDisplayLabel: 'View trace'
  - name: Tempo
    uid: tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        spanStartTimeShift: '-1h'
        spanEndTimeShift: '1h'
        filterByTraceID: true
      nodeGraph:
        enabled: true
'''

OTEL_CFG = r'''# Managed by repair_observability_stack.sh — valid for opentelemetry-collector
# 0.111.0. The deprecated `service.telemetry.metrics.address` key (which caused
# "invalid key: address") is replaced by the supported `readers:` (OTel SDK)
# syntax below. Logs go to Loki via native OTLP (Loki 3.x /otlp); the removed
# `loki` exporter is intentionally NOT used.
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 5s
    limit_percentage: 80
    spike_limit_percentage: 25
  batch:
    timeout: 2s
    send_batch_size: 512

exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
  prometheus:
    endpoint: 0.0.0.0:8889
  otlphttp/loki:
    endpoint: http://loki:3100/otlp
    tls:
      insecure: true

extensions:
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  telemetry:
    metrics:
      level: detailed
      # SUPPORTED replacement for the removed `address:` key. Exposes the
      # collector's own metrics on :8888 for Prometheus to scrape.
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlphttp/loki]
'''

TEMPO_CFG = r'''# Managed by repair_observability_stack.sh — canonical single-binary + local
# storage config valid for Tempo 2.6.x. Top-level `ingester`/`compactor` are
# valid here; the previous "field ingester not found in type app.Config" error
# came from a config that did not match the binary schema. WAL + blocks live on
# the existing persistent volume mounted at /var/tempo.
stream_over_http_enabled: true
server:
  http_listen_port: 3200
  grpc_listen_port: 9095
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318
ingester:
  max_block_duration: 5m
compactor:
  compaction:
    block_retention: 72h
storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks
'''

LOKI_CFG = r'''# Managed by repair_observability_stack.sh — single-node config valid for
# Loki 3.2.x. Native OTLP ingestion (used by the Collector) needs structured
# metadata, which is enabled below. Data stays under /loki (existing volume).
auth_enabled: false
server:
  http_listen_port: 3100
  grpc_listen_port: 9096
common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
limits_config:
  allow_structured_metadata: true
  volume_enabled: true
'''

PROM_CFG = r'''# Managed by repair_observability_stack.sh — valid for Prometheus v2.54.x.
# Scrapes the collector's own metrics + node/cadvisor exporters over the compose
# network. The platform API's /internal/metrics is scraped remotely elsewhere.
global:
  scrape_interval: 15s
  evaluation_interval: 15s
scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['localhost:9090']
  - job_name: otel-collector
    static_configs:
      - targets: ['otel-collector:8888', 'otel-collector:8889']
  - job_name: node-exporter
    static_configs:
      - targets: ['node-exporter:9100']
  - job_name: cadvisor
    static_configs:
      - targets: ['cadvisor:8080']
'''

CONFIGS = {"grafana": GRAFANA_DS, "otel": OTEL_CFG, "tempo": TEMPO_CFG,
           "loki": LOKI_CFG, "prometheus": PROM_CFG}

# ---- healthchecks that work with each image (shell + wget available) ---------
# NOTE: the Tempo and OTel Collector images are distroless (no shell), so we do
# NOT attach a container healthcheck to them — they are verified from the host in
# the bash verify step instead. Redis/Loki/Grafana/Prometheus images have a shell.
HEALTH = {
    "grafana": ["CMD-SHELL", "wget -q --spider http://localhost:3000/api/health || exit 1"],
    "prometheus": ["CMD-SHELL", "wget -q --spider http://localhost:9090/-/healthy || exit 1"],
    "loki": ["CMD-SHELL", "wget -q --spider http://localhost:3100/ready || exit 1"],
    # Redis: use the password from the CONTAINER env ($$ is escaped so compose
    # passes a literal $REDIS_PASSWORD to the shell). Never printed.
    "redis": ["CMD-SHELL", 'redis-cli -a "$$REDIS_PASSWORD" --no-auth-warning ping | grep -q PONG'],
}

with open(COMPOSE) as f:
    doc = yaml.safe_load(f) or {}
services = doc.get("services", {})

def host_path(bind):
    # "host:container[:mode]" -> absolute host path (relative resolved to ROOT)
    parts = bind.split(":")
    hp = parts[0]
    if not os.path.isabs(hp):
        hp = os.path.normpath(os.path.join(ROOT, hp))
    return hp, (parts[1] if len(parts) > 1 else "")

CONV = {  # conventional fallback paths under ROOT
    "grafana": "grafana/provisioning/datasources/datasources.yaml",
    "otel": "otel-collector/config.yaml",
    "tempo": "tempo/tempo.yaml",
    "loki": "loki/loki-config.yaml",
    "prometheus": "prometheus/prometheus.yml",
}

mapping = {}
for name, svc in services.items():
    if not isinstance(svc, dict):
        continue
    repo = repo_of(svc.get("image", ""))
    kind = kind_of(repo)
    if kind is None:
        continue
    mapping[kind] = name
    # (a) pin image (drops :latest / any tag)
    if repo in PINS:
        svc["image"] = PINS[repo]
    # (b) healthcheck
    if kind in HEALTH:
        hc = svc.get("healthcheck", {}) or {}
        hc["test"] = HEALTH[kind]
        hc.setdefault("interval", "15s")
        hc.setdefault("timeout", "5s")
        hc.setdefault("retries", 10)
        hc["start_period"] = "40s"
        svc["healthcheck"] = hc
    # redis: make sure the container has REDIS_PASSWORD for the healthcheck
    if kind == "redis":
        env = svc.get("environment")
        if isinstance(env, list):
            if not any(str(e).startswith("REDIS_PASSWORD") for e in env):
                env.append("REDIS_PASSWORD=${REDIS_PASSWORD}")
        elif isinstance(env, dict):
            env.setdefault("REDIS_PASSWORD", "${REDIS_PASSWORD}")
        else:
            svc["environment"] = ["REDIS_PASSWORD=${REDIS_PASSWORD}"]
    # (c) write corrected config to the mount the container actually uses
    if kind in CONFIGS:
        target = None
        for b in (svc.get("volumes", []) or []):
            if not isinstance(b, str):
                continue
            hp, cp = host_path(b)
            low = (cp or hp).lower()
            if kind == "grafana":
                if "provisioning" in low and "datasource" in low:
                    target = hp if hp.endswith((".yaml", ".yml")) else os.path.join(hp, "datasources.yaml")
                    break
                if "provisioning" in low:
                    target = os.path.join(hp, "datasources", "datasources.yaml")
            elif hp.endswith((".yaml", ".yml")) and kind in low.replace("otel-collector", "otel"):
                target = hp; break
            elif hp.endswith((".yaml", ".yml")) and (
                    (kind == "otel" and "otel" in low) or
                    (kind == "prometheus" and "prom" in low) or
                    (kind == "tempo" and "tempo" in low) or
                    (kind == "loki" and "loki" in low)):
                target = hp; break
        if target is None:
            target = os.path.join(ROOT, CONV[kind])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write(CONFIGS[kind])
        # also refresh the conventional path so the repo layout stays canonical
        conv = os.path.join(ROOT, CONV[kind])
        if os.path.abspath(conv) != os.path.abspath(target):
            os.makedirs(os.path.dirname(conv), exist_ok=True)
            with open(conv, "w") as f:
                f.write(CONFIGS[kind])
        print(f"   wrote {kind} config -> {target}")

with open(COMPOSE, "w") as f:
    yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, width=120)

with open(os.environ["MAP"], "w") as f:
    for k, v in mapping.items():
        f.write(f"{k.upper()}_SVC={v}\n")
    otelcfg = None
    for b in (services.get(mapping.get("otel", ""), {}).get("volumes", []) or []):
        if isinstance(b, str) and (b.split(":")[0]).endswith((".yaml", ".yml")):
            hp = b.split(":")[0]
            otelcfg = hp if os.path.isabs(hp) else os.path.normpath(os.path.join(ROOT, hp))
            break
    f.write(f"OTEL_CFG={otelcfg or os.path.join(ROOT,'otel-collector/config.yaml')}\n")
print("   compose pinned + healthchecks normalised; volumes/creds preserved")
PYEOF
ok "configs rewritten, images pinned, redis/loki/grafana/prometheus healthchecks fixed"

# shellcheck disable=SC1090
[ -f "$MAP" ] && source "$MAP"

# ------------------------------------------------------------- validate -------
log "Validating docker compose (docker compose config)"
compose config >/dev/null && ok "compose file is valid"

if [ -n "${OTEL_CFG:-}" ] && [ -f "$OTEL_CFG" ]; then
  log "Validating OpenTelemetry Collector config against $PIN_OTELCOL"
  docker run --rm -v "$OTEL_CFG":/etc/otelcol/config.yaml:ro "$PIN_OTELCOL" \
      validate --config /etc/otelcol/config.yaml \
    && ok "collector config valid" \
    || die "collector config invalid — see output above; backup kept at $BACKUPS/$TS"
fi

# ------------------------------------------------------------- pull + up -------
log "Pulling ONLY the pinned images"
compose pull

log "Starting the stack (docker compose up -d)"
compose up -d --remove-orphans

# ------------------------------------------------------------- verify ---------
# Prefer a host HTTP probe on the conventional port; fall back to the container's
# running/health state (so distroless services and unpublished ports still pass).
probe_http() { curl -fsS --max-time 4 "$1" >/dev/null 2>&1; }
cid()  { compose ps -q "$1" 2>/dev/null || true; }
running() { local id; id="$(cid "$1")"; [ -n "$id" ] && \
  [ "$(docker inspect -f '{{.State.Running}}' "$id" 2>/dev/null)" = "true" ] && \
  [ "$(docker inspect -f '{{.State.Restarting}}' "$id" 2>/dev/null)" != "true" ]; }

verify() {  # verify <label> <svc-var-value> <url> <retries>
  local label="$1" svc="$2" url="$3" tries="${4:-40}" i=0
  [ -z "$svc" ] && { warn "$label: service not found in compose (skipped)"; return 0; }
  while [ "$i" -lt "$tries" ]; do
    if [ -n "$url" ] && probe_http "$url"; then ok "$label healthy ($url)"; return 0; fi
    if [ -z "$url" ] && running "$svc"; then ok "$label running"; return 0; fi
    # if URL probe keeps failing but the container is healthy/running, accept it
    if [ -n "$url" ] && running "$svc"; then
      local h; h="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$(cid "$svc")" 2>/dev/null || echo '')"
      [ "$h" = "healthy" ] && { ok "$label healthy (container health)"; return 0; }
    fi
    i=$((i+1)); sleep 5
  done
  return 1
}

FAILED=()
log "Waiting for services to become healthy (up to ~3 min each)"
verify "Grafana"          "${GRAFANA_SVC:-}"    "http://localhost:3000/api/health" || FAILED+=("${GRAFANA_SVC:-grafana}")
verify "Prometheus"       "${PROMETHEUS_SVC:-}" "http://localhost:9090/-/healthy"  || FAILED+=("${PROMETHEUS_SVC:-prometheus}")
verify "Loki"             "${LOKI_SVC:-}"       "http://localhost:3100/ready"      || FAILED+=("${LOKI_SVC:-loki}")
verify "Tempo"            "${TEMPO_SVC:-}"      "http://localhost:3200/ready"      || FAILED+=("${TEMPO_SVC:-tempo}")
verify "OTel Collector"   "${OTEL_SVC:-}"       "http://localhost:13133/"          || FAILED+=("${OTEL_SVC:-otel-collector}")
verify "Node Exporter"    "${NODE_SVC:-}"       "http://localhost:9100/metrics"    || FAILED+=("${NODE_SVC:-node-exporter}")
verify "cAdvisor"         "${CADVISOR_SVC:-}"   "http://localhost:8080/healthz"    || FAILED+=("${CADVISOR_SVC:-cadvisor}")

# Redis: PONG via the container using the password from its env (never printed).
if [ -n "${REDIS_SVC:-}" ]; then
  if compose exec -T "$REDIS_SVC" sh -c 'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping' 2>/dev/null | grep -q PONG; then
    ok "Redis PONG (authenticated)"
  else
    FAILED+=("$REDIS_SVC"); warn "Redis did not return PONG"
  fi
else
  warn "Redis service not found in compose (skipped)"
fi

# ------------------------------------------------------------- outcome --------
echo
if [ "${#FAILED[@]}" -eq 0 ]; then
  printf '%s================ REPAIR SUCCESSFUL ================%s\n' "$c_g$c_b" "$c_reset"
  echo "Pinned images:"
  echo "  grafana=$PIN_GRAFANA  prometheus=$PIN_PROMETHEUS  loki=$PIN_LOKI"
  echo "  tempo=$PIN_TEMPO  otel=$PIN_OTELCOL  redis=$PIN_REDIS"
  echo "  node-exporter=$PIN_NODE  cadvisor=$PIN_CADVISOR"
  echo "Backup: $BACKUPS/$TS   (credentials + volumes preserved; nothing deleted)"
  echo "No secret values were printed."
  compose ps
  exit 0
else
  printf '%s================ REPAIR INCOMPLETE ================%s\n' "$c_r$c_b" "$c_reset"
  echo "Unhealthy: ${FAILED[*]}"
  for svc in "${FAILED[@]}"; do
    echo; echo "----- last 200 log lines: $svc -----"
    compose logs --tail=200 "$svc" 2>&1 || true
  done
  echo
  echo "Backup preserved at $BACKUPS/$TS. Persistent volumes were NOT deleted."
  echo "Rollback if needed:  sudo bash $0 --rollback $TS"
  exit 1
fi

SCRIPT
chmod +x /root/repair_observability_stack.sh
sudo /root/repair_observability_stack.sh
```

**Rollback (if a service stays unhealthy):**
```bash
sudo /root/repair_observability_stack.sh --rollback
```

**Expected success information (paste the tail back here):**
- `================ REPAIR SUCCESSFUL ================`
- `Grafana healthy`, `Prometheus healthy`, `Loki healthy`, `Tempo healthy`,
  `OTel Collector healthy`, `Redis PONG (authenticated)`, `Node Exporter running`,
  `cAdvisor running`.
- A `docker compose ps` table with every service `running`/`healthy`.
- No secret value is printed anywhere.

**If it exits non-zero:** it prints the last 200 log lines of each unhealthy service and
keeps the backup. Paste those log lines here and I'll append DEBUG REQUEST #3.

**Next action after you paste results:** confirm all services healthy → mark this request
`RESOLVED` and proceed to the end-to-end trace verification in `docs/TESTING_EXCHANGE.md`.

---

<!-- Append DEBUG REQUEST #3, ... below. Increment the number. Never delete. -->
