#!/usr/bin/env bash
# Deterministic investor demo: validate deps -> build schema -> seed labelled demo
# data -> health-check -> print accounts + URLs -> serve. Ctrl-C stops the server.
#
#   ./demo_run.sh          # seed (if empty) + serve
#   ./demo_run.sh reset    # wipe + reseed, then serve
#   ./demo_run.sh seed     # wipe + reseed only (no server)
#
# No paid credentials required — everything runs on the sandbox ledger + stubs.
set -euo pipefail
cd "$(dirname "$0")"

RED=$'\e[31m'; GRN=$'\e[32m'; YEL=$'\e[33m'; OFF=$'\e[0m'
die() { echo "${RED}✗ $*${OFF}" >&2; exit 1; }
info() { echo "${GRN}▸ $*${OFF}"; }

PORT="${DEMO_PORT:-8000}"
HOST="${DEMO_HOST:-127.0.0.1}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./demo.db}"
export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://${HOST}:${PORT}}"
export DEMO_API_URL="$PUBLIC_BASE_URL"

# ---- 1. validate dependencies ---------------------------------------------
command -v python3 >/dev/null || die "python3 not found. Install Python 3.11+ and retry."
PYBIN=python3
if [ -x .venv/bin/python ]; then PYBIN=.venv/bin/python; fi
$PYBIN - <<'PY' 2>/dev/null || die "Python deps missing. Run: pip install -r requirements.txt (or ./quickstart.sh)"
import fastapi, uvicorn, sqlalchemy, jose, cryptography, httpx  # noqa
PY
command -v "$PYBIN" >/dev/null || die "python interpreter not runnable"
info "dependencies OK ($($PYBIN --version 2>&1))"

# ---- 2. stable demo secrets shared by BOTH the seeder and the server -------
# (Fixed for the run so API keys minted at seed time stay decryptable by the server.)
export SECRET_KEY="${SECRET_KEY:-demo-secret-not-for-production-$RANDOM}"
export SERVER_PRIVATE_KEY="${SERVER_PRIVATE_KEY:-$($PYBIN -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')}"
export PAYMENTS_MODE="${PAYMENTS_MODE:-sandbox}"
export PAYOUT_STUB=true NOTIFY_STUB=true S3_STUB=true GOOGLE_OAUTH_STUB=true
export WG_PUBLIC_KEY="${WG_PUBLIC_KEY:-demoWGpublickeybase64==}" WG_ENDPOINT="${WG_ENDPOINT:-vpn.demo.local}"
export PAYMENT_WEBHOOK_SECRET="${PAYMENT_WEBHOOK_SECRET:-whsec_demo}"
export REAPER_DISABLED=true
export TRUSTED_PROXIES="${TRUSTED_PROXIES:-testclient,127.0.0.1,::1}"
export ADMIN_USERS="${ADMIN_USERS:-demo_admin@petabyte.market}"
export ENVIRONMENT=development
export GEOIP_STUB='{"10.1.1.1":"DE","10.3.3.3":"US","10.4.4.4":"SA"}'

CMD="${1:-serve}"

# ---- 3. seed (build schema + labelled demo entities) ----------------------
if [ "$CMD" = "reset" ] || [ "$CMD" = "seed" ] || [ ! -f demo.db ]; then
  info "seeding demo data (schema + clearly-labelled demo entities)…"
  $PYBIN demo.py seed || die "seeding failed — see the traceback above."
fi

if [ "$CMD" = "seed" ]; then
  info "seed complete. Start the server with: ./demo_run.sh"
  exit 0
fi

# ---- 4. start the server ---------------------------------------------------
info "starting API on ${HOST}:${PORT}…"
$PYBIN -m uvicorn main:app --host "$HOST" --port "$PORT" --log-level warning &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT INT TERM

# ---- 5. health check with actionable failure ------------------------------
ready=0
for i in $(seq 1 30); do
  if curl -fsS "http://${HOST}:${PORT}/healthz" >/dev/null 2>&1; then ready=1; break; fi
  if ! kill -0 $SRV 2>/dev/null; then die "server exited during startup — check the log above."; fi
  sleep 0.5
done
[ "$ready" = 1 ] || die "server did not become healthy within 15s on ${HOST}:${PORT} (port in use?)."

# ---- 6. print the demo guide ----------------------------------------------
$PYBIN demo.py info || true
echo "${YEL}Server is live. Press Ctrl-C to stop.${OFF}"
wait $SRV
