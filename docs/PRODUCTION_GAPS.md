# Production Gaps

An honest, prioritized list of what is **not** production-ready, grouped by the
milestone at which each must be fixed. This is the companion to
[`FUNDING_READINESS_AUDIT.md`](FUNDING_READINESS_AUDIT.md); it exists so a technical
diligence reviewer finds the gaps here rather than discovering them uncomfortably.

Legend: ✅ addressed in this branch · ⚠️ documented, not yet done.

## Must fix before investor demos
- ✅ Deterministic demo mode with labelled data and reset (`make investor-demo`).
- ✅ Honest savings math and trust levels; no fabricated discounts or fake TEE claims.
- ✅ Production maintenance worker starts (reaper import fix).
- ✅ Broken `/gpu/{id}` links; misleading "fully built" investor copy corrected.

## Must fix before pilots
- ✅ **Payout worker scheduler.** Shipped `deploy/lumaris-payout.service` (oneshot,
  hardened like the reaper) + `deploy/lumaris-payout.timer` (every 5 min,
  `Persistent=true`). `deploy.sh` installs and `enable --now`s the timer on fresh boxes,
  and `update.sh` syncs the units + arms the timer on already-provisioned hosts, so queued
  withdrawals now send. Safe by default: `PAYOUT_STUB=true` simulates until a real provider
  is configured.
- ✅ **Deploy safety.** `deploy-server.yml` now gates prod on the FULL test suite —
  `deploy` `needs: [tests, configuration-preflight]`, where `tests` reuses `tests.yml`
  via `workflow_call` (the money/security/config/schema/Postgres jobs are hard blockers;
  the flake-prone P1 browser-E2E job is `continue-on-error`, independently covered by
  `browser-e2e.yml`). Concurrency guard (`concurrency: deploy-server`), pinned host key
  (`StrictHostKeyChecking=yes` + `known_hosts`), post-deploy `/healthz` gate, and env
  rollback-on-failure were already in place.
- ✅ **TLS by default.** `deploy.sh` now issues a Let's Encrypt cert automatically the
  moment the domain resolves to the box (HTTP-01 needs that): it sets the real
  `server_name`, runs `certbot --nginx … --redirect`, and arms `certbot.timer` for
  renewal. If DNS isn't pointed here yet it skips without failing the deploy and prints the
  one manual command — so a fresh box is HTTPS the moment DNS is ready, never silently
  plaintext once it is.
- ✅ **Alembic baseline.** A squashed baseline now builds the schema from a clean DB, and
  a CI `migration` job runs `alembic upgrade head` (and downgrade) on real Postgres.
- ⚠️ **`/login` app-level rate limit.** Brute-force protection on `/login` is
  nginx-only; add it to the app failure-budget limiter as defence in depth.

## Must fix before handling real money
- ⚠️ **KYC/AML/sanctions.** `screen()` now fails closed in live mode, but no real
  provider (Chainalysis/TRM) or KYC (Persona/Sumsub) is integrated. Legal + compliance
  review of the payout and any idle-mining revenue flow is required.
- ⚠️ **Live payment provider review.** Stripe-in and provider payouts are written as
  real adapters but unexercised; swap the generic webhook check for
  `stripe.Webhook.construct_event` and security-review each provider relationship
  (`docs/stub.md` #4, #5).
- ⚠️ **Secret handling in deploy.** `deploy.sh` passes env via `env $(… | xargs)`,
  exposing secrets in the process table; switch to `EnvironmentFile`/`set -a`.
- ⚠️ **Rotate historically committed secrets** before any real deploy (`SECURITY.md`).

## Must fix before executing untrusted customer workloads (at scale)
- ⚠️ **Signed agent updates.** The auto-update channel is not cryptographically
  signed. It is now opt-in, the unit is hardened, and `update.sh` has a pinned-key
  verify hook — but the release-signing pipeline (Ed25519 for the tarball,
  Authenticode for the `.exe`) must be built before fleet-wide auto-update is enabled.
- ⚠️ **Sandbox-escape verification.** Container isolation flags are coded (strongest
  on the notebook path); escape resistance must be tested on a real Docker+GPU host
  (`docs/RLtest.md` §17). Template/render/transcode paths need cap-drop/read-only
  parity with the notebook path.
- ⚠️ **Desktop agent parity.** `desktop-app/` is a drifted fork of `lumaris_agent/`;
  the shipped Windows copy lost isolation flags and binds containers to all
  interfaces. Extract a shared core package so isolation logic lives in one place.
- ⚠️ **Micro-VM isolation.** Firecracker/QEMU + GPU passthrough is roadmap; the
  placeholder backends now `raise NotImplementedError` (they previously returned fake
  "running" endpoints).

## Must fix before enterprise deployment
- ⚠️ Vendor TEE attestation (NVIDIA NRAS / AMD SEV-SNP / Intel TDX) to back a real
  confidential-compute trust level (`docs/stub.md` #3).
- ⚠️ SOC 2 / formal security program, data-residency guarantees beyond IP GeoIP
  (which is VPN-defeatable), multi-region control-plane HA, and a dedicated
  `petabyte-scheduler` process separate from the web tier.
- ⚠️ Gateway hardening: authenticated node registration + TLS on the connection
  gateway before it is deployed (currently standalone, not wired into deploy).

## Deferred / low priority
- Package rename `lumaris_* → petabyte_*` (cosmetic).
- NiceHash idle-mining: stubbed, unit-mismatched, unscheduled — keep off and out of
  the revenue story.
- `pricing_references` table with source/date/region attribution for cloud reference
  prices (today they are an in-code table with a disclaimer).
