# Deploying Lumaris on a DigitalOcean droplet

Target: fresh **Ubuntu 24.04** droplet (1 vCPU / 1–2 GB is enough to start).

## One command
```bash
# from your machine: copy the bundle up
scp -r lumaris_bundle root@DROPLET_IP:/root/lumaris

# on the droplet
ssh root@DROPLET_IP
cd /root/lumaris
bash deploy/deploy.sh
```
That installs Python, Postgres, nginx; creates the `lumaris` service user and DB;
generates secrets into `/etc/lumaris/lumaris.env` (chmod 600); creates tables;
starts three systemd units behind nginx; and issues a TLS cert automatically when
the domain's DNS already points at the box (see HTTPS below).

## What runs
| Unit | Role |
|---|---|
| `lumaris-api` | gunicorn + uvicorn workers (`WEB_CONCURRENCY`), bound to 127.0.0.1:8000 |
| `lumaris-reaper` | standalone heartbeat reaper (so it runs once, not per worker) |
| `lumaris-payout.timer` | fires `tools/payout_worker.py` every 5 min to drain queued seller withdrawals (safe/`PAYOUT_STUB=true` by default) |
| `nginx` | reverse proxy → :8000 (HTTPS once certbot runs) |
| `postgresql` | database |

> The in-process reaper is disabled via `REAPER_DISABLED=true`; the dedicated
> `lumaris-reaper` service owns reaping. Don't enable both. The payout timer is
> installed and enabled on every deploy — without it, queued withdrawals never send.

## Verify
```bash
systemctl status lumaris-api lumaris-reaper
curl -s http://localhost/healthz     # {"status":"ok"}
curl -s http://localhost/readyz      # {"status":"ready"}  (DB reachable)
journalctl -u lumaris-api -f         # live logs
```

## HTTPS (automatic)
TLS is issued at deploy time. Set the domain, point its A record at the box, and
re-run `deploy.sh`:
```bash
export DEPLOY_DOMAIN=yourdomain.com          # or set BASE_DOMAIN in lumaris.env
export CERTBOT_EMAIL=you@yourdomain.com       # optional expiry-notice account
bash deploy/deploy.sh
```
Once the domain resolves to this host, `deploy.sh` runs
`certbot --nginx -d <domain> --redirect` and arms `certbot.timer` for renewal. If
DNS wasn't ready, it stays on HTTP and prints the one-liner to run later:
```bash
sudo certbot --nginx -d yourdomain.com --redirect -m you@yourdomain.com
```

## Updating after a code change
```bash
scp -r lumaris_bundle root@DROPLET_IP:/root/lumaris
ssh root@DROPLET_IP 'cd /root/lumaris && bash deploy/update.sh'
```
`update.sh` rsyncs the app, syncs the systemd units (api, reaper, payout timer),
and runs `alembic upgrade head` automatically when revisions are present.
Re-running `deploy.sh` is also safe: it preserves existing secrets and the DB.

## Schema migrations (Postgres)
The schema applies automatically: first deploy creates tables via `init_db()`, and
`update.sh` runs `alembic upgrade head` on redeploys. There is a squashed baseline
(`alembic/versions/0001_baseline_schema.py`) proven up/down on Postgres in CI. Adopt
Alembic on a bootstrap-built DB with a one-time stamp — do **not** autogenerate on a
server (author migrations in a dev checkout; see `docs/MIGRATIONS.md`):
```bash
cd /opt/lumaris
sudo -u lumaris .venv/bin/alembic stamp head
```

## WireGuard (when you wire up real VPN)
- The server's **private** key was saved to `/etc/lumaris/wg_server_private.key`.
  Move it to your VPN host's `wg0` config; it must NOT live in the API env.
- Set `WG_APPLY=true` and `WG_INTERFACE` only on a host where the API process
  can manage the interface (or via a privileged helper). Keep `false` otherwise.

## Tuning
Edit `/etc/lumaris/lumaris.env` then `systemctl restart lumaris-api`:
- `WEB_CONCURRENCY` — gunicorn workers (rule of thumb: 2×vCPU + 1)
- `HEARTBEAT_TIMEOUT_S` / `REAPER_INTERVAL_S` — liveness sensitivity
- `PLATFORM_TAKE_RATE` — marketplace fee

## Going live: payments, CORS, reference price

Edit `/etc/lumaris/lumaris.env` then `systemctl restart lumaris-api`:

- **`PAYMENTS_MODE=live`** — disables `/deposit` (returns 403). Balances are then
  credited ONLY via the signed webhook `POST /webhooks/payment`. Keep `sandbox`
  for demos where `/deposit` mints test credits.
- **`PAYMENT_WEBHOOK_SECRET`** — HMAC secret the webhook verifies (X-Signature =
  HMAC-SHA256 of the raw body). For Stripe, set this to the endpoint secret and
  swap the verify call for `stripe.Webhook.construct_event`. The webhook is
  idempotent on `event_id` (no double-credit on retries).
- **`ALLOWED_ORIGINS`** — comma-separated origins for a separate frontend/CLI.
  The dashboard at `/` is same-origin and needs nothing here.
- **`AWS_REFERENCE_PRICE`** — $/hr shown in the dashboard's savings column.

Webhook payload (generic): `{"event_id","type","data":{"username","amount"}}`
with header `X-Signature: <hmac-sha256 hex of raw body>`.
