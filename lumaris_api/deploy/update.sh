#!/usr/bin/env bash
# Pull the latest code from the monorepo checkout and redeploy the API. Called by
# the GitHub Actions deploy workflow over SSH (or run by hand). See AUTO_DEPLOY.md.
set -euo pipefail
SRC="${PETABYTE_SRC:-/opt/petabyte}"     # monorepo git checkout (repo root)
APP=/opt/lumaris                          # running app dir (services point here)

[ -d "$SRC/.git" ] || { echo "ERROR: $SRC is not a git checkout. See deploy/AUTO_DEPLOY.md."; exit 1; }
cd "$SRC"
before=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only
after=$(git rev-parse HEAD 2>/dev/null || echo none)

# sync only the API into the app dir (never touch venv, db, or env)
rsync -rc --exclude .venv --exclude '*.db' --exclude '*.db-*' --exclude '.env' \
      --exclude __pycache__ --exclude .git "$SRC/lumaris_api/" "$APP/"

# reinstall deps only if requirements changed
if ! git diff --quiet "$before" "$after" -- lumaris_api/requirements.txt 2>/dev/null; then
  echo "==> requirements changed — reinstalling"
  sudo -u lumaris "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
fi

# schema: the app runs create_all() on startup, so fresh tables appear on restart.
# Only run Alembic if migrations are actually present (for altering existing tables).
if [ -d "$APP/alembic/versions" ] && ls "$APP"/alembic/versions/*.py >/dev/null 2>&1; then
  sudo -u lumaris env HOME=/run/lumaris $(grep -v '^#' /etc/lumaris/lumaris.env | xargs) \
    "$APP/.venv/bin/alembic" upgrade head || true
fi

chown -R lumaris:lumaris "$APP"

# refresh the systemd unit if it changed in this pull, then reload
if ! cmp -s "$APP/deploy/lumaris-api.service" /etc/systemd/system/lumaris-api.service 2>/dev/null; then
  echo "==> service unit changed — updating"
  cp "$APP/deploy/lumaris-api.service" /etc/systemd/system/lumaris-api.service
  systemctl daemon-reload
fi

# NOTE: nginx conf is intentionally NOT auto-copied — certbot rewrites that file when
# you enable HTTPS, so overwriting it would wipe the SSL block. If you change
# deploy/nginx-lumaris.conf, apply it by hand: sudo cp ... && sudo nginx -t && reload.

systemctl restart lumaris-api lumaris-reaper
echo "deployed ${before:0:7} -> ${after:0:7}"
