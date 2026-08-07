#!/usr/bin/env bash
# Collect Petabyte platform diagnostics into a single tarball for troubleshooting.
# Redacts nothing sensitive by construction — it only gathers service logs + health JSON,
# never the env file or secrets. Run on the platform server. Copy/paste ready.
set -Eeuo pipefail
OUT="/tmp/petabyte-diag-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Service status + logs"
systemctl status lumaris-api lumaris-reaper --no-pager -l > "$OUT/services.txt" 2>&1 || true
journalctl -u lumaris-api -n 500 --no-pager > "$OUT/api.log" 2>&1 || true
journalctl -u lumaris-reaper -n 200 --no-pager > "$OUT/reaper.log" 2>&1 || true

step "Health + observability (no secrets)"
curl -fsS http://127.0.0.1:8000/healthz > "$OUT/healthz.json" 2>&1 || true
curl -fsS http://127.0.0.1:8000/readyz > "$OUT/readyz.json" 2>&1 || true
curl -fsS http://127.0.0.1:8000/health/observability > "$OUT/observability.json" 2>&1 || true

step "Env report (LIVE/STUB/SET only — never prints secret values)"
bash /opt/lumaris/deploy/env-report.sh > "$OUT/env-report.txt" 2>&1 || true

step "Nginx + Postgres"
nginx -t > "$OUT/nginx-t.txt" 2>&1 || true
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity;" > "$OUT/pg-activity.txt" 2>&1 || true

tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
rm -rf "$OUT"
echo; echo "Diagnostics: $OUT.tar.gz"
echo "Paste the relevant bits into docs/DEBUG_EXCHANGE.md. This bundle contains NO secrets."
