# Petabyte

A marketplace and routing layer for underutilized GPU/CPU compute. Petabyte
aggregates fragmented supply, verifies and normalizes it, then routes workloads by
price, performance, availability and trust. Buyers get a simpler interface and
lower-cost options; infrastructure owners monetize idle capacity; Petabyte earns a fee
on successfully delivered compute.

We state plainly what is built and what is not. Real payment rails, vendor TEE
attestation, and KYC/AML are on the roadmap, not live; see
[`docs/PRODUCTION_GAPS.md`](docs/PRODUCTION_GAPS.md).

**Trust & security:** what is enforced in code vs. what needs hardware is documented in
[`docs/TRUST_MODEL.md`](docs/TRUST_MODEL.md); live, honest transparency counts and a
verifiable per-job receipt are at [petabyte.market/trust](https://petabyte.market/trust).
To report a vulnerability, see [`SECURITY.md`](SECURITY.md) — we offer coordinated
disclosure with safe harbor.

## Try the demo in one command

```bash
make investor-demo     # validate deps → build schema → seed labelled demo data → health check → serve
make demo-reset        # wipe and start clean
```

No paid credentials, no Docker or GPU required. It prints demo accounts and URLs.
All seeded entities are labelled **"Demo data"** and are separable from real data
everywhere in the product. Walkthrough: [`docs/PRODUCT_DEMO.md`](docs/PRODUCT_DEMO.md).

## What actually works today (verified in code + tests)

- **Marketplace** with per-GPU-class cloud-price comparison, honest trust levels,
  region, reliability and availability — search/filter/sort, professional empty states.
- **Explainable, auditable routing**: the platform selects a node, shows *why*, and
  records the full decision (`/solve`, `/launch`, `RoutingDecision`).
- **Escrowed settlement on a double-entry ledger**: exact decimal money, idempotent
  booking/settlement, money conservation proven under concurrency on PostgreSQL.
- **Verification**: Ed25519 hardware attestation + signed proof-of-work; trust ladder
  `self_reported → agent_verified → benchmark_verified` (the TEE path is a documented
  stub, never marketed as vendor attestation).
- **Isolation**: buyer code runs only in Docker on the seller machine, no host fallback.
- **Ops**: admin console with append-only audit log + kill switch; a metrics dashboard
  from real queries with demo/real separation and a ledger-integrity signal.

## Monorepo layout

| Path | What it is |
|---|---|
| `lumaris_api/` | FastAPI control plane + web app (marketplace, routing, ledger, admin, metrics, demo) |
| `lumaris_agent/` | Seller node agent (CLI) — registers, attests, heartbeats, runs jobs in Docker |
| `desktop-app/` | Windows-packaged agent (drifted fork — see PRODUCTION_GAPS) |
| `lumaris_gateway/` | Stable-address connection gateway (standalone; not yet wired into deploy) |
| `.github/workflows/` | CI: tests (SQLite + Postgres), demo, clean-DB migration, lint, security scans |
| `docs/` | Technical due-diligence package (below) |

Package names retain the original `lumaris_*` prefix; the product is Petabyte. A rename
is tracked as low-priority hygiene in the roadmap.

## Technical due-diligence package

| Document | Purpose |
|---|---|
| [`docs/INVESTOR_TECHNICAL_BRIEF.md`](docs/INVESTOR_TECHNICAL_BRIEF.md) | The system in one read for a technical adviser |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Components, money model, trust ladder, isolation |
| [`docs/DATA_FLOW.md`](docs/DATA_FLOW.md) | End-to-end flow with endpoints and ledger legs |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Adversaries, mitigations, unresolved items |
| [`docs/METRIC_DEFINITIONS.md`](docs/METRIC_DEFINITIONS.md) | Every metric, defined |
| [`docs/PRODUCT_DEMO.md`](docs/PRODUCT_DEMO.md) | The five-minute demo script |
| [`docs/PRODUCTION_GAPS.md`](docs/PRODUCTION_GAPS.md) | Honest what's-not-ready, by milestone |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Sequenced plan and where a moat can form |
| [`docs/FUNDING_READINESS_AUDIT.md`](docs/FUNDING_READINESS_AUDIT.md) | Full audit findings + status |
| `RUNBOOK.md` | Deploy, onboard a seller, buy compute |

## Run the tests

```bash
cd lumaris_api && python smoke_test.py         # fast SQLite signal
bash run_tests.sh --postgres                    # both engines (what CI runs)
python demo_test.py                             # demo seeding / honesty / reset
```

Assertion counts are emitted by the runners; CI (`.github/workflows/tests.yml`) runs
the full suite on SQLite and PostgreSQL plus demo, clean-DB migration, lint,
dependency-vulnerability and secret scanning.

Built in Riyadh. petabyte.market
