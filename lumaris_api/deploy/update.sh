#!/usr/bin/env bash
# Pull the latest code from the monorepo checkout and redeploy the API. Called by
# the GitHub Actions deploy workflow over SSH (or run by hand). See AUTO_DEPLOY.md.
set -euo pipefail
APP=/opt/lumaris                          # running app dir (services point here)

# Find the monorepo git checkout. Honour an explicit PETABYTE_SRC, otherwise probe the
# known locations — the checkout has historically lived at /root/petabyte on this box and
# /opt/petabyte in the docs, so we stop guessing and just look. This is why deploys used
# to fail with "not a git checkout" unless you passed PETABYTE_SRC by hand.
SRC=""
for _cand in "${PETABYTE_SRC:-}" /root/petabyte /opt/petabyte /home/petabyte/petabyte; do
  [ -n "$_cand" ] && [ -d "$_cand/.git" ] && { SRC="$_cand"; break; }
done
if [ -z "$SRC" ]; then
  echo "ERROR: could not find the petabyte git checkout." >&2
  echo "Looked in: \${PETABYTE_SRC:-<unset>}, /root/petabyte, /opt/petabyte, /home/petabyte/petabyte" >&2
  echo "Fix: clone it, or run with PETABYTE_SRC=/path/to/petabyte. See deploy/AUTO_DEPLOY.md." >&2
  exit 1
fi
echo "==> source checkout: $SRC"
cd "$SRC"
before=$(git rev-parse HEAD 2>/dev/null || echo none)
git pull --ff-only
after=$(git rev-parse HEAD 2>/dev/null || echo none)

# sync only the API into the app dir (never touch venv, db, or env)
rsync -rc --exclude .venv --exclude '*.db' --exclude '*.db-*' --exclude '.env' \
      --exclude __pycache__ --exclude .git "$SRC/lumaris_api/" "$APP/"

# bundle the node installers so /install.sh and /install.ps1 serve on the deployed host
mkdir -p "$APP/installers"
cp "$SRC/lumaris_agent/install.sh" "$SRC/lumaris_agent/install.ps1" "$SRC/lumaris_agent/manage.ps1" "$SRC/lumaris_agent/uninstall.sh" "$APP/installers/" 2>/dev/null || true
# Bundle the agent CODE into a tarball the API serves at /agent.tar.gz, so the node
# installer never has to clone GitHub (works when the repo is private; no creds on hosts).
tar -czf "$APP/installers/agent.tar.gz" -C "$SRC" lumaris_agent 2>/dev/null || true

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

# refresh systemd units if they changed in this pull, then reload. Covers the API plus the
# payout worker service+timer, so an existing box that predates the payout timer picks it up
# on its next deploy (previously only lumaris-api.service was synced, so queued withdrawals
# never sent on already-provisioned hosts).
_units_changed=0
for _u in lumaris-api.service lumaris-payout.service lumaris-payout.timer; do
  if [ -f "$APP/deploy/$_u" ] && ! cmp -s "$APP/deploy/$_u" "/etc/systemd/system/$_u" 2>/dev/null; then
    echo "==> systemd unit changed — updating $_u"
    cp "$APP/deploy/$_u" "/etc/systemd/system/$_u"
    _units_changed=1
  fi
done
[ "$_units_changed" = 1 ] && systemctl daemon-reload
# Ensure the payout timer is armed (idempotent — no-op if already enabled/running).
systemctl enable --now lumaris-payout.timer >/dev/null 2>&1 || true

# NOTE: nginx conf is intentionally NOT auto-copied — certbot rewrites that file when
# you enable HTTPS, so overwriting it would wipe the SSL block. If you change
# deploy/nginx-lumaris.conf, apply it by hand: sudo cp ... && sudo nginx -t && reload.

systemctl restart lumaris-api lumaris-reaper
echo "deployed ${before:0:7} -> ${after:0:7}"

# Print the env health report at the end of every deploy. Inside GitHub Actions this
# also lands in the job Step Summary, so you can read it on github.com without SSH.
bash "$APP/deploy/env-report.sh" || true
