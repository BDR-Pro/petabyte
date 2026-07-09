#!/usr/bin/env bash
# One-time local setup: venv, deps, secrets, .env (SQLite dev).
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install -q -U pip
pip install -q fastapi uvicorn "python-jose[cryptography]" bcrypt cryptography \
    sqlalchemy "pydantic>=2" python-multipart python-dotenv httpx alembic

# Generate a server WireGuard keypair (public goes in .env; keep private on the VPN host only)
read WG_PRIV WG_PUB < <(python - <<'PY'
import base64
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization
k=X25519PrivateKey.generate()
priv=base64.b64encode(k.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())).decode()
pub=base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
print(priv, pub)
PY
)

cat > .env <<ENV
DATABASE_URL=sqlite:///./dev.db
SECRET_KEY=$(openssl rand -hex 32)
SERVER_PRIVATE_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
PLATFORM_TAKE_RATE=0.10
HEARTBEAT_TIMEOUT_S=60
WG_PUBLIC_KEY=$WG_PUB
WG_ENDPOINT=vpn.lumaris.example
WG_APPLY=false
WG_INTERFACE=wg0
ENV

echo "✅ .env written. Server WG PRIVATE key (store on the VPN host, NOT in this API):"
echo "   $WG_PRIV"
echo "Run:  source .venv/bin/activate && uvicorn main:app --reload"
