#!/usr/bin/env bash
# Petabyte one-line node installer (Ubuntu/Debian).
#   PETABYTE_API_URL=https://petabyte.market \
#   PETABYTE_API_KEY=pk_your_node_key PRICE_PER_HOUR=1.5 \
#   bash <(curl -fsSL https://petabyte.market/install.sh)
# Create the API key on the /install page (that button also makes you a seller).
set -euo pipefail
: "${PETABYTE_API_URL:?set PETABYTE_API_URL}"
: "${PETABYTE_API_KEY:?set PETABYTE_API_KEY (create one on the /install page)}"
REPO="${PETABYTE_REPO:-https://github.com/BDR-Pro/petabyte.git}"
SUBDIR="${PETABYTE_AGENT_SUBDIR:-lumaris_agent}"
APP=/opt/petabyte-agent
ENVF=/etc/petabyte/agent.env
KEYF=/etc/petabyte/agent_ed25519.key

echo "==> installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv git curl ca-certificates rsync

echo "==> installing Docker (sandbox runtime)"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "==> installing nvidia-container-toolkit (GPU in containers; native + WSL2)"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -y && apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker && systemctl restart docker || true
fi

echo "==> fetching agent"
mkdir -p "$APP" /etc/petabyte
if [ -f "./task_fetcher.py" ]; then
  cp -r ./* "$APP"/                          # running from inside lumaris_agent/ locally
else
  TMP=$(mktemp -d)
  git clone --depth 1 "$REPO" "$TMP"         # monorepo; take only the agent subfolder
  cp -r "$TMP/$SUBDIR/." "$APP"/
  rm -rf "$TMP"
fi
cd "$APP"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "==> registering + attesting this node"
PETABYTE_AGENT_KEY="$KEYF" AGENT_ENV="$ENVF" \
  PETABYTE_API_URL="$PETABYTE_API_URL" PETABYTE_API_KEY="$PETABYTE_API_KEY" \
  PRICE_PER_HOUR="${PRICE_PER_HOUR:-1.0}" UNITS="${UNITS:-1}" GPU_MODEL="${GPU_MODEL:-}" \
  .venv/bin/python provision.py

echo "==> starting service"
cp "$APP/petabyte-agent.service" /etc/systemd/system/petabyte-agent.service
systemctl daemon-reload
systemctl enable --now petabyte-agent

# auto-update: pull latest agent every 6h and restart if changed
if [ -f "$APP/petabyte-agent-update.service" ]; then
  chmod +x "$APP/update.sh" 2>/dev/null || true
  cp "$APP/petabyte-agent-update.service" /etc/systemd/system/petabyte-agent-update.service
  cp "$APP/petabyte-agent-update.timer" /etc/systemd/system/petabyte-agent-update.timer
  systemctl daemon-reload
  systemctl enable --now petabyte-agent-update.timer
  echo "==> auto-update enabled (petabyte-agent-update.timer, every 6h)"
fi

echo "✅ node online. logs: journalctl -u petabyte-agent -f"
