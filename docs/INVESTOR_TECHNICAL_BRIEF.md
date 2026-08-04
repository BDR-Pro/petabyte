# Investor Technical Brief

A concise, honest overview for an investor's technical adviser. Every claim here is
backed by code in this repository and by the test suite; limitations are stated plainly
and detailed in [PRODUCTION_GAPS](PRODUCTION_GAPS.md) and [THREAT_MODEL](THREAT_MODEL.md).

## The problem
High-end GPU compute is expensive and supply-constrained at the hyperscalers, while
large amounts of capable hardware sit underutilized across smaller providers,
render farms, and individual owners. There is no efficient, trustworthy way to
aggregate that idle supply and route workloads to it.

## The product
Petabyte aggregates fragmented compute supply, verifies and normalizes it, then routes
workloads by price, performance, availability and trust. Buyers get a simpler
interface and lower-cost options; infrastructure owners monetize idle capacity;
Petabyte earns a fee on successfully delivered compute.

## The current working system (verified in code + tests)
- **Marketplace**: normalized supply with per-class cloud-price comparison, trust
  level, region, reliability, availability; search/filter/sort; professional empty and
  offline states. (`/marketplace`, `main.py`, `pages.py`)
- **Explainable routing**: eligible nodes gathered against hard constraints, scored on
  reputation/price/throughput with deterministic tie-breaks; a plain-language reason is
  shown to the buyer and the full decision (intent + every candidate's factor scores +
  selection) is persisted as an audit record. (`router.py`, `RoutingDecision`)
- **Escrowed settlement on a double-entry ledger**: exact `NUMERIC(20,8)`/`Decimal`
  money; the only way to write money refuses unbalanced legs; balances reconstruct from
  the ledger; booking and settlement are idempotent. Proven under concurrency
  (no oversell, exact money conservation) on PostgreSQL. (`db.py`, `adversarial_test.py`,
  `postgres_test.py`)
- **Verification**: Ed25519 hardware attestation and signed proof-of-work bind results
  to the attested node; an honest trust ladder (self-reported → agent-verified →
  benchmark-verified). The TEE path is a documented stub and is never marketed as
  vendor attestation.
- **Isolation**: buyer code runs only in Docker on the seller machine, no host
  fallback; strongest on the notebook path (`--network none`, cap-drop, read-only,
  limits).
- **Operations**: admin console with append-only audit log, kill switch, payout state
  machine; a live metrics dashboard from real queries with demo/real separation and a
  ledger-integrity signal.
- **Reliability**: heartbeat/reaper, refund-on-death, VM failover to a new node at the
  same stable address (proven in `tunnel_test.py`), retryable failed jobs.
- **Demo**: one command (`make investor-demo`) stands up the whole loop deterministically
  with clearly-labelled data and a reset.

Test evidence: smoke, adversarial (money under races) and gateway suites pass on
SQLite; the same plus 12 Postgres-only invariants (exact NUMERIC, advisory-lock leader
election, real concurrent writers) pass on PostgreSQL 16; frontend contract + JS-parse
audits pass; a 21-check demo honesty suite passes. CI runs all of this plus clean-DB
schema build, lint, dependency-vuln and secret scanning.

## Differentiation — more than a listing site
- The buyer states intent; the platform **selects and justifies** the node, and records
  the decision. That routing/verification/settlement layer is the product, not a
  directory.
- Money is a first-class, auditable, double-entry system — not a spreadsheet of
  transactions.
- Honesty as a feature: trust levels, savings, and "what's not built yet" are stated in
  the product itself, which is exactly what technical diligence rewards.

## Marketplace flywheel
More verified supply → better routing options and lower prices → more buyers → more
completed jobs → more reliability/pricing data → better routing and pricing → more
attractive to buyers and sellers.

## Where a real moat can form
Not any single feature. It accrues in **data and infrastructure that compound with
volume**: normalized supply telemetry, per-node reliability history, the routing
decision corpus (already recorded per placement), transaction infrastructure, and
pricing/routing models trained on that history. The routing-decision audit table is the
first deliberate step toward that. We do not claim a moat we do not have.

## Security model
Both buyers and sellers are untrusted; the control plane is the only trusted component.
JWT + scoped, revocable node keys; per-object authorization with negative tests; rate
limiting, request-size limits, secure headers/CSP, ORM-only SQL, shell-free subprocess;
HMAC-verified idempotent payment webhook; sanctions screen fails closed in live mode;
append-only audit log. See THREAT_MODEL for adversaries and the unresolved,
hardware-dependent items.

## Revenue mechanics
A configurable take rate (default 10%) is deducted from each completed rental — not
added on top — and split in the ledger between seller earnings and platform revenue.
The metrics dashboard reports GMV, platform revenue, seller payouts and the effective
take rate directly from settled bookings.

## Current limitations (see PRODUCTION_GAPS for the full list)
Real payment rails, KYC/AML, and vendor TEE attestation are not live; payouts run on a
sandbox ledger by default; the payout worker needs a scheduler in deploy; Alembic needs
a squashed baseline; agent auto-update needs a signing pipeline before fleet-wide use;
container-escape resistance needs live testing; the desktop agent is a drifted fork to
be unified.

## What funding enables (next 18 months)
Pilot-hardening (payout scheduler, TLS-by-default, signed updates, isolation parity) →
real money at small scale (Stripe-in, one payout rail, KYC/AML, auto-pricing) →
scale + defensibility (vendor TEE, micro-VM isolation, cross-provider routing adapters,
HA control plane). Sequenced in [ROADMAP](ROADMAP.md).
