#!/usr/bin/env bash
# Petabyte node agent — pull the latest agent code from the monorepo and restart
# if it changed. Installed as a systemd timer (petabyte-agent-update.timer).
set -euo pipefail
REPO="${PETABYTE_REPO:-https://github.com/BDR-Pro/petabyte.git}"
SUBDIR="${PETABYTE_AGENT_SUBDIR:-lumaris_agent}"
APP=/opt/petabyte-agent
SERVICE=petabyte-agent

command -v rsync >/dev/null || { echo "rsync missing"; exit 0; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# Prefer OUR server's agent bundle (works when the repo is private; no git creds on hosts).
# The API URL was written to the agent env file at provision time.
API_URL="$(grep -E '^PETABYTE_API_URL=' /etc/petabyte/agent.env 2>/dev/null | cut -d= -f2-)"
if [ -n "$API_URL" ] \
   && curl -fsSL "$API_URL/agent.tar.gz" -o "$TMP/agent.tar.gz" 2>/dev/null \
   && tar -xzf "$TMP/agent.tar.gz" -C "$TMP" 2>/dev/null && [ -d "$TMP/$SUBDIR" ]; then
  :  # bundle unpacked to $TMP/$SUBDIR, same layout the rest of this script expects
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
