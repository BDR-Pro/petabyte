# Petabyte

The routing layer for GPU compute, priced like an energy market. A decentralized
exchange that aggregates underutilized GPU capacity and routes it to buyers below
hyperscaler prices — with confidential computing, escrow-protected settlement, and
automated payout rails.

## Monorepo layout

| Path             | What it is                                                        |
|------------------|-------------------------------------------------------------------|
| `lumaris_api/`   | FastAPI server + web app (marketplace, admin, keys, investor site) |
| `lumaris_agent/` | Seller node agent (CLI) — registers, attests, runs jobs           |
| `desktop-app/`   | Native desktop agent packaged as a Windows `.exe`                 |
| `.github/`       | CI: deploy the server, build + release the desktop agent          |
| `RUNBOOK.md`     | Step-by-step: deploy, onboard a seller, buy a service             |
| `docs/`          | Design notes, security assessment, deploy/frontend references     |

## Quick start

- **Deploy the server:** `RUNBOOK.md` §1, then `lumaris_api/deploy/AUTO_DEPLOY.md`
  for push-to-deploy.
- **Become a seller:** `RUNBOOK.md` §2 — one-liner installer or the desktop app.
- **Buy compute:** `RUNBOOK.md` §3.
- **Run tests:** `cd lumaris_api && python smoke_test.py` (208 assertions).

## Automation

- **Server:** push to `main` → GitHub Actions deploys to the droplet.
- **Seller agent:** self-updates every 6h via `petabyte-agent-update.timer`.
- **Desktop app:** tag `vX.Y.Z` → CI builds the `.exe` and publishes a release the
  running app auto-updates from.

Built in Riyadh. petabyte.market
