#!/usr/bin/env bash
# Petabyte node agent — pull the latest code and restart if it changed.
# Installed as a systemd timer (petabyte-agent-update.timer) by install.sh.
set -euo pipefail
APP=/opt/petabyte-agent
SERVICE=petabyte-agent
cd "$APP" 2>/dev/null || { echo "agent dir $APP missing"; exit 0; }

if [ ! -d .git ]; then
  echo "not a git checkout — reinstall via install.sh to enable auto-update"; exit 0
fi

before=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only 2>/dev/null || { echo "pull failed (local changes?)"; exit 0; }
after=$(git rev-parse HEAD 2>/dev/null || echo none)

if [ "$before" = "$after" ]; then
  echo "already up to date ($after)"; exit 0
fi

# reinstall deps only if requirements changed, then restart
if ! git diff --quiet "$before" "$after" -- requirements.txt 2>/dev/null; then
  .venv/bin/pip install -q -r requirements.txt || true
fi
systemctl restart "$SERVICE"
echo "updated ${before:0:7} -> ${after:0:7} and restarted $SERVICE"
