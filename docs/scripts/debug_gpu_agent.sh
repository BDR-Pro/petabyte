#!/usr/bin/env bash
# Diagnose the Petabyte seller agent on a GPU Droplet: GPU, Docker/CUDA, agent process,
# and OUTBOUND heartbeat to the platform. Prints progress and collects diagnostics.
# Copy/paste ready. Secrets are read from the environment, never printed.
set -Eeuo pipefail

API_URL="${PETABYTE_API_URL:-https://petabyte.market}"
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mOK\033[0m %s\n' "$1"; }
warn() { printf '   \033[33m!!\033[0m %s\n' "$1"; }

step "GPU (nvidia-smi)"
if command -v nvidia-smi >/dev/null; then nvidia-smi || warn "nvidia-smi returned non-zero"; else warn "nvidia-smi not found"; fi

step "CUDA in Docker (NVIDIA Container Toolkit)"
if command -v docker >/dev/null; then
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi \
    && ok "CUDA container sees the GPU" || warn "GPU not visible in a container — check nvidia-container-toolkit"
else
  warn "docker not found"
fi

step "Seller agent process / service"
systemctl status petabyte-agent --no-pager -l 2>/dev/null | head -20 || warn "no systemd unit; agent may be run manually"
pgrep -af "task_fetcher.py" || warn "task_fetcher.py not running"

step "Agent logs (last 200 lines, structured JSON)"
( journalctl -u petabyte-agent -n 200 --no-pager 2>/dev/null \
  || tail -n 200 /var/log/petabyte-agent.log 2>/dev/null \
  || warn "no agent logs found (journal or /var/log/petabyte-agent.log)" ) | tail -n 200

step "Outbound heartbeat reachability (the agent only makes OUTBOUND calls)"
if [ -n "${PETABYTE_API_KEY:-}" ] && [ -n "${PETABYTE_SPEC_ID:-}" ]; then
  code=$(curl -s -o /tmp/hb.out -w '%{http_code}' -X POST "$API_URL/heartbeat" \
    -H "X-API-KEY: $PETABYTE_API_KEY" -H "Content-Type: application/json" \
    -d "{\"spec_id\": ${PETABYTE_SPEC_ID}}" || echo "000")
  echo "   heartbeat HTTP $code"
  case "$code" in
    200) ok "heartbeat accepted"; cat /tmp/hb.out; echo ;;
    401|403) warn "auth failed — check PETABYTE_API_KEY scope 'node'" ;;
    404) warn "spec not found / not owned — check PETABYTE_SPEC_ID" ;;
    000) warn "could NOT reach $API_URL — DNS/TLS/egress from this box?" ;;
    *)   warn "unexpected status $code"; cat /tmp/hb.out; echo ;;
  esac
else
  warn "set PETABYTE_API_KEY and PETABYTE_SPEC_ID to test the heartbeat"
fi

step "Connectivity to the platform (TLS, no cert bypass)"
curl -fsS "$API_URL/healthz" && echo && ok "platform reachable" || warn "platform /healthz unreachable"

echo; echo "Done. Paste the output above into docs/DEBUG_EXCHANGE.md under the open request."
