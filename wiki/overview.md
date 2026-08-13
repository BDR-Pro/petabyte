# Overview & architecture

Petabyte connects **buyers** (need GPUs) with **sellers** (have idle GPUs), and makes the exchange
safe with escrow, verifiable trust, and a clean product surface. This page explains the moving
parts so the rest of the wiki makes sense.

## The pieces

| Component | What it is | Where it lives |
|---|---|---|
| **API** | The FastAPI backend — accounts, wallet, marketplace, bookings, jobs, payouts, models. Serves the website too. | `lumaris_api/` |
| **Console** | The signed-in web app for buyers *and* sellers (run jobs, VMs, clusters, storage, billing, teams, nodes). | `/console` |
| **Public site** | Marketing / legal / trust / status pages, the marketplace, and the model catalog. | `/`, `/marketplace`, `/models`, … |
| **Agent** | The small daemon a **seller** installs on a GPU machine. Proves the GPU, sends heartbeats, runs jobs, and (optionally) earns from spare disk / idle mining. | `lumaris_agent/` |
| **CLI** | `petabyte` — a command line for buyers (rent + run) and everyone (manage models). | `lumaris_api/cli/petabyte.py` |
| **Gateway** | Routes traffic to rented VMs behind a stable address, with failover. | `lumaris_gateway/` |
| **Model hub** | Provider-independent discover / download / manage layer for open AI models. | `lumaris_api/modelhub/` |

## How a job flows (buyer → seller)

```
buyer adds funds ──▶ picks a GPU (or "cheapest match") ──▶ books it
        │                                                     │
        ▼                                                     ▼
  money into ESCROW                                   seller's agent claims the job,
        │                                             runs it in a sandboxed container,
        │                                             signs the result
        ▼                                                     │
  job completes ──▶ escrow RELEASED to seller (− platform fee) ◀┘
  node drops    ──▶ buyer REFUNDED
```

Key ideas:

- **Escrow, hourly.** Funds are reserved before work starts and released as work is delivered. Every
  unused hour is refundable — a dropped node never costs the buyer.
- **Verified supply.** A GPU must **attest** (prove it exists and is what it claims) before it can be
  booked. Trust is earned by real, server-timed benchmarks and completed jobs — not self-report.
- **Sandboxed execution.** Buyer workloads run in locked-down containers on the seller's machine,
  with egress restricted by default, so hosting a stranger's job is safe.

## Two products, one platform

- **Build (compute):** rent GPUs, run notebooks/containers, form multi-GPU clusters, persist data.
  This is the main product for most users.
- **Buy data:** a metered REST API over Petabyte's live marketplace data (price index, supply,
  demand, GPU-authenticity dataset). Separate keys, separate docs. See [API & keys](api.md).

## The runtime environment

Petabyte is a normal FastAPI app plus a SQL database (SQLite for dev, PostgreSQL in production) and,
optionally, object storage (S3-compatible) for backups, persistent volumes, and job I/O. It degrades
gracefully: telemetry, Redis, Sentry, GeoIP and email are all **optional** — absent, the app still
runs; present, features light up. Everything is configured with environment variables documented in
[`self-hosting`](self-hosting.md) and `lumaris_api/template.env`.

## Where to go next

- New here? → [Getting started](getting-started.md)
- Renting compute → [For buyers](buyers.md)
- Earning → [For sellers](sellers.md)
- Deeper technical docs live in the repo `docs/` folder (runbooks, trust model, disk rental, etc.).
