#!/usr/bin/env bash
# wireguard-server.sh — turn a fresh Linux VM into the Petabyte WireGuard VPN server.
#
# This is the peer that buyers connect to: /vpn_config/<booking> and /jobs/<job>/vpn_config
# hand out CLIENT configs whose [Peer] is THIS server's public key + endpoint. Running this
# script produces the three values the API needs (WG_PUBLIC_KEY, WG_ENDPOINT, WG_APPLY=true)
# and prints them at the end so you can drop them straight into the API's environment.
#
# Idempotent: safe to re-run. It never prints or persists the server PRIVATE key anywhere the
# API can read it — the API only ever needs the PUBLIC key.
#
# Usage:   sudo ./wireguard-server.sh
# Env:     WG_INTERFACE (default wg0)  WG_PORT (default 51820)  WG_SUBNET (default 10.0.0.0/24)
#          WG_SERVER_ADDR (default 10.0.0.1/24)  WAN_IF (auto-detected default route iface)
set -euo pipefail

WG_INTERFACE="${WG_INTERFACE:-wg0}"
WG_PORT="${WG_PORT:-51820}"
WG_SUBNET="${WG_SUBNET:-10.0.0.0/24}"
WG_SERVER_ADDR="${WG_SERVER_ADDR:-10.0.0.1/24}"
WG_DIR="/etc/wireguard"
CONF="${WG_DIR}/${WG_INTERFACE}.conf"

if [[ $EUID -ne 0 ]]; then echo "run as root (sudo)"; exit 1; fi

# 1) Install WireGuard (Debian/Ubuntu or RHEL/Fedora).
if ! command -v wg >/dev/null 2>&1; then
  echo "→ installing wireguard..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y && apt-get install -y wireguard wireguard-tools iptables
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y wireguard-tools iptables
  else
    echo "unsupported distro — install 'wireguard-tools' manually"; exit 1
  fi
fi

# 2) Server keypair (generated once; private key stays 0600 root-only, never leaves the box).
umask 077; mkdir -p "$WG_DIR"
if [[ ! -f "${WG_DIR}/server_private.key" ]]; then
  echo "→ generating server keypair..."
  wg genkey | tee "${WG_DIR}/server_private.key" | wg pubkey > "${WG_DIR}/server_public.key"
fi
SRV_PRIV="$(cat "${WG_DIR}/server_private.key")"
SRV_PUB="$(cat "${WG_DIR}/server_public.key")"

# 3) Detect the WAN interface (for NAT) and this host's public endpoint.
WAN_IF="${WAN_IF:-$(ip route show default 2>/dev/null | awk '/default/{print $5; exit}')}"
WAN_IF="${WAN_IF:-eth0}"
PUB_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
PUB_IP="${PUB_IP:-$(ip -4 addr show "$WAN_IF" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1)}"

# 4) Interface config. PostUp/PostDown add the NAT + forwarding rules so peers can reach the
#    workloads (and, if AllowedIPs=0.0.0.0/0 on the client, the internet) through this server.
if [[ ! -f "$CONF" ]]; then
  echo "→ writing ${CONF}..."
  cat > "$CONF" <<EOF
[Interface]
Address = ${WG_SERVER_ADDR}
ListenPort = ${WG_PORT}
PrivateKey = ${SRV_PRIV}
PostUp   = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -s ${WG_SUBNET} -o ${WAN_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -s ${WG_SUBNET} -o ${WAN_IF} -j MASQUERADE
# Peers are added at runtime by the API (wg set ... peer <pubkey> allowed-ips <ip>/32) when
# WG_APPLY=true, so nothing to list here at boot.
EOF
  chmod 600 "$CONF"
fi

# 5) Kernel IP forwarding (persisted).
echo "→ enabling ip forwarding..."
sysctl -qw net.ipv4.ip_forward=1
grep -q '^net.ipv4.ip_forward=1' /etc/sysctl.conf 2>/dev/null || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf

# 6) Open the UDP port if a firewall is active (best-effort).
command -v ufw >/dev/null 2>&1 && ufw allow "${WG_PORT}/udp" >/dev/null 2>&1 || true

# 7) Bring it up on boot + now (idempotent).
echo "→ starting wg-quick@${WG_INTERFACE}..."
systemctl enable "wg-quick@${WG_INTERFACE}" >/dev/null 2>&1 || true
systemctl restart "wg-quick@${WG_INTERFACE}" 2>/dev/null || wg-quick up "$WG_INTERFACE" || true

echo
echo "======================================================================"
echo " WireGuard VPN server is up on UDP ${WG_PORT} (${WG_INTERFACE})."
echo
echo " Put these in the Petabyte API environment so /vpn_config hands clients"
echo " a config that points at THIS server (the private key never leaves here):"
echo
echo "   WG_PUBLIC_KEY=${SRV_PUB}"
echo "   WG_ENDPOINT=${PUB_IP:-<this-server-public-ip>}"
echo "   WG_INTERFACE=${WG_INTERFACE}"
echo "   WG_APPLY=true        # let the API push buyer peers with 'wg set'"
echo "======================================================================"
