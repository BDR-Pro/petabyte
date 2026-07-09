# Lumaris API

Decentralized GPU/VM compute marketplace. FastAPI backend with JWT auth,
encrypted API keys, hardware attestation, capacity-safe booking, node
heartbeats, and WireGuard config issuance.

## Layout
```
main.py            FastAPI app: auth, specs, attestation, booking, heartbeat, keys, health
db.py              SQLAlchemy models + data access (capacity, idempotency, reaper, WG peers)
auth.py            JWT create/verify (UTC-aware)
utils.py           WireGuard keygen, encrypted API keys, Ed25519 attestation verify
smoke_test.py      End-to-end test (20 assertions incl. concurrency/oversell)
quickstart.sh      One-shot local setup: venv + deps + .env with generated secrets
tools/attest.py    Sign a hardware attestation body for POST /prove
tools/agent.py     Seller node heartbeat agent (keeps a spec online)
template.env       Env var reference (no secrets)
requirements.txt   pip dependencies
alembic/           DB migrations
```

## Quick start (SQLite dev)
```bash
bash quickstart.sh
source .venv/bin/activate
python smoke_test.py          # expect: ALL CHECKS PASSED
uvicorn main:app --reload     # http://localhost:8000/docs
```

## Endpoints
| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | /register_user | – | Create user (defaults to buyer) |
| POST | /login | – | Get JWT |
| POST | /change_role | JWT | Opt into buyer/seller |
| POST | /register_specs | JWT (seller) | List hardware + price + units |
| POST | /prove | JWT (seller) | Verify Ed25519 hardware attestation |
| POST | /heartbeat | API key | Keep a spec online (run via tools/agent.py) |
| POST | /request_vm | JWT (buyer) | Book an attested+online spec (Idempotency-Key supported) |
| GET  | /vpn_config/{booking_id} | JWT (buyer) | WireGuard client config |
| POST | /create_api_key | JWT | Issue encrypted API key (has jti) |
| GET  | /verify_api_key | API key | Validate key (honors revocation) |
| POST | /revoke_api_key | JWT + key | Revoke your key by jti |
| GET  | /healthz, /readyz | – | Liveness / DB readiness |

## Reliability properties
- **No double-sell:** atomic conditional UPDATE on `available_units`.
- **Idempotent bookings:** `Idempotency-Key` header; retries never double-book.
- **Node liveness:** heartbeat + background reaper; offline specs aren't bookable.
- **Race-safe WireGuard IP allocation;** **pool_pre_ping** + statement timeout on Postgres.

## Security notes
- The server's WireGuard PRIVATE key lives only on the VPN host — never in this API or .env.
- Passwords hashed with bcrypt; API keys are Fernet-encrypted with expiry + revocable jti.
- Run Postgres in CI: one prior bug only surfaced off SQLite.

## Production
```bash
# set DATABASE_URL to Postgres in .env, then:
alembic revision --autogenerate -m "schema"
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```
