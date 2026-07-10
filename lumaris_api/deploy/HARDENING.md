# Production hardening — day-one ops

The code/config pieces are wired; these are the toggles + external services to turn on.
Do them in this order.

## 1. Don't lose the database (highest priority)
- **Managed Postgres:** in the DigitalOcean DB panel, backups + point-in-time recovery
  are on by default — confirm they're enabled and note the retention window.
- **If still on the droplet's local Postgres:** you have NO backups. Either migrate to
  managed (set `DATABASE_URL`), or add a nightly `pg_dump` to object storage. Migrating
  is strongly preferred — it also frees RAM on the box.

## 2. Error tracking (Sentry) — already wired
1. Create a project at sentry.io → copy the DSN.
2. Set `SENTRY_DSN=https://…` in `/etc/lumaris/lumaris.env`, restart `lumaris-api`.
   (Empty = off; the SDK only initialises when the DSN is present.)
3. Deploy installs `sentry-sdk` via requirements. You'll now get stack traces for every
   unhandled exception, tagged with the environment (`PAYMENTS_MODE`).

## 3. Uptime alerting (external)
- Sign up at UptimeRobot / Better Stack (free tier is fine).
- Add an HTTP monitor on `https://petabyte.market/healthz`, 1-minute interval,
  alert by email/SMS. **External** is the point — an internal monitor dies with the box.

## 4. Rate limiting — already wired
`deploy/nginx-lumaris.conf` defines two zones and applies them:
- `auth` (5 r/s) on `/login`, `/register_user`, `/create_api_key`, `/deposit`, Google callback.
- `api` (30 r/s) on everything else.
Tune the rates/bursts with real traffic. Limits key on `$binary_remote_addr`; behind a
load balancer, switch to the real client IP via `X-Forwarded-For`.

## 5. Rotate the signing keys (the repo leaked them)
`SECRET_KEY` (JWT) and `SERVER_PRIVATE_KEY` (Fernet) previously sat in the repo. Rotate:
```
openssl rand -hex 32                                   # new SECRET_KEY
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # new SERVER_PRIVATE_KEY
```
Put both in `/etc/lumaris/lumaris.env`, restart. NOTE: rotating `SECRET_KEY` invalidates
all live JWTs (everyone re-signs in) — expected. Rotating `SERVER_PRIVATE_KEY` re-keys
API-key encryption; re-issue node keys after.

## 6. Basics to confirm
- Firewall (`ufw`): only 22, 80, 443 open. deploy.sh sets this — verify with `ufw status`.
- HTTPS: `certbot --nginx -d petabyte.market` (renews automatically).
- `PAYMENTS_MODE=live` only once Stripe + webhook are real; keep sandbox until then.
