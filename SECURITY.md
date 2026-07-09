# ⚠️ Rotate the leaked secrets immediately

The uploaded `lumaris_api-master/.env` contained **real secrets committed to the
repo**: `WG_PRIVATE_KEY`, `SECRET_KEY` (JWT signing), and `SERVER_PRIVATE_KEY`
(API-key Fernet). Anyone with that file can forge JWTs and API keys and
impersonate your VPN server. These are compromised and must be rotated:

1. Generate new values:
   - `SECRET_KEY`: `openssl rand -hex 32`
   - `SERVER_PRIVATE_KEY`: `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`
   - WireGuard: new server keypair (`wg genkey | tee priv | wg pubkey`)
2. Put them in an UN-committed `.env` (this bundle ships `.gitignore` + `template.env`).
3. Invalidate old tokens: rotating `SECRET_KEY` voids all JWTs; rotating
   `SERVER_PRIVATE_KEY` voids all API keys (and the new revocation list adds
   per-key control going forward).
4. Purge the secret from git history (`git filter-repo` / BFG), not just HEAD.

This bundle does **not** include the leaked `.env` or `dev.db`.
