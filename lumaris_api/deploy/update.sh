#!/usr/bin/env bash
# Pull the latest API code and restart the services. Called by the GitHub Actions
# deploy workflow over SSH (or run by hand). Requires /opt/lumaris to be a git
# checkout (see AUTO_DEPLOY.md for the one-time setup).
set -euo pipefail
APP=/opt/lumaris
cd "$APP"

if [ ! -d .git ]; then
  echo "ERROR: $APP is not a git checkout. See deploy/AUTO_DEPLOY.md (one-time setup)."; exit 1
fi

before=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only
after=$(git rev-parse HEAD 2>/dev/null || echo none)

if [ "$before" = "$after" ]; then
  echo "no change ($after) — restarting anyway to pick up env edits"
fi

# reinstall deps only if requirements changed
if ! git diff --quiet "$before" "$after" -- requirements.txt 2>/dev/null; then
  echo "==> requirements changed — reinstalling"
  sudo -u lumaris "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
fi

# apply DB migrations (no-op if already at head)
sudo -u lumaris env $(grep -v '^#' /etc/lumaris/lumaris.env | xargs) \
  "$APP/.venv/bin/alembic" upgrade head || true

chown -R lumaris:lumaris "$APP"
systemctl restart lumaris-api lumaris-reaper
echo "deployed ${before:0:7} -> ${after:0:7}"
