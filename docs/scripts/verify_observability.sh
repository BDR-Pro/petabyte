#!/usr/bin/env bash
# Verify the observability pipeline from a machine that can reach the observability server.
# Runs the platform metrics check + the observability smoke test's remote tier.
# Copy/paste ready. Point the *_URL vars at your obs server first. No secret is printed.
set -Eeuo pipefail
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mOK\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m!!\033[0m %s\n' "$1"; }

# check_backend NAME URL PROBE_PATH OK_MSG FAIL_MSG
# A backend is "required" only if its *_URL is set; an unset URL is optional and skipped.
# A configured-but-unreachable backend records a failure in $failed (checked below).
check_backend() {
  local name="$1" url="$2" path="$3" okmsg="$4" failmsg="$5"
  if [ -z "$url" ]; then
    warn "$name URL not set — skipping (optional)"
    return 0
  fi
  if curl -fsS "$url$path" >/dev/null; then
    ok "$okmsg"
  else
    warn "$failmsg"
    failed=1
  fi
  return 0
}

: "${OBS_HOST:?set OBS_HOST=<observability server host/ip>}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://$OBS_HOST:4317}"
export TEMPO_URL="${TEMPO_URL:-http://$OBS_HOST:3200}"
export LOKI_URL="${LOKI_URL:-http://$OBS_HOST:3100}"
export GRAFANA_URL="${GRAFANA_URL:-http://$OBS_HOST:3000}"
export PROMETHEUS_URL="${PROMETHEUS_URL:-http://$OBS_HOST:9090}"

step "Backend endpoints reachable"
failed=0
check_backend "Loki"       "${LOKI_URL:-}"       "/ready"      "Loki ready"       "Loki not ready ($LOKI_URL)"
check_backend "Tempo"      "${TEMPO_URL:-}"      "/ready"      "Tempo ready"      "Tempo not ready ($TEMPO_URL)"
check_backend "Grafana"    "${GRAFANA_URL:-}"    "/api/health" "Grafana up"       "Grafana down ($GRAFANA_URL)"
check_backend "Prometheus" "${PROMETHEUS_URL:-}" "/-/ready"    "Prometheus ready" "Prometheus not ready"

if [ "$failed" -ne 0 ]; then
  warn "One or more configured backends are unreachable — aborting before the smoke test."
  exit 1
fi

step "Observability smoke test (local tier + OTel propagation + remote tier)"
REPO="${REPO:-/opt/petabyte}"
python3 "$REPO/scripts/observability_smoke_test.py"

echo; echo "If the remote checks now say 'ok' (not 'skip'), telemetry is landing on the obs server."
echo "Paste the summary into docs/TESTING_EXCHANGE.md and mark the observability checklist item COMPLETE."
