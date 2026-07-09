# Petabyte (fixed bundle)

Decentralized GPU/VM compute marketplace. Two components:

- **lumaris_api/** — FastAPI backend (auth, specs, bookings, attestation,
  WireGuard, secure task/job dispatch). Hardened and covered by `smoke_test.py`.
- **lumaris_agent/** — seller node agent (heartbeat, job execution in a Docker
  sandbox, optional QEMU/Firecracker microVMs).

Start here:
1. **SECURITY.md** — rotate the leaked secrets first.
2. **FIXES.md** — everything that was changed and why.
3. API: `cd lumaris_api && bash quickstart.sh && python smoke_test.py` then
   `uvicorn main:app --reload`. Deploy guide in `lumaris_api/deploy/DEPLOY.md`.
4. Agent: `cd lumaris_agent && cp .env.example .env` (fill in API URL/key/spec),
   `pip install -r requirements.txt`, `python main.py`.
