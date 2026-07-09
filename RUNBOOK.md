# Petabyte — Runbook

Three step-by-step flows, verified against the API end to end:
1. Deploy the server on a DigitalOcean VM
2. Onboard a seller (list a GPU)
3. Buy a service (rent a GPU + run a job)

Replace `api.yourdomain.com` with your domain and `DROPLET_IP` with your droplet's IP.

---

## 1 — Deploy the server on a DigitalOcean droplet

1. **Create the droplet.** Ubuntu 24.04, 2 GB RAM min. Note `DROPLET_IP`.
2. **Create a database.** A DigitalOcean Managed PostgreSQL is recommended; copy its
   connection string. (SQLite works for a quick test but not for production.)
3. **Copy the API up** from your machine:
   ```bash
   scp -r lumaris_api root@DROPLET_IP:/root/lumaris
   ```
4. **Run the installer** on the droplet:
   ```bash
   ssh root@DROPLET_IP
   cd /root/lumaris && bash deploy/deploy.sh
   ```
   This installs Python/nginx/certbot/postgres, creates the `lumaris` service user,
   generates secrets into `/etc/lumaris/lumaris.env` (chmod 600), creates the DB
   tables, and starts two systemd services: `lumaris-api` (gunicorn behind nginx) and
   `lumaris-reaper` (refund-on-reap watchdog).
5. **Edit `/etc/lumaris/lumaris.env`** for production, then
   `systemctl restart lumaris-api lumaris-reaper`. Set at minimum:
   - `DATABASE_URL=postgresql+psycopg2://…` (your managed Postgres)
   - `SECRET_KEY=$(openssl rand -hex 32)`
   - `SERVER_PRIVATE_KEY=$(python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")`
   - `ADMIN_USERS=you@domain.com` (unlocks `/admin`)
   - `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` (Google Cloud → OAuth Web client; redirect
     `https://api.yourdomain.com/auth/google/callback`)
   - keep `PAYMENTS_MODE=sandbox` until you wire live payments
6. **Migrate (Postgres):**
   ```bash
   sudo -u lumaris /opt/lumaris/.venv/bin/alembic upgrade head
   ```
7. **HTTPS.** Point an `A` record `api.yourdomain.com → DROPLET_IP`, set `server_name`
   in `/etc/nginx/sites-available/lumaris`, then:
   ```bash
   systemctl reload nginx && certbot --nginx -d api.yourdomain.com
   ```
8. **Verify:**
   ```bash
   curl https://api.yourdomain.com/healthz     # {"status":"ok"}
   journalctl -u lumaris-api -f
   ```
   Open `https://api.yourdomain.com/` for the site, `/admin` for the console.
9. **Auto-deploy after this (optional):** see `lumaris_api/deploy/AUTO_DEPLOY.md` — push
   to `main` and GitHub Actions runs `deploy/update.sh` for you (no SSH).

---

## 2 — Onboard a seller (list a GPU)

Run on the **GPU machine** (needs Docker + NVIDIA drivers), not the API droplet.

### The easy path — one command
```bash
PETABYTE_API_URL=https://api.yourdomain.com \
PETABYTE_USER=sofia PETABYTE_PASS=secret \
PRICE_PER_HOUR=2.5 \
bash <(curl -fsSL https://api.yourdomain.com/install.sh)
```
The installer creates the account if needed, installs Docker + the NVIDIA toolkit,
detects the GPU, and **automatically does everything below** (register the spec,
attest it, mint a key, start heartbeating). Then:
```bash
systemctl status petabyte-agent
journalctl -u petabyte-agent -f
```
The GPU appears in `/marketplace` within a minute. Auto-update is enabled by default
(6-hourly `petabyte-agent-update.timer`).

**Windows sellers:** either `irm https://api.yourdomain.com/install.ps1 | iex` (WSL2
service) or the double-click desktop app (`desktop-app/` → `PetabyteAgent.exe`), where
you paste your API key + Spec ID in the dashboard. Both need Docker for paid jobs.

### What the installer does under the hood (the manual equivalent)
1. `POST /register_user {username, password}` — create the account.
2. `POST /login` → JWT (or Google sign-in on `/app`).
3. `POST /change_role {role:"seller"}` — switch from buyer to seller.
4. `POST /register_specs {cpu,ram,gpu_model,duration,price_per_hour,provider,units}`
   → returns `spec_id`.
5. **Attest** (Ed25519): sign the spec proof with the node's key and
   `POST /prove {spec_id, attestation, signature, pubkey}`.
6. `POST /create_api_key` → the node's `X-API-KEY`.
7. `POST /heartbeat {spec_id}` (with `X-API-KEY`) every ~15s → keeps the node **online**
   and bookable. Stop heartbeating and the reaper marks it offline.

---

## 3 — Buy a service (rent a GPU + run a job)

### Via the dashboard (what a buyer actually does)
1. Open `https://api.yourdomain.com/app`, sign in (Google or username/password).
2. **Add funds** — in sandbox this mints test credit; live goes through your payment
   provider.
3. **Browse** `/marketplace`, pick a GPU (model, `$/hr`, savings vs cloud, trust badges).
4. **Book it** — funds are held in **escrow**; then submit your notebook/template/render
   job and watch logs live. Results download when it finishes; escrow releases to the
   seller minus the take-rate (auto-refunded if the node dies mid-job).

### Via the API (the exact verified calls)
```bash
# 1. account + token
curl -sX POST https://api.yourdomain.com/register_user -H 'Content-Type: application/json' \
  -d '{"username":"dan","password":"secret12"}'
TOKEN=$(curl -sX POST https://api.yourdomain.com/login \
  -d 'username=dan&password=secret12' | jq -r .access_token)
AUTH="Authorization: Bearer $TOKEN"

# 2. add funds (sandbox) — check the wallet
curl -sX POST https://api.yourdomain.com/deposit -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"amount":50}'                                   # -> {"balance":50.0}

# 3. browse supply, note a spec_id
curl -s https://api.yourdomain.com/marketplace/specs   # -> {"count":N,"specs":[{"gpu_model":"H100",...}]}

# 4. book it -> escrows the cost, returns booking_id
curl -sX POST https://api.yourdomain.com/request_vm -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"spec_id":1,"hours":2}'                         # -> {"booking_id":1,"booking_status":"escrowed"}

# 5. run a job against that booking
curl -sX POST https://api.yourdomain.com/create_task -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"booking_id":1,"task_type":"notebook","code":"print(6*7)"}'   # -> {"task_id":1}

# 6. monitor + settle
curl -s https://api.yourdomain.com/tasks/1 -H "$AUTH"   # status, logs, result
curl -s https://api.yourdomain.com/wallet   -H "$AUTH"  # balance after escrow/settlement
```

Alternatively, let the router place the job for you:
`POST /solve {"workload":"inference","gpu_class":"H100","min_vram":40,"region":"me-central"}`.

**Order matters:** `request_vm` (get `booking_id` + escrow) **then** `create_task`
against it — not the other way round.
