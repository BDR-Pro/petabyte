#!/usr/bin/env bash
# Verify the observability pipeline from a machine that can reach the observability server.
# Runs the platform metrics check + the observability smoke test's remote tier.
# Copy/paste ready. Point the *_URL vars at your obs server first. No secret is printed.
set -Eeuo pipefail
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mOK\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m!!\033[0m %s\n' "$1"; }

: "${OBS_HOST:?set OBS_HOST=<observability server host/ip>}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://$OBS_HOST:4317}"
export TEMPO_URL="${TEMPO_URL:-http://$OBS_HOST:3200}"
export LOKI_URL="${LOKI_URL:-http://$OBS_HOST:3100}"
export GRAFANA_URL="${GRAFANA_URL:-http://$OBS_HOST:3000}"
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://$OBS_HOST:9090}"

step "Backend endpoints reachable"
curl -fsS "$LOKI_URL/ready"    >/dev/null && ok "Loki ready"    || warn "Loki not ready ($LOKI_URL)"
curl -fsS "$TEMPO_URL/ready"   >/dev/null && ok "Tempo ready"   || warn "Tempo not ready ($TEMPO_URL)"
curl -fsS "$GRAFANA_URL/api/health" >/dev/null && ok "Grafana up" || warn "Grafana down ($GRAFANA_URL)"
curl -fsS "$PROMETHEUS_URL/-/ready" >/dev/null && ok "Prometheus ready" || warn "Prometheus not ready"

step "Observability smoke test (local tier + OTel propagation + remote tier)"
REPO="${REPO:-/opt/petabyte}"
python3 "$REPO/scripts/observability_smoke_test.py"

echo; echo "If the remote checks now say 'ok' (not 'skip'), telemetry is landing on the obs server."
echo "Paste the summary into docs/TESTING_EXCHANGE.md and mark the observability checklist item COMPLETE."
