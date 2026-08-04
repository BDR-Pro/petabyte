# Roadmap

Sequenced by what most strengthens the product and the investment case. Dates are
relative to funding close; scope, not commitments. Cross-referenced to
PRODUCTION_GAPS for the "why".

## Now (this branch)
- Deterministic investor demo (`make investor-demo`) with labelled data + reset.
- Explainable, auditable routing (`RoutingDecision` records).
- Honest trust ladder; corrected savings math and marketing claims.
- Investor/ops metrics dashboard (real queries, demo/real separated).
- P0 fixes: maintenance worker startup, payout screen fail-closed, volume
  path-traversal validation, VM stub honesty, opt-in signed-update path, uninstall fix.
- CI: demo suite, clean-DB migration check, lint, dependency + secret scanning.

## 0–3 months (pilot-ready)
- Payout worker systemd timer; TLS-by-default in deploy; deploy test-gate + health
  check + rollback.
- Squashed Alembic baseline + CI diff against `create_all`.
- Template/render/transcode isolation parity with the notebook path; sandbox-escape
  test run on a real Docker+GPU host (RLtest §17).
- Signed agent release pipeline (Ed25519 tarball + Authenticode `.exe`), then re-enable
  auto-update by default.
- 3–5 design-partner sellers and 2–3 pilot buyers on a controlled testnet; capture
  real reliability and routing data.

## 3–9 months (real money, at small scale)
- Live Stripe-in (`construct_event`) and one real payout rail end-to-end.
- KYC (Persona/Sumsub) + sanctions/AML (Chainalysis/TRM) wired to `screen()`/`/verify`.
- Demand-based auto-pricing engine using accumulated routing + utilization history
  (the auto-price fields already exist as the seam).
- Investor-facing transaction detail screen with contribution margin per rental.
- Desktop/agent unified into a shared core package.

## 9–18 months (scale + defensibility)
- Vendor TEE attestation (NVIDIA NRAS / AMD SEV-SNP / Intel TDX) → a real
  confidential-compute trust level.
- Micro-VM isolation (Firecracker/QEMU + GPU passthrough) for interactive rentals.
- Gateway hardening (authenticated node registration + TLS) and general availability
  of stable-address VM rental with failover.
- Cross-provider routing adapters (the scorer is already provider-agnostic): contribute
  hyperscaler/neocloud candidates so the router arbitrages across supply, not just our
  own nodes.
- Multi-region control-plane HA; dedicated scheduler process; SOC 2 track.

## Where defensibility accrues (honest view)
Not from any single feature, but from **data and infrastructure that compound with
volume**: normalized supply telemetry, per-node reliability history, the routing
decision corpus (every placement's inputs + outcome is already recorded), transaction
infrastructure, and increasingly effective pricing/routing models trained on that
history. The routing-decision audit table is the first deliberate step toward that
data moat.
