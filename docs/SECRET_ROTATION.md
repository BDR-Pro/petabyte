# Secret rotation runbook

Rotate these whenever a secret may have been exposed (committed to git, pasted in a
ticket, shared in plaintext, or present in a leaked bundle). This runbook was first
written to remediate a historical incident where a real `.env` had been committed;
keep it as the standing procedure.

## What to rotate and how

| Secret | Regenerate | Effect of rotating |
|---|---|---|
| `SECRET_KEY` (JWT signing) | `openssl rand -hex 32` | Invalidates **all** JWTs — everyone is logged out. |
| `SERVER_PRIVATE_KEY` (API-key Fernet) | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` | Invalidates **all** node API keys — agents must re-enrol. |
| WireGuard server key | `wg genkey \| tee priv \| wg pubkey` | New server keypair; peers must update the endpoint pubkey. |
| `PAYMENT_WEBHOOK_SECRET`, `STRIPE_*`, `MAILGUN_API_KEY`, `GATEWAY_TOKEN`, … | rotate in the provider console | Voids the old credential at the source. |

## Procedure

1. Generate new values (above).
2. Put them in an **un-committed** `.env` — the repo ships `.gitignore` + `lumaris_api/template.env`; secrets never belong in git.
3. Deploy so the new values take effect. Rotating `SECRET_KEY` voids all JWTs; rotating
   `SERVER_PRIVATE_KEY` voids all API keys (per-key revocation exists for finer control).
4. If a secret was ever committed, **purge it from git history** (`git filter-repo` / BFG),
   not just `HEAD` — a value in history is still exposed.
5. Confirm the leaked value no longer authenticates anywhere (old JWT/API key rejected).

Never commit `.env` or a real database. This repo does not ship either.
