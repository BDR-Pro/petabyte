# Architecture

Petabyte is a marketplace and routing layer for underutilized GPU/CPU compute.
This document maps the system as it is actually implemented in this repository.

## Components

| Component | Path | Role | Runs where |
|---|---|---|---|
| API / control plane + web app | `lumaris_api/` | FastAPI app: accounts, marketplace, routing, booking, jobs, ledger, payouts, admin, and all server-rendered pages | Operator's server (systemd + gunicorn behind nginx) |
| Seller node agent | `lumaris_agent/` | Registers hardware, attests, heartbeats, claims jobs, runs them in Docker, reports signed results | Seller's GPU machine |
| Desktop agent | `desktop-app/` | Windows-packaged variant of the agent (drifted fork — see PRODUCTION_GAPS) | Seller's Windows machine |
| Connection gateway | `lumaris_gateway/` | Holds outbound node control channels and bridges buyer↔node traffic so a rented VM keeps one stable address across failover | Operator's server (not wired into deploy today — see PRODUCTION_GAPS) |
| Maintenance worker | `lumaris_api/tools/reaper.py` | Reaps stale nodes, expires VMs, settles, reprices — one leader via a Postgres advisory lock | Operator's server (systemd) |

Naming: the product is **Petabyte**; the Python packages retain the original
`lumaris_*` names. This is cosmetic and does not affect behavior; a rename is tracked
in ROADMAP as low-priority hygiene.

## Request/data flow (happy path)

```
 Seller machine                     Control plane (lumaris_api)                 Buyer
 ─────────────                      ───────────────────────────                 ─────
 agent register ───────────────────►  SellerSpec (self_reported)
 agent /prove (Ed25519) ────────────►  attested=true  (agent_verified)
 agent /heartbeat (X-API-KEY) ──────►  status=online, region verified via GeoIP
 (optional) signed benchmark ───────►  benchmark_tokens_sec (benchmark_verified)
                                        │
                                        │  marketplace: /marketplace/specs
                                        │◄───────────────────────────────  browse
                                        │  routing: /solve or /launch
                                        │   → gather eligible → score → select
                                        │   → RoutingDecision (audit record)
                                        │◄───────────────────────────────  book
                                        │  escrow: try_reserve_unit + try_debit
                                        │          + book_with_escrow (ledger)
 agent /jobs/next (claim) ◄──────────── Task (pending→running)
 run in Docker sandbox
 agent /jobs/result (signed) ────────►  verify sig → completed
                                        │  release_booking → seller earns,
                                        │  platform fee, ledger postings
                                        │◄───────────────────────────────  result + receipt
```

Every automated placement writes a `RoutingDecision` row (intent, every eligible
candidate with its factor scores, the selection, and a plain-language explanation),
so any booking can answer "why this machine?" later.

## Money model

- All monetary columns are `NUMERIC(20,8)`; all arithmetic is Python `Decimal`.
  Never binary float. Verified exact on Postgres in `postgres_test.py`.
- **Double-entry ledger** (`db.py`: `LedgerTx`/`LedgerEntry`/`post`). The only way
  to write money is `post()`, which refuses unbalanced legs. `users.balance` and
  `users.earnings` are caches; the ledger is the source of truth and can reconstruct
  every balance (`account_balance`, `ledger_is_balanced`).
- **Escrow**: booking debits the buyer into an `escrow:{booking_id}` account; on
  completion, `release_booking` moves it to seller earnings and platform revenue; on
  node death or cancel, `refund_booking` returns it. Both are idempotent (guarded
  conditional updates), verified under concurrency in `adversarial_test.py`.
- Take rate: `PLATFORM_TAKE_RATE` (default 10%), applied out of the rental, not on
  top. Surfaced to sellers before they list.

## Trust / verification ladder

Implemented in `db.py::trust_level_for`, awarded only on evidence held:

| Level | Requirement (what the code checks) | Guarantee | Limit |
|---|---|---|---|
| `self_reported` | Listing created via API | none | nothing proven |
| `agent_verified` | Ed25519-signed hardware report (`/prove`) | a keyholder on the node claims this hardware | not proof of the silicon itself |
| `benchmark_verified` | agent_verified + a signed benchmark result on record | throughput was measured, not declared | benchmark harness quality caveat |

`confidential` is surfaced separately as a **CC pilot** flag; the current TEE verifier
is a structural Ed25519 stub (`utils.py`, `docs/stub.md` #3) and is **never**
presented as vendor hardware attestation (NVIDIA NRAS / AMD SEV-SNP / Intel TDX).

## Execution isolation (seller side)

Buyer workloads run **only** in Docker on the seller machine, never on the host
directly. The notebook path (`lumaris_agent/notebook.py`) uses `--network none`,
`--cap-drop ALL`, `--no-new-privileges`, read-only rootfs, tmpfs, memory/CPU/PID
limits, a wall-clock timeout and output cap, and refuses to run if Docker is absent
(no host fallback). Template/render/transcode paths use a subset of these; hardening
parity and micro-VM isolation are tracked in PRODUCTION_GAPS. Sandbox-escape
resistance requires live testing on a real Docker host (see `docs/RLtest.md`).

## Persistence & schema

SQLAlchemy ORM (30 models in `db.py`). Schema is created by `init_db()` =
`create_all()` + `_ensure_columns()` (idempotent forward-migration of added columns)
+ `_ensure_indexes()`. A CI job proves the schema builds from a completely empty
SQLite **and** Postgres DB. Alembic migrations exist but are stale (see
PRODUCTION_GAPS); a squashed baseline is on the roadmap.

## Deployment

`lumaris_api/deploy/deploy.sh` provisions a single droplet: Python venv, nginx,
systemd units (`lumaris-api` = gunicorn, `lumaris-reaper` = maintenance), Postgres,
secret generation into `/etc/lumaris/lumaris.env` (chmod 600), and S3 bucket
hardening. `ENVIRONMENT=production` arms a boot gate that refuses to start with any
stub still enabled. Deployment gaps (TLS-by-default, deploy test-gate, secret
handling via argv) are documented in PRODUCTION_GAPS.
