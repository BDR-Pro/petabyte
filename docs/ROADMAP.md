# Roadmap

Sequenced by what most strengthens the product and the investment case. Dates are
relative to funding close; scope, not commitments. Cross-referenced to
PRODUCTION_GAPS for the "why".

## Now (this branch) — landed
- Deterministic investor demo (`make investor-demo`) with labelled data + reset.
- Explainable, auditable routing (`RoutingDecision` records).
- Honest trust ladder; corrected savings math and marketing claims.
- Investor/ops metrics dashboard (real queries, demo/real separated).
- P0 fixes: maintenance worker startup, payout screen fail-closed, volume
  path-traversal validation, VM stub honesty, uninstall fix.
- CI: demo suite, clean-DB migration check, lint, dependency + secret scanning.
- **Payout worker systemd timer**; **TLS-by-default** in deploy; **deploy test-gate**
  (`deploy` `needs: [tests, …]`) + health check + rollback.
- **Squashed Alembic baseline** + CI up/down `migration` job on real Postgres.
- **Isolation flags applied to every buyer container** (cap-drop/no-new-privs/pids/
  mem/cpu + gVisor when present); shipped desktop agent hardened + loopback-only bind.
- **Ed25519-signed, fail-closed agent/desktop update channel** (`sign_release.py` +
  `release-desktop.yml`); auto-update remains opt-in.
- **`petabyte-client` pip package** (`petabyte launch`, bundled model hub) + PyPI
  release workflow; browser-uploadable desktop releases (`/admin/desktop`).
- **JWT `jti`/revocation + entropy gate, signed-double-submit CSRF, optional TOTP 2FA**;
  app-level `/login` rate limit; backup/restore DR drill + freshness gauge.

## 0–3 months (pilot-ready)
- Make strict read-only rootfs the default; sandbox-escape test on a real Docker+GPU
  host (RLtest §26).
- Extract a shared agent core so `desktop-app/` is no longer a mirrored fork.
- Schedule the biweekly Connect obligation batch (`run_biweekly_payouts.py`) as a unit.
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
