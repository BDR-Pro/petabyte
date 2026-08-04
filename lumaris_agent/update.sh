#!/usr/bin/env bash
# Petabyte node agent — pull the latest agent code from the monorepo and restart
# if it changed. Installed as a systemd timer (petabyte-agent-update.timer).
#
# SECURITY — READ THIS. This channel is NOT cryptographically signed yet. TLS
# authenticates the transport, but a compromised API server or GitHub account could
# still push code that runs on this machine. Before this runs unattended in the field:
#   1. Sign the agent bundle with a release Ed25519 key at publish time.
#   2. Ship that PUBLIC key inside the installer (pin it; never fetch it at runtime).
#   3. Verify the signature here, BEFORE rsync, and abort on mismatch.
# Until then the installer leaves this timer DISABLED unless PETABYTE_AUTO_UPDATE=true.
# The pinned key path below is honoured when present so signing can be rolled out
# without changing this script again.
set -euo pipefail
REPO="${PETABYTE_REPO:-https://github.com/BDR-Pro/petabyte.git}"
SUBDIR="${PETABYTE_AGENT_SUBDIR:-lumaris_agent}"
APP=/opt/petabyte-agent
SERVICE=petabyte-agent
PUBKEY="${PETABYTE_RELEASE_PUBKEY:-/etc/petabyte/release_ed25519.pub}"

command -v rsync >/dev/null || { echo "rsync missing"; exit 0; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

verify_bundle() {  # verify_bundle <bundle> <sigfile> — 0 ok, 1 fail/unavailable
  local bundle="$1" sig="$2"
  [ -f "$PUBKEY" ] && [ -f "$sig" ] || return 1
  command -v openssl >/dev/null || return 1
  openssl pkeyutl -verify -pubin -inkey "$PUBKEY" \
    -rawin -in "$bundle" -sigfile "$sig" >/dev/null 2>&1
}

# Prefer OUR server's agent bundle (works when the repo is private; no git creds on hosts).
# The API URL was written to the agent env file at provision time.
API_URL="$(grep -E '^PETABYTE_API_URL=' /etc/petabyte/agent.env 2>/dev/null | cut -d= -f2-)"
if [ -n "$API_URL" ] \
   && curl -fsSL "$API_URL/agent.tar.gz" -o "$TMP/agent.tar.gz" 2>/dev/null \
   && tar -xzf "$TMP/agent.tar.gz" -C "$TMP" 2>/dev/null && [ -d "$TMP/$SUBDIR" ]; then
  # If a pinned release key is present, the bundle MUST verify against its signature.
  # (When no key is pinned we fall back to TLS-only trust — the documented interim state.)
  if [ -f "$PUBKEY" ]; then
    curl -fsSL "$API_URL/agent.tar.gz.sig" -o "$TMP/agent.tar.gz.sig" 2>/dev/null || true
    if ! verify_bundle "$TMP/agent.tar.gz" "$TMP/agent.tar.gz.sig"; then
      echo "SECURITY: agent bundle signature did not verify against $PUBKEY — refusing update"; exit 1
    fi
  fi
else
  # Fallback: clone the repo (needs access if private).
  git clone --depth 1 "$REPO" "$TMP" 2>/dev/null || { echo "fetch failed"; exit 0; }
fi

RSYNC_EXCL=(--exclude .venv --exclude '*.env' --exclude '*.log' --exclude __pycache__ --exclude .git)
if rsync -rcn "${RSYNC_EXCL[@]}" "$TMP/$SUBDIR/" "$APP/" | grep -q . ; then
  rsync -rc "${RSYNC_EXCL[@]}" "$TMP/$SUBDIR/" "$APP/"
  "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt" || true
  systemctl restart "$SERVICE"
  echo "agent updated and restarted"
else
  echo "already up to date"
fi
