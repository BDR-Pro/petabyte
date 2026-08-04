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
- ⚠️ **Payout worker scheduler.** `tools/payout_worker.py` exists but no systemd
  timer/cron installs it, so queued withdrawals never send. Ship
  `lumaris-payout.service` + `.timer` and install in `deploy.sh`. Payouts run in
  sandbox (`PAYOUT_STUB=true`) by default today.
- ⚠️ **Deploy safety.** `deploy-server.yml` auto-deploys prod on every push to
  `main` with no test gate, concurrency guard, or post-deploy health check; the SSH
  key is written before `chmod` and uses `StrictHostKeyChecking=no`. Gate on tests,
  add `concurrency:` and a `/healthz` assertion, harden key handling.
- ⚠️ **TLS by default.** Fresh deploys serve plaintext HTTP until a human runs
  certbot; JWTs travel in cleartext in that window. Run certbot inside `deploy.sh`
  when a domain is supplied and ship a 443 template.
- ⚠️ **Alembic baseline.** Migrations are stale (3 `add_column`, zero `create_table`);
  `alembic upgrade head` from a clean DB fails. Schema truth is `create_all` +
  `_ensure_columns` (a CI job proves it builds from empty). Autogenerate a squashed
  baseline, `alembic stamp` prod, and make CI diff `upgrade head` against `create_all`.
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
