#!/usr/bin/env bash
# Petabyte one-line node installer (Ubuntu/Debian).
#   PETABYTE_API_URL=https://petabyte.market PETABYTE_API_KEY=pk_your_node_key \
#     bash <(curl -fsSL https://petabyte.market/install.sh)
# The /install page generates this exact command with your key already filled in.
# PRICE_PER_HOUR is optional: leave it unset and the node auto-prices from its GPU's
# benchmark; set it (e.g. PRICE_PER_HOUR=1.5) to pin your own rate.
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

# --- Container egress lockdown (protects the SELLER) -------------------------------
# A buyer's job runs on the seller's machine and network. Left open, it can reach the
# cloud metadata endpoint (169.254.169.254 -> steal the host's IAM/cloud credentials)
# and the seller's own LAN (router admin, NAS, other hosts). We DROP both from
# containers, on the DOCKER-USER chain so it governs all container-forwarded traffic.
# The job cannot remove these rules: the agent runs every job with --cap-drop ALL, so
# it has neither NET_ADMIN nor NET_RAW. Toggle with PETABYTE_LOCKDOWN_EGRESS=false.
if [ "${PETABYTE_LOCKDOWN_EGRESS:-true}" = "true" ]; then
  echo "==> installing container egress firewall (block cloud-metadata + LAN)"
  apt-get install -y iptables >/dev/null 2>&1 || true
  install -m 0755 /dev/stdin /etc/petabyte/egress-firewall.sh <<'FW'
#!/usr/bin/env bash
# Petabyte container egress lockdown. Idempotent: rebuilds a dedicated PB-EGRESS chain
# jumped from DOCKER-USER. Re-applied on boot (docker flushes DOCKER-USER on restart).
set -euo pipefail
command -v iptables >/dev/null || exit 0
iptables -N PB-EGRESS 2>/dev/null || iptables -F PB-EGRESS
# let a container's OWN replies back in (only NEW outbound to the bad nets is dropped)
iptables -A PB-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
# cloud instance metadata service (IMDS) — IAM/credential theft
iptables -A PB-EGRESS -d 169.254.0.0/16 -j DROP
# the seller's own private LAN — pivot / attack of router, NAS, other hosts
iptables -A PB-EGRESS -d 10.0.0.0/8      -j DROP
iptables -A PB-EGRESS -d 192.168.0.0/16  -j DROP
# NOTE: 172.16.0.0/12 is intentionally NOT blocked wholesale — Docker's own bridge
# networks live there and blocking them breaks container DNS/NAT. Operators whose LAN
# is in 172.16/12 should add a scoped rule for their subnet.
iptables -A PB-EGRESS -j RETURN
iptables -C DOCKER-USER -j PB-EGRESS 2>/dev/null || iptables -I DOCKER-USER -j PB-EGRESS
# IPv6 metadata (best-effort; AWS IMDS over v6)
if command -v ip6tables >/dev/null; then
  ip6tables -N PB-EGRESS 2>/dev/null || ip6tables -F PB-EGRESS
  ip6tables -A PB-EGRESS -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  ip6tables -A PB-EGRESS -d fd00:ec2::254/128 -j DROP
  ip6tables -A PB-EGRESS -j RETURN
  ip6tables -C DOCKER-USER -j PB-EGRESS 2>/dev/null || ip6tables -I DOCKER-USER -j PB-EGRESS
fi
echo "petabyte: container egress lockdown applied"
FW
  cat > /etc/systemd/system/petabyte-egress.service <<'UNIT'
[Unit]
Description=Petabyte container egress lockdown (block cloud-metadata + LAN)
After=docker.service
Requires=docker.service
[Service]
Type=oneshot
ExecStart=/etc/petabyte/egress-firewall.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now petabyte-egress.service || /etc/petabyte/egress-firewall.sh || true
fi

echo "==> fetching agent"
mkdir -p "$APP" /etc/petabyte

# Pin the release verification PUBLIC key. The API substitutes it into this script at download
# time; update.sh then requires every future agent bundle to be signed by the matching offline
# key before applying it. If it's empty (unset on the server) we remove the file so auto-update
# stays OFF (fail-closed) rather than trusting TLS alone for code that runs as root.
cat > /etc/petabyte/release_ed25519.pub <<'PBPUBKEY_EOF'
__PETABYTE_RELEASE_PUBKEY_PEM__
PBPUBKEY_EOF
if ! grep -q "BEGIN PUBLIC KEY" /etc/petabyte/release_ed25519.pub 2>/dev/null; then
  rm -f /etc/petabyte/release_ed25519.pub
fi

if [ -f "./task_fetcher.py" ]; then
  cp -r ./* "$APP"/                          # running from inside lumaris_agent/ locally
else
  TMP=$(mktemp -d)
  # Preferred: fetch the agent bundle from OUR server (no GitHub needed => works when the
  # repo is private, and no host ever holds a git credential).
  if curl -fsSL "$PETABYTE_API_URL/agent.tar.gz" -o "$TMP/agent.tar.gz" 2>/dev/null \
     && tar -xzf "$TMP/agent.tar.gz" -C "$TMP" 2>/dev/null && [ -d "$TMP/lumaris_agent" ]; then
    cp -r "$TMP/lumaris_agent/." "$APP"/
  else
    # Fallback: clone the repo (needs access if the repo is private).
    echo "==> agent bundle unavailable, falling back to git clone"
    git clone --depth 1 "$REPO" "$TMP/repo"
    cp -r "$TMP/repo/$SUBDIR/." "$APP"/
  fi
  rm -rf "$TMP"
fi
cd "$APP"
python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

echo "==> registering + attesting this node"
PETABYTE_AGENT_KEY="$KEYF" AGENT_ENV="$ENVF" \
  PETABYTE_API_URL="$PETABYTE_API_URL" PETABYTE_API_KEY="$PETABYTE_API_KEY" \
  PRICE_PER_HOUR="${PRICE_PER_HOUR:-}" UNITS="${UNITS:-1}" GPU_MODEL="${GPU_MODEL:-}" \
  .venv/bin/python provision.py

echo "==> starting service"
cp "$APP/petabyte-agent.service" /etc/systemd/system/petabyte-agent.service
systemctl daemon-reload
systemctl enable --now petabyte-agent

# Auto-update: OFF by default. The current update channel is NOT cryptographically
# signed (see update.sh), so a compromised server or GitHub account could push code
# that runs on this machine. The update channel is Ed25519-signed and fail-closed
# (update.sh refuses unsigned bundles); auto-update stays opt-in as a conservative
# default: set PETABYTE_AUTO_UPDATE=true to enable the 6-hourly timer.
if [ "${PETABYTE_AUTO_UPDATE:-false}" = "true" ] && [ -f "$APP/petabyte-agent-update.service" ]; then
  chmod +x "$APP/update.sh" 2>/dev/null || true
  cp "$APP/petabyte-agent-update.service" /etc/systemd/system/petabyte-agent-update.service
  cp "$APP/petabyte-agent-update.timer" /etc/systemd/system/petabyte-agent-update.timer
  systemctl daemon-reload
  systemctl enable --now petabyte-agent-update.timer
  echo "==> auto-update ENABLED (petabyte-agent-update.timer, every 6h)."
  echo "    Updates are signature-verified against a pinned key (see update.sh)."
else
  echo "==> auto-update disabled (opt-in). Update manually with: petabyte update"
  echo "    or re-run the installer with PETABYTE_AUTO_UPDATE=true to opt in."
fi

echo "✅ node online. logs: journalctl -u petabyte-agent -f"
