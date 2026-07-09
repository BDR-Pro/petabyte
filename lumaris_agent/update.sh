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
git clone --depth 1 "$REPO" "$TMP" 2>/dev/null || { echo "fetch failed"; exit 0; }

RSYNC_EXCL=(--exclude .venv --exclude '*.env' --exclude '*.log' --exclude __pycache__ --exclude .git)
if rsync -rcn "${RSYNC_EXCL[@]}" "$TMP/$SUBDIR/" "$APP/" | grep -q . ; then
  rsync -rc "${RSYNC_EXCL[@]}" "$TMP/$SUBDIR/" "$APP/"
  "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt" || true
  systemctl restart "$SERVICE"
  echo "agent updated and restarted"
else
  echo "already up to date"
fi
