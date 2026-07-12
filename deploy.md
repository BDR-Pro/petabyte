# deploy.md — things only you can do

Everything in this file needs your hands: your DNS, your droplet, your accounts.
Code-side work is done and green (288 smoke + 11 adversarial assertions).

Ordered by value. **Do 1 and 2 this week.**

---

## 1. Kill the duplicate sites (highest value on the whole list)

Right now someone can type `www.petabyte.market` or `space.petabyte.market` and land on
an **older Petabyte with a different design and a broken login (502)**. That reads as a
dead company. No amount of typography beats fixing this.

Full config: **`deploy/canonical-domain.md`**. Short version:

```bash
# DNS: A @ -> droplet IP; CNAME www -> petabyte.market; CNAME space -> petabyte.market
sudo certbot --nginx -d petabyte.market -d www.petabyte.market -d space.petabyte.market
# nginx: 301 www + space -> https://petabyte.market$request_uri   (see canonical-domain.md)
sudo nginx -t && sudo systemctl reload nginx
```

Verify:
```bash
curl -sI https://www.petabyte.market/login | head -1    # expect 301
curl -sI https://petabyte.market/login     | head -1    # expect 200, NOT 502
```

Then **stop the old service** on whatever box served the old site. A redirect in front of
a live old app is one nginx typo away from resurfacing.

---

## 2. Deploy this build

```bash
ssh root@<droplet>
cd /root/petabyte && git pull        # or upload the zip
sudo PETABYTE_SRC=/root/petabyte /opt/lumaris/deploy/update.sh
```

**The database migrates itself** — `init_db()` adds the new columns, indexes, and
backfills opaque public ids for existing listings. Idempotent; safe to run twice.

New env var worth setting:
```
S3_SSE=AES256          # AES256 works on AWS S3 AND DigitalOcean Spaces ("aws:kms" is AWS-only)
```

Verify after deploy:
```bash
curl -s  https://petabyte.market/health/live            # {"status":"alive"}
curl -s  https://petabyte.market/health/ready           # {"status":"ready","database":"ok"}
curl -sI https://petabyte.market/ | grep -i content-security-policy   # CSP present
curl -s  https://petabyte.market/api/v1/marketplace/nodes | head -c 120
open     https://petabyte.market/docs                   # Scalar API portal
```

The deploy script now ends with a **DEBUG env report** classifying every setting as
`[LIVE] / [STUB] / [SET] / [DEFAULT] / [MISSING]`. Read it. It tells you exactly what this
deployment will really do.

---

## 3. Run the suite against Postgres (now automated)

This used to be a manual step because CI only ran SQLite. It no longer is —
`.github/workflows/tests.yml` runs everything against Postgres 16 on every push, and
`lumaris_api/run_tests.sh --postgres` does it locally.

Still worth doing **once against YOUR managed Postgres** before real funds, because your
database has different settings (pooling, timeouts, isolation) than a stock container:

```bash
ssh root@<droplet>
cd /root/petabyte/lumaris_api
DATABASE_URL="<your managed-postgres URL>" python adversarial_test.py   # expect 14 passed
DATABASE_URL="<your managed-postgres URL>" python postgres_test.py      # expect 12 passed
```

`postgres_test.py` is the one that matters: it proves money is exact **in the database**,
that exactly one worker wins the maintenance lock, and that 50 parallel debits on one
wallet resolve correctly. If anything fails, do **not** flip payments live.

---

## 3b. Run maintenance as ONE process (not one per API worker)

Gunicorn runs several workers. The reaper used to live inside the app, so **every worker
ran it** — racing to fail over the same node and settle the same booking every 20s. Fixed
in code (advisory lock), but do the deployment side too:

```bash
# 1. API workers must NOT run maintenance:
echo 'REAPER_DISABLED=true'   >> /etc/lumaris/lumaris.env
# 2. and tell the app who your reverse proxy is, so X-Forwarded-For can be trusted:
echo 'TRUSTED_PROXIES=127.0.0.1,::1' >> /etc/lumaris/lumaris.env

sudo cp deploy/lumaris-reaper.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lumaris-reaper
systemctl status lumaris-reaper
```

**Add an alert.** A dead reaper is a silent money bug — VMs never expire, dead nodes stay
listed, bookings never settle, and the API keeps reporting healthy the whole time:

```bash
curl -s https://petabyte.market/health/ready | jq .maintenance
# alert if .stale == true, or .failures keeps climbing
```

---

## 4. Before taking real money

- [ ] `PAYMENTS_MODE=live` + real Stripe keys (today: sandbox mints test credit)
- [ ] `PAYOUT_STUB=false` + real payout provider + **real KYC/AML** (today: simulated)
- [ ] **Rotate `SECRET_KEY` and the Fernet key** — the old ones were exposed in chat
- [ ] `GOOGLE_OAUTH_STUB` must be **unset** in prod (if `true`, it's an open demo login)
- [ ] Set `SENTRY_DSN`, add UptimeRobot on `/health/ready`
- [ ] `ALLOWED_ORIGINS=https://petabyte.market` (CORS is allow-list only — keep it tight)
- [ ] `TRUSTED_PROXIES=<nginx address>` — without it, `X-Forwarded-For` is ignored (safe
      default); with a wrong value, clients could spoof their IP and country
- [ ] Set `ENVIRONMENT=production`. **The app will now refuse to boot** if any stub is
      still on (`GOOGLE_OAUTH_STUB`, `PAYOUT_STUB`, `S3_STUB`, sandbox payments, a default
      `SECRET_KEY`). That refusal is the feature — do not work around it.
- [ ] Re-mint any API keys issued before scopes existed. Scopeless keys are now **denied**
      (they used to mean *full access*). `LEGACY_KEYS_FULL_ACCESS=true` exists only as a
      temporary migration escape hatch — do not leave it on.

`grep -rn 'TODO(stub)' lumaris_api/` gives the full inventory of what's still simulated.

---

## 5. The big one: prove the tunnel on real machines

**This is the only thing standing between "impressive architecture" and "a product".**
Nobody has yet SSH'd into a real container on a real seller's box.

Follow **`docs/vm-runbook.md`**. You need two cheap cloud VMs + your laptop:

- **Phase A** — prove NAT traversal: `frps` on a public gateway, `frpc` on a node with
  *no inbound ports open*, then from your laptop: `ssh -p <port> root@gateway` lands you
  inside the container. If this works, the core product works.
- **Phase B** — the stable address: add `sshpiper`, then
  `ssh vm-<handle>@petabyte.market` routes by username to the current node.
- **Failover test** — kill node A, confirm the *same handle* lands you on node B.

Budget half a day. Everything else on this list is subordinate to it.

---

## 6. Windows agent dry run

The PowerShell scripts (`install.ps1`, `manage.ps1`) are logically complete but have
**never run on a real Windows box** — I can't execute PowerShell here.

On a spare Windows machine:
```powershell
# install, then:
$env:PETABYTE_ACTION="status";    irm https://petabyte.market/manage.ps1 | iex
$env:PETABYTE_ACTION="pause";     irm https://petabyte.market/manage.ps1 | iex
$env:PETABYTE_ACTION="uninstall"; irm https://petabyte.market/manage.ps1 | iex
```
Confirm the uninstall path especially: it should remove the distro **only if we created
it**, and disable WSL **only if WSL wasn't already on the machine**.

---

## 7. Deferred deliberately (my recommendation)

- **Next.js rewrite** — not yet. Do it after §5 passes and §3/§4 are done. Rewriting the
  presentation layer while the core loop is unproven moves zero product risk.
- **Hardware-backed attestation (SEV-SNP/TDX)** — Phase 2. Today's attestation is
  software-signed, and `/security` says so honestly.
- **gVisor on a real GPU box** — the agent adds `--runtime=runsc` when present; needs
  verifying on real hardware.
