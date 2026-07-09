# Deploying Petabyte

End-to-end guide to run Petabyte on a live server, then switch it from
**sandbox** (demo) to **live** (real payments). Two components:

- **lumaris_api** — the marketplace API + buyer dashboard. Runs on a server (a
  DigitalOcean droplet in this guide).
- **lumaris_agent** — the seller node agent. Runs on each GPU machine (NOT on the
  API droplet — it needs Docker/KVM/GPU).

---

## 0. Architecture at a glance

```
            buyers (CLI / dashboard at /)
                        |
                   HTTPS :443
                        |
            ┌───────────▼───────────┐
            │  nginx  →  gunicorn    │   systemd: lumaris-api
            │  (uvicorn workers)     │
            │  + lumaris-reaper      │   systemd: lumaris-reaper (refund-on-reap)
            └───────────┬───────────┘
                        │
                   PostgreSQL
                        ▲
                        │  X-API-KEY (heartbeat, /jobs/next, signed results)
            seller GPU nodes (lumaris_agent + Docker sandbox)
```

---

## 1. Prerequisites

- A fresh **Ubuntu 24.04** droplet (1 vCPU / 2 GB is enough to start).
- A **PostgreSQL** database (DigitalOcean Managed DB, or Postgres on the droplet).
- A domain you can point at the droplet (for HTTPS).
- For sellers: any Ubuntu/Debian box with a GPU + Docker.

---

## 2. Sanity check locally first (optional, 1 min)

```bash
cd lumaris_api
bash quickstart.sh
source .venv/bin/activate
python smoke_test.py            # expect: ALL CHECKS PASSED
uvicorn main:app --reload       # open http://localhost:8000/  (dashboard)
```

---

## 3. Provision the droplet

```bash
# from your machine
scp -r lumaris_api root@DROPLET_IP:/root/lumaris

# on the droplet
ssh root@DROPLET_IP
cd /root/lumaris
bash deploy/deploy.sh
```

`deploy.sh` installs Python + Postgres + nginx + certbot + ufw, creates the
`lumaris` service user and a local DB, generates secrets into
`/etc/lumaris/lumaris.env` (chmod 600), creates the tables, and starts two
systemd services behind nginx on port 80:

| Service          | Role                                            |
|------------------|-------------------------------------------------|
| `lumaris-api`    | gunicorn + uvicorn workers (bound 127.0.0.1:8000) |
| `lumaris-reaper` | marks dead nodes offline + **refunds in-flight bookings** |
| `nginx`          | reverse proxy :80 → :8000                       |

> The reaper runs as its own service; the web app sets `REAPER_DISABLED=true` so
> it doesn't run once per gunicorn worker. Don't enable both.

---

## 4. Configure the environment

Everything is driven by `/etc/lumaris/lumaris.env` (chmod 600). After
`deploy.sh` it has working defaults; edit it for production, then
`systemctl restart lumaris-api lumaris-reaper`.

```ini
# --- Database (REQUIRED: switch off SQLite for production) ---
DATABASE_URL=postgresql+psycopg2://lumaris:PASSWORD@your-db-host:5432/lumaris

# --- Secrets (ROTATE — old committed ones are compromised, see SECURITY.md) ---
SECRET_KEY=<openssl rand -hex 32>
SERVER_PRIVATE_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">

# --- Marketplace / trust ---
PLATFORM_TAKE_RATE=0.10
MIN_REPUTATION=50
HEARTBEAT_TIMEOUT_S=60

# --- Reaper (separate service owns it) ---
REAPER_DISABLED=true
REAPER_INTERVAL_S=20

# --- Web ---
WEB_CONCURRENCY=3
LOG_LEVEL=info

# --- Payments (see section 8 to go live) ---
PAYMENTS_MODE=sandbox            # sandbox = /deposit mints test credits
PAYMENT_WEBHOOK_SECRET=          # required when PAYMENTS_MODE=live

# --- Dashboard ---
AWS_REFERENCE_PRICE=12.29        # $/hr shown in the savings column

# --- CORS (only for a separate frontend/CLI origin; dashboard at / is same-origin) ---
ALLOWED_ORIGINS=                 # e.g. https://app.petabyte.market

# --- WireGuard (keep OFF unless you run a real VPN host; see section 9) ---
WG_PUBLIC_KEY=<server pubkey>
WG_ENDPOINT=<droplet public IP>
WG_APPLY=false
WG_INTERFACE=wg0
```

Generate secrets:
```bash
openssl rand -hex 32                                                   # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # SERVER_PRIVATE_KEY
```

---

## 5. Database + migrations (REQUIRED on Postgres)

The bundled Alembic migrations predate the current schema (bookings, tasks,
ledger, test_workloads, wg_peers, idempotency, processed_webhooks). Regenerate
and apply once, as the `lumaris` user, after setting `DATABASE_URL`:

```bash
cd /opt/lumaris
sudo -u lumaris .venv/bin/alembic revision --autogenerate -m "full schema"
sudo -u lumaris .venv/bin/alembic upgrade head
```

> First boot also calls `init_db()` (create_all) for convenience, but use Alembic
> for anything beyond the first deploy so schema changes are versioned.

---

## 6. HTTPS

```bash
# point an A record (e.g. yourdomain.com) at the droplet, then:
sed -i 's/server_name _;/server_name yourdomain.com;/' /etc/nginx/sites-available/lumaris
systemctl reload nginx
certbot --nginx -d yourdomain.com
```

---

## 7. Verify

```bash
systemctl status lumaris-api lumaris-reaper
curl -s https://yourdomain.com/healthz      # {"status":"ok"}
curl -s https://yourdomain.com/readyz       # {"status":"ready"}  (DB reachable)
# open https://yourdomain.com/  -> the buyer dashboard
journalctl -u lumaris-api -f                     # live logs
```

---

## 8. Switching to LIVE payments

In **sandbox** mode `/deposit` mints test credits (great for demos). In **live**
mode that endpoint is disabled and money only enters via a verified webhook.

### 8a. Env change (no code needed for the generic webhook)

```ini
PAYMENTS_MODE=live
PAYMENT_WEBHOOK_SECRET=<a strong shared secret>
```
`systemctl restart lumaris-api`. Now `POST /deposit` returns 403, and balances
are credited only by `POST /webhooks/payment`, which:
- verifies `X-Signature` = HMAC-SHA256 of the raw body using `PAYMENT_WEBHOOK_SECRET`,
- is idempotent on `event_id` (safe to retry — no double credit),
- expects JSON `{"event_id","type","data":{"username","amount"}}`.

Your payment provider (or a small bridge) calls this on successful payment.

### 8b. Code change to use Stripe specifically (optional)

The generic HMAC works as-is. To use Stripe's native verification instead:

1. `pip install stripe` (add to `requirements.txt`).
2. In `main.py`, replace the signature check inside `payment_webhook`:

```python
# BEFORE (generic HMAC)
sig = request.headers.get("X-Signature", "")
if not verify_webhook_signature(PAYMENT_WEBHOOK_SECRET, raw, sig):
    raise HTTPException(status_code=401, detail="Invalid webhook signature")
try:
    evt = json.loads(raw)
    event_id = evt["event_id"]
    username = evt["data"]["username"]
    amount = float(evt["data"]["amount"])
except (ValueError, KeyError, TypeError):
    raise HTTPException(status_code=400, detail="Malformed event")

# AFTER (Stripe)
import stripe
sig = request.headers.get("Stripe-Signature", "")
try:
    evt = stripe.Webhook.construct_event(raw, sig, PAYMENT_WEBHOOK_SECRET)
except Exception:
    raise HTTPException(status_code=401, detail="Invalid webhook signature")
if evt["type"] != "checkout.session.completed":
    return {"status": "ignored"}
session = evt["data"]["object"]
event_id = evt["id"]
username = session["metadata"]["username"]     # set this when creating the Checkout Session
amount = session["amount_total"] / 100.0       # cents -> dollars
```

Set the buyer's `username` in the Checkout Session `metadata` so the webhook
knows whom to credit. Everything downstream (idempotency, crediting) is unchanged.

---

## 9. A note on the VPN

WireGuard config generation is correct and never leaks the server key, but live
peer application is intentionally **off** (`WG_APPLY=false`). The notebook-job
path (CLI + dashboard) needs no VPN. Turning it on for interactive VM rental
requires a privileged peer-reconciler service, NAT, and opening UDP 51820 — defer
until a customer needs SSH into a live VM.

---

## 10. Onboard a seller GPU node

On each GPU machine (not the API droplet):

```bash
PETABYTE_API_URL=https://yourdomain.com \
PETABYTE_USER=alice PETABYTE_PASS=secret PRICE_PER_HOUR=1.5 \
bash <(curl -fsSL https://YOUR_HOST/install.sh)
```

This installs Docker, detects the GPU, registers + attests the spec, mints an API
key, writes `/etc/petabyte/agent.env`, and starts the `petabyte-agent` service.
Verify with `systemctl status petabyte-agent`. See `lumaris_agent/INSTALL.md`.

---

## 11. Updating / redeploying

```bash
scp -r lumaris_api root@DROPLET_IP:/root/lumaris
ssh root@DROPLET_IP 'cd /root/lumaris && bash deploy/deploy.sh && \
  systemctl restart lumaris-api lumaris-reaper'
```
Re-running `deploy.sh` preserves existing secrets and data. If the schema
changed, run the Alembic migration (section 5) before restarting.

---

## 12. Gotchas (in order of likelihood)

1. **Forgot the Alembic migration** → missing tables on Postgres → 500s. Run section 5.
2. **`ALLOWED_ORIGINS` unset** → a separate frontend/CLI-from-browser hits CORS errors. The dashboard at `/` is fine (same-origin).
3. **Left `PAYMENTS_MODE=sandbox` in production** → anyone mints free credits via `/deposit`. Set `live`.
4. **`WG_APPLY=true` without a real VPN host** → `/vpn_config` 500s. Keep `false`.
5. **Secrets not rotated** → the old committed values are compromised (SECURITY.md).

## 13. Secure backups (object storage)

Backups upload **directly from untrusted seller nodes**, so the security model is:
the API holds the object-storage credentials; nodes never do.

**Env** (`/etc/lumaris/lumaris.env`):
```ini
S3_BUCKET=petabyte-backups
S3_REGION=us-east-1
S3_ENDPOINT=                      # set for Cloudflare R2 / MinIO; empty for AWS
AWS_ACCESS_KEY_ID=__SET_ME__      # the API's creds, NOT the nodes'
AWS_SECRET_ACCESS_KEY=__SET_ME__
BACKUP_RESCHEDULE_GRACE_S=900
```

**How it's secured:**
- **No standing node credentials.** For each backup the agent calls
  `POST /jobs/backup_url`; the API returns a **per-object, 15-min pre-signed PUT URL**.
  A node can write exactly one key and holds nothing reusable.
- **Per-tenant prefix isolation.** Keys are `backups/{buyer_id}/{task_id}/...`, and the
  pre-signed URL is for that single key — one seller can't read or clobber another's.
- **Client-side encryption.** The agent encrypts the tarball with a per-task key
  (issued by the API, sealed at rest) before upload.
- **Integrity on restore.** `POST /jobs/restore_url` returns the signed
  `content_hash`; the agent re-hashes the download and refuses a tampered backup.

**Bucket bootstrap.** `deploy.sh` creates the bucket if missing and hardens it when
`S3_BUCKET` + creds are set: block-all-public-access, versioning (recover malicious
overwrites), default SSE, a TLS-only bucket policy, and a 30-day lifecycle expiry.
Re-run `deploy.sh` after setting the S3 vars, or apply the same `aws s3api` calls
manually. For stronger isolation, give the API an IAM role scoped to
`arn:aws:s3:::$S3_BUCKET/backups/*` only.

**Honest limit:** the per-task key is platform-issued, so Petabyte (and the node
during a job) can read backups. For buyer-confidential data, wrap the data key with
a buyer-held KMS key / enclave key — roadmap, and it binds to the CC attestation.
