#!/usr/bin/env bash
# seller_setup.sh — turn the seller GPU Droplet into a live Petabyte node.
#
# Run this ON the seller Droplet (165.22.236.63), as root. It:
#   1. mints a node API key for the seller account (if you don't already have one),
#   2. runs the official one-line installer (detects GPU, attests, registers, starts
#      the systemd agent), and
#   3. verifies GPU + Docker-GPU + agent health.
#
# Secrets: the seller password is read with `read -s` (never echoed, never in argv,
# never in shell history). The minted key is written to /etc/petabyte/agent.env
# (chmod 600) by the installer. Do NOT paste the key into chat or commit it.
#
# Usage:
#   PETABYTE_API_URL=https://petabyte.market SELLER_USER=testUserSeller \
#   PRICE_PER_HOUR=1.5 bash scripts/e2e/seller_setup.sh
set -euo pipefail

API_URL="${PETABYTE_API_URL:-https://petabyte.market}"
SELLER_USER="${SELLER_USER:-testUserSeller}"
PRICE_PER_HOUR="${PRICE_PER_HOUR:-1.5}"

echo "== Petabyte seller setup =="
echo "API:   $API_URL"
echo "User:  $SELLER_USER"
echo

# 0) Pre-flight: this box must actually have a GPU.
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "WARNING: nvidia-smi not found. Install the NVIDIA driver first, or set"
  echo "         GPU_MODEL=/GPU_COUNT=/VRAM_GB= to override detection."
else
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
fi
echo

# 1) Mint a node API key (scopes: node,jobs) unless one was supplied.
if [ -z "${PETABYTE_API_KEY:-}" ]; then
  echo "No PETABYTE_API_KEY supplied — logging in as $SELLER_USER to mint one."
  printf 'Seller password (input hidden): '
  read -rs SELLER_PASS; echo
  # OAuth2 password grant -> bearer token (form-encoded).
  TOKEN=$(curl -fsS -X POST "$API_URL/login" \
            --data-urlencode "username=$SELLER_USER" \
            --data-urlencode "password=$SELLER_PASS" \
          | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
  unset SELLER_PASS
  PETABYTE_API_KEY=$(curl -fsS -X POST \
            "$API_URL/create_api_key?days=90&scopes=node,jobs&label=seller-gpu-droplet" \
            -H "Authorization: Bearer $TOKEN" \
          | python3 -c 'import sys,json;print(json.load(sys.stdin)["api_key"])')
  unset TOKEN
  echo "Minted a 90-day node key (value hidden)."
fi

# 2) Run the official installer (detects GPU, attests with Ed25519, registers spec,
#    installs+starts the petabyte-agent systemd service). See lumaris_agent/INSTALL.md.
echo
echo "Running the node installer..."
PETABYTE_API_URL="$API_URL" \
PETABYTE_API_KEY="$PETABYTE_API_KEY" \
PRICE_PER_HOUR="$PRICE_PER_HOUR" \
UNITS="${UNITS:-1}" MAX_HOURS="${MAX_HOURS:-24}" \
bash <(curl -fsSL "$API_URL/install.sh")
unset PETABYTE_API_KEY

# 3) Verify.
echo
echo "== Verification =="
systemctl status petabyte-agent --no-pager || true
echo "--- last agent logs ---"
journalctl -u petabyte-agent -n 20 --no-pager || true
echo "--- Docker GPU smoke (should print nvidia-smi from inside a container) ---"
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi || \
  echo "Docker-GPU test failed — install nvidia-container-toolkit (the agent installer does this)."

echo
echo "Done. Confirm the node is attested + live from the buyer side:"
echo "  curl -s \"$API_URL/marketplace/specs\" | python3 -m json.tool | less"
