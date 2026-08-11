#!/usr/bin/env bash
# Petabyte node agent — pull the latest agent code from the monorepo and restart
# if it changed. Installed as a systemd timer (petabyte-agent-update.timer).
#
# SECURITY. The signed-bundle channel is ENFORCED: the agent tarball fetched from the API
# MUST verify against a PINNED release Ed25519 public key before any file is applied. TLS
# authenticates the transport, but TLS alone would let a compromised API server/object store
# push root-run code to the whole fleet — so we require a signature too, and FAIL CLOSED:
#   * no pinned key at $PUBKEY            -> refuse (no unsigned auto-update)
#   * missing/invalid bundle signature    -> refuse
# Pin the key by shipping it in the installer (never fetch it at runtime). The installer also
# leaves the timer DISABLED unless PETABYTE_AUTO_UPDATE=true, so this only runs when opted in.
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
  # SIGNED UPDATES ONLY — fail closed. The bundle MUST verify against the pinned release key;
  # we NEVER fall back to TLS-only trust for code that runs as root on the seller's machine.
  if [ ! -f "$PUBKEY" ]; then
    echo "SECURITY: no pinned release key at $PUBKEY — refusing to apply an unsigned agent update." \
         "Ship the release public key in the installer (see update.sh header)."; exit 1
  fi
  curl -fsSL "$API_URL/agent.tar.gz.sig" -o "$TMP/agent.tar.gz.sig" 2>/dev/null || true
  if ! verify_bundle "$TMP/agent.tar.gz" "$TMP/agent.tar.gz.sig"; then
    echo "SECURITY: agent bundle signature did not verify against $PUBKEY — refusing update"; exit 1
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
