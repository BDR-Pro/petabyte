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
and starts two systemd services behind nginx on port 80.

## What runs
| Service | Role |
|---|---|
| `lumaris-api` | gunicorn + uvicorn workers (`WEB_CONCURRENCY`), bound to 127.0.0.1:8000 |
| `lumaris-reaper` | standalone heartbeat reaper (so it runs once, not per worker) |
| `nginx` | reverse proxy :80 -> :8000 |
| `postgresql` | database |

> The in-process reaper is disabled via `REAPER_DISABLED=true`; the dedicated
> `lumaris-reaper` service owns reaping. Don't enable both.

## Verify
```bash
systemctl status lumaris-api lumaris-reaper
curl -s http://localhost/healthz     # {"status":"ok"}
curl -s http://localhost/readyz      # {"status":"ready"}  (DB reachable)
journalctl -u lumaris-api -f         # live logs
```

## HTTPS
```bash
# point an A record (e.g. yourdomain.com) at the droplet, then:
sed -i 's/server_name _;/server_name yourdomain.com;/' /etc/nginx/sites-available/lumaris
systemctl reload nginx
certbot --nginx -d yourdomain.com
```

## Updating after a code change
```bash
scp -r lumaris_bundle root@DROPLET_IP:/root/lumaris
ssh root@DROPLET_IP 'cd /root/lumaris && bash deploy/deploy.sh && systemctl restart lumaris-api lumaris-reaper'
```
Re-running `deploy.sh` is safe: it preserves existing secrets and the DB.

## Schema migrations (Postgres)
First deploy creates tables via `init_db()`. For later schema changes use Alembic:
```bash
cd /opt/lumaris
sudo -u lumaris .venv/bin/alembic revision --autogenerate -m "change"
sudo -u lumaris .venv/bin/alembic upgrade head
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
