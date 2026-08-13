# Payments & trust

How money moves, and how you know a GPU is real.

## TEST MODE (the default)

Petabyte ships in **TEST MODE** — a sandbox where **no real card is charged and no real money
moves**. Every money screen shows a clear **TEST MODE** banner while the sandbox is active, so a demo
is never mistaken for a real charge. This lets you try the entire buy/sell flow safely.

Going live is a deliberate configuration step (real Stripe keys + `PAYMENTS_LIVE_ENABLED`), and even
then the code fails **safe**: if configuration is inconsistent it refuses to move real money rather
than guessing. Financial records carry an immutable **TEST/LIVE** marker so the two can never be
confused after the fact.

## Escrow (the core guarantee)

- Booking compute **escrows** the cost — it's reserved, not spent.
- As the work is delivered, escrow is **released** to the seller minus the platform fee.
- **Unused hours are refundable**, and a dropped node **refunds the buyer** automatically. You never
  pay for compute you didn't get.

## Payouts (sellers)

- Earnings accrue to a **unified balance** as jobs complete.
- Withdraw via a verified payout method (bank / USDC / gift card) after KYC where required.
- Earnings **mature** after a short hold and a minimum number of completed jobs, which protects
  against clawbacks and fraud.

## The trust ladder

Supply is **verified**, and trust is **earned by real work**, never self-reported:

1. **Attested** — the GPU cryptographically proves it exists and is what it claims. Required before
   it can be booked at all.
2. **Benchmark-verified** — Petabyte re-times the benchmark **server-side** and compares against
   public reference numbers (LLM tokens/sec, plus 3D/video benchmarks). A node can't just claim a
   score.
3. **Job-proven** — completed real jobs, with results **bound to the output bytes** (a content hash)
   so a result can be verified, and a real-job **quorum** cross-checks nodes.
4. **Confidential (TEE)** — runs inside a hardware enclave for private workloads.
5. **Region-verified** — the node's country is GeoIP-confirmed against its claim (data residency).

Buyers can filter by trust level; higher trust wins more bookings. Sanctioned wallets/countries are
screened at onboarding (fail-closed).

## Verifiable receipts

Each job produces a **verifiable per-job receipt**, and there's a public **trust page** and status
page. You can check that a result came from the GPU you paid for. See the repo `docs/` for the full
trust model and honest roadmap (what's enforced today vs. planned).

## Fees

The platform takes a transparent cut of released escrow (the take rate); the rest is the seller's
payout. Data-API usage is metered per call past a free monthly allowance. See [API & keys](api.md).
