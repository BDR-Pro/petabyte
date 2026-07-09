#!/usr/bin/env bash
# Provision Lumaris on a fresh Ubuntu 24.04 DigitalOcean droplet.
# Run as root from inside the extracted bundle:  sudo bash deploy/deploy.sh
set -euo pipefail

APP_USER=lumaris
APP_DIR=/opt/lumaris
ENV_DIR=/etc/lumaris
ENV_FILE=$ENV_DIR/lumaris.env
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # bundle root

echo "==> Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip postgresql nginx \
    certbot python3-certbot-nginx ufw git curl wireguard-tools rsync

echo "==> Creating service user and dirs"
id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR" "$ENV_DIR"

echo "==> Syncing application to $APP_DIR"
rsync -a --delete \
  --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
  --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
  "$SRC_DIR"/ "$APP_DIR"/

echo "==> Python venv + dependencies"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -U pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> PostgreSQL role + database (idempotent)"
DB_PASS_FILE=$ENV_DIR/.dbpass
if [[ ! -f "$DB_PASS_FILE" ]]; then openssl rand -hex 24 > "$DB_PASS_FILE"; chmod 600 "$DB_PASS_FILE"; fi
DB_PASS="$(cat "$DB_PASS_FILE")"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='lumaris'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE USER lumaris WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='lumaris'" | grep -q 1 \
  || sudo -u postgres createdb -O lumaris lumaris

echo "==> Secrets + env file (generated once, preserved on re-run)"
if [[ ! -f "$ENV_FILE" ]]; then
  SECRET_KEY="$(openssl rand -hex 32)"
  FERNET="$("$APP_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
  # server WireGuard keypair: PUBLIC goes in env; PRIVATE saved separately for the VPN host
  read WG_PRIV WG_PUB < <("$APP_DIR/.venv/bin/python" - <<'PY'
import base64
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
k=X25519PrivateKey.generate()
print(base64.b64encode(k.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode(),
      base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode())
PY
)
  PUBIP="$(curl -s ifconfig.me || echo your.droplet.ip)"
  cat > "$ENV_FILE" <<ENV
DATABASE_URL=postgresql+psycopg2://lumaris:$DB_PASS@localhost:5432/lumaris
SECRET_KEY=$SECRET_KEY
SERVER_PRIVATE_KEY=$FERNET
PLATFORM_TAKE_RATE=0.10
MIN_REPUTATION=50
HEARTBEAT_TIMEOUT_S=60
PAYMENTS_MODE=sandbox
PAYMENT_WEBHOOK_SECRET=
AWS_REFERENCE_PRICE=12.29
ALLOWED_ORIGINS=
BACKUP_RESCHEDULE_GRACE_S=900
# --- Object storage for backups (the API mints pre-signed URLs; nodes get NO keys) ---
S3_BUCKET=
S3_REGION=us-east-1
S3_ENDPOINT=
AWS_ACCESS_KEY_ID=__SET_ME__
AWS_SECRET_ACCESS_KEY=__SET_ME__
REAPER_DISABLED=true
REAPER_INTERVAL_S=20
WEB_CONCURRENCY=3
WG_PUBLIC_KEY=$WG_PUB
WG_ENDPOINT=$PUBIP
WG_APPLY=false
WG_INTERFACE=wg0
LOG_LEVEL=info
ENV
  echo "$WG_PRIV" > "$ENV_DIR/wg_server_private.key"; chmod 600 "$ENV_DIR/wg_server_private.key"
  echo "    Server WG PRIVATE key saved to $ENV_DIR/wg_server_private.key (move to your VPN host)"
fi
chown -R "$APP_USER:$APP_USER" "$ENV_DIR" "$APP_DIR"
chmod 600 "$ENV_FILE"

echo "==> Creating database tables"
( cd "$APP_DIR" && sudo -u "$APP_USER" env $(grep -v '^#' "$ENV_FILE" | xargs) "$APP_DIR/.venv/bin/python" -c "from db import init_db; init_db()" )

echo "==> Installing systemd services"
cp "$APP_DIR/deploy/lumaris-api.service" /etc/systemd/system/
cp "$APP_DIR/deploy/lumaris-reaper.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lumaris-api lumaris-reaper

echo "==> Configuring nginx"
cp "$APP_DIR/deploy/nginx-lumaris.conf" /etc/nginx/sites-available/lumaris
ln -sf /etc/nginx/sites-available/lumaris /etc/nginx/sites-enabled/lumaris
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Firewall"
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
yes | ufw enable >/dev/null 2>&1 || true

echo ""
echo "✅ Deployed. Check: systemctl status lumaris-api"
echo "   Smoke:  curl -s http://localhost/healthz"
echo ""
echo "Next:"
echo "  1) Point your domain's A record at this droplet."
echo "  2) Edit server_name in /etc/nginx/sites-available/lumaris, reload nginx."

# --- Create + harden the backup bucket if S3_BUCKET is set and creds are present ---
set +e
source /etc/lumaris/lumaris.env 2>/dev/null
if [ -n "${S3_BUCKET:-}" ] && [ "${AWS_ACCESS_KEY_ID:-__SET_ME__}" != "__SET_ME__" ]; then
  if command -v aws >/dev/null 2>&1; then
    echo "==> ensuring backup bucket s3://$S3_BUCKET"
    if ! aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
      if [ "${S3_REGION:-us-east-1}" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$S3_BUCKET"
      else
        aws s3api create-bucket --bucket "$S3_BUCKET" --region "$S3_REGION" \
          --create-bucket-configuration LocationConstraint="$S3_REGION"
      fi
    fi
    # Harden: block public access, versioning (recover overwrites), default encryption
    aws s3api put-public-access-block --bucket "$S3_BUCKET" --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    aws s3api put-bucket-versioning --bucket "$S3_BUCKET" \
      --versioning-configuration Status=Enabled
    aws s3api put-bucket-encryption --bucket "$S3_BUCKET" --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
    # TLS-only bucket policy
    aws s3api put-bucket-policy --bucket "$S3_BUCKET" --policy "{
      \"Version\":\"2012-10-17\",
      \"Statement\":[{\"Sid\":\"DenyInsecureTransport\",\"Effect\":\"Deny\",
        \"Principal\":\"*\",\"Action\":\"s3:*\",
        \"Resource\":[\"arn:aws:s3:::$S3_BUCKET\",\"arn:aws:s3:::$S3_BUCKET/*\"],
        \"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
    # Expire old backups after 30 days
    aws s3api put-bucket-lifecycle-configuration --bucket "$S3_BUCKET" --lifecycle-configuration \
      '{"Rules":[{"ID":"expire-old-backups","Status":"Enabled","Filter":{"Prefix":"backups/"},"Expiration":{"Days":30}}]}'
    echo "    bucket hardened (private, versioned, TLS-only, SSE, 30d lifecycle)"
  else
    echo "WARN: S3_BUCKET set but 'aws' CLI not installed; skipping bucket bootstrap"
  fi
fi
set -e

echo "  3) Enable HTTPS:  certbot --nginx -d api.yourdomain.com"
