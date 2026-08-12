# populate-data.md — fill the DB with demo data for UI/UX testing

`scripts/populate_demo_data.py` fills a database with **realistic, clearly-labelled** demo data so
you can click through every screen with content instead of empty tables. It's a **superset of the
investor demo** (`lumaris_api/demo.py`): it runs that tested base seed and then enriches it so the
newer screens have data too.

## Quick start

```bash
# wipe + seed + enrich the default SQLite file (./demo.db), print the accounts
make populate-demo
#   or:  python scripts/populate_demo_data.py

# then serve THAT database and open the UI. A served API must pick a payment gateway
# explicitly, so pass STRIPE_GATEWAY (fake = offline, no money) for a local click-through:
cd lumaris_api && DATABASE_URL=sqlite:///../demo.db STRIPE_GATEWAY=fake PETABYTE_OFFLINE_TEST=1 \
  uvicorn main:app --reload
# -> http://127.0.0.1:8000/marketplace  ·  /app  ·  /metrics  ·  /docs
```

Pick a specific file, or add to an existing DB without wiping:

```bash
make populate-demo DB=sqlite:///./ui.db          # seed a named file
make populate-demo ARGS=--keep                    # enrich WITHOUT wiping (append)
DATABASE_URL=sqlite:///./ui.db python scripts/populate_demo_data.py
```

> Log in with any seeded account. **Password (all accounts): `demo-Petabyte-2026!`**
> Sellers: `demo_aurora_labs`, `demo_vega_compute`, `demo_nimbus_rigs`, … · Buyers:
> `demo_northwind_ai`, `demo_delta_research`, `demo_quant_forge`. The script prints the full list.

## What gets seeded

| Data | Screens it lights up |
|---|---|
| Sellers with **verified GPUs** (H100/A100/4090…), benchmarks, regions | `/marketplace`, node/trust pages |
| Buyers with **funded wallets** | `/app`, checkout |
| **Bookings + jobs** (completed / running / failed) with explainable routing + settlement + earnings | `/app`, `/metrics`, seller earnings |
| **Idle mining** config + estimate on some nodes | idle earnings UI |
| **Rentable VMs** — one running, one "migrated" (stable address kept) | `/app` VM UI, the dynamic-DNS story |
| **Spare-disk rental** on some nodes (Storj/BTFS/Sia, GB caps, usage) — *auto-skipped on builds without the disk columns* | seller disk UI, `GET /disk/providers` |
| A **distributed cluster** (ranks + rendezvous) — *auto-skipped on builds without the cluster feature* | `/cluster`, `/jobs/manifest/{id}` |

The script is **schema/feature-aware**: each enrichment runs only when this build actually has
its columns/functions, and the summary prints `skipped — … not in this build` otherwise — so a
count never implies a write that didn't land. On this branch, idle-mining and VM enrichments
apply; spare-disk and distributed-cluster are skipped.

## Honesty (same rules as the investor demo, enforced by `demo_test.py`)

- Every base entity is stamped **`is_demo=True`** and reported **separately** from real data —
  `/metrics` excludes it and the UI badges it **"Demo data"**. Nothing here inflates real
  GMV/revenue.
- The enrichments set only **display/status** fields (disk/idle config, cluster addresses, VM
  routes). They post **no ledger settlement**, so **no fabricated earnings** enter the books —
  "credited to date" for disk/idle stays honestly **$0** until a real `disk_reconcile` /
  `idle_reconcile` runs.
- No buyer code is executed: completed demo jobs carry a clearly-labelled **SIMULATED** result
  string (real execution needs the real agent + Docker).

## Reset / re-run

- Default (no `--keep`) **wipes and recreates** the schema, then seeds — repeatable and
  deterministic. It **refuses to run against `ENVIRONMENT=production`**.
- `--keep` seeds on top of an existing DB (handy while iterating on the server).
- To clear a SQLite demo DB entirely, just delete the file (e.g. `rm demo.db`).

## Related

- `make investor-demo` — the base demo + serves it (five-minute walkthrough).
- `make demo-seed` / `lumaris_api/demo.py` — the tested base seed this script builds on.
- The disk-rental and distributed-cluster enrichments target features that ship on the
  full-platform branches; where those features aren't present, this script skips them
  cleanly (see the schema/feature-aware note above).
