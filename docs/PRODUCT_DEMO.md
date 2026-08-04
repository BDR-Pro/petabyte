# Product Demo — five-minute investor script

A repeatable, deterministic demonstration of the whole loop on one machine, no paid
credentials. All seeded entities are labelled "Demo data" and are separable from real
data everywhere in the product.

## Start it

```bash
make investor-demo        # validate deps → build schema → seed → health check → serve
# or, to wipe and start clean:
make demo-reset
```

The command prints the demo accounts, the shared demo password, and every URL you
need. Default base URL: `http://127.0.0.1:8000`. Ctrl-C stops the server. Re-run
`make demo-reset` to restore the initial state between runs.

Seeded supply (all labelled Demo data): five verified sellers across regions and trust
levels — H100 (benchmark-verified), A100, RTX 4090, L40 (agent-verified, no benchmark
yet), and an H100 "CC pilot" node — plus three funded demo buyers and six jobs
(completed / running / failed).

## The five-minute walk

**0:00 — The thesis (marketplace).** Open `/marketplace`. Fragmented GPU supply,
normalized into one view: model, VRAM, price, **per-class** "vs cloud" savings (note
it shows nothing where no fair comparison exists — no fake discounts), trust badge,
region, reliability, availability. Point out the "Demo data — includes simulated
nodes" badge: we never dress seeded data as real traction.

**0:45 — Trust is earned, not claimed.** Open a node detail (`/gpu/{id}`). Show the
trust level and its **evidence and limits** — agent-verified means a node key signed a
hardware report, not that the silicon is proven; the CC node is a "pilot", not
vendor-attested. This is the honesty a technical reviewer is testing for.

**1:30 — Seller side.** Sign in as a demo seller → `/seller/dashboard`. It answers the
question every real seller asks — "my GPU is on, why am I not earning?" — with
online/attested/priced/utilization diagnostics and the fix for each, plus earnings.

**2:15 — Buyer books with an explanation.** Sign in as a demo buyer → pick a template
→ launch. The platform selects a node and shows **why**: "Selected {GPU} node …
because it … costs N% less than the next eligible node … has an X% successful-job
rate." Open `/routing/decisions/{id}` (or the booking) to show the stored audit record
— every eligible candidate with its factor scores. This is the "routing layer", not a
listing site.

**3:00 — Job → result → settlement.** Watch the job move through states to a result
(clearly labelled SIMULATED — no buyer code runs in the demo). Then the money: escrow
→ seller earnings + platform fee, all through a double-entry ledger.

**3:45 — Unit economics (metrics).** Open `/metrics`. Real queries: GMV, **effective
take rate = the configured 10%**, seller payouts, buyer savings vs cloud, utilization,
completion rate, supply by region/hardware — with a persistent "Demo data" badge and a
live "ledger balanced" integrity signal. Toggle scope to "Real only" to prove demo and
real are separated.

**4:30 — Trust & audit.** Open `/admin` (as the demo admin) → the append-only audit log
and the transaction/booking history. Mention the kill switch (pauses new bookings
without disrupting running rentals) and that money conservation is proven under
concurrency in CI.

## What to say about what's not built
Be upfront: real payments, vendor TEE attestation, and KYC/AML are on the roadmap, not
live (see PRODUCTION_GAPS). The demo runs on a sandbox ledger by design. This candor is
part of the pitch — the numbers you just saw are real arithmetic over labelled data,
not a mock.

## If it fails
`make investor-demo` fails with actionable messages (missing deps, port in use, seed
error). Re-run `make demo-reset`. The demo needs only Python 3.11+ and the repo's
requirements; no Docker, GPU, or third-party accounts.
