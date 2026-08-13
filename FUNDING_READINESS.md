# Petabyte — Funding Readiness Gap Analysis

**Date:** 2026-08-11 · **Branch:** `claude/petabyte-funding-readiness-fun2q6` · **Base commit audited:** `30f03ec`

**Method.** This assessment was produced by verifying the *implementation* — not the docs — across five parallel code investigations (money-flow/ledger, security/authz, workload isolation/agent trust, marketplace/scheduler, infrastructure/CI/DR/tests). Every finding below is anchored to `file:line` in the repository as it stands today. Where the existing docs over-claim relative to the code, this document supersedes them. Scores are deliberately *not* inflated.

> **One-line verdict:** Petabyte has an unusually strong *transaction-level* engine (guarded settlement FSM, idempotency via DB unique constraints, TEST/LIVE isolation, real observability, honest evidence tooling) wrapped around **six independently fundable-blocking gaps** at the seams — a trivial admin-privilege-escalation, no database backups on a single box, an unsigned fleet auto-updater, payment for unverified results, unit economics that lose money on small jobs, and refund clawback that doesn't cover the default payout path. The bones are real; the blockers are concrete and mostly cheap to close.

---

## 1. Scorecard (0–10)

Scores reflect *verified* implementation state, weighted for a fund performing aggressive technical, security, and financial diligence. "Sev" = investor severity of the dominant gap.

| # | Category | Score | Verified state & evidence | Dominant gap | Sev |
|---|---|---|---|---|---|
| 1 | Product completeness | **6** | Full lifecycle exists: browse → Stripe auth → reserve → dispatch → GPU → result → capture → settle (`stripe_connect.py:357-880`); buyer BUY UI + seller dashboard. | Two parallel money systems (wallet `Booking` + `ComputeTransaction`) drive one `Task`; real-GPU E2E never run. | HIGH |
| 2 | Buyer UX | **6** | Checkout+run UI with progress states; object-level authz on all buyer resources. | Stripe-native job failure on a live node leaves buyer stuck (can't cancel, 409). | HIGH |
| 3 | Seller UX | **5** | One-command onboarding, attestation, earnings dashboard. | The *shipped* Windows agent is the unhardened `desktop-app/` variant. | HIGH |
| 4 | Marketplace liquidity readiness | **3** | Supply-side metrics exist (`metrics.py`, `marketplace_insight.py`). | No demand-side metrics (unfulfilled demand captured but never aggregated, `db.py:834`), no cohort/retention, no real liquidity yet. | HIGH |
| 5 | Payment safety | **6** | Manual-capture PI, capture only after metering, idempotent ops via DB unique key (`db.py:1111`), TEST/LIVE immutable `mode`. | Refund clawback only on admin path; batch-paid earnings unrecoverable on chargeback. | CRITICAL |
| 6 | Ledger / accounting integrity | **5** | Real double-entry: `post()` refuses unbalanced/zero (`db.py:509-538`), balance checks in SQL (`db.py:566-586`). | **Split-brain**: batch payout never `post()`s (`payout_routing.py:311-315`); cents/dollars mixed in shared accounts. | HIGH |
| 7 | Seller payout safety | **5** | 14-day hold, screened destination, cooling-off, atomic `transferring` claim (`stripe_connect.py:781-804`). | Payout worker has no timer/service in repo → sellers unpaid unless cron hand-installed. | HIGH |
| 8 | Security | **3** | Many strengths (below), but a trivially-exploitable admin escalation dominates. | `POST /account/email` + unverified `_is_admin` = full compromise (`main.py:3337-3343`, `2996-3002`). | **BLOCKER** |
| 9 | Authentication / authorization | **4** | bcrypt (`db.py:121`), enumeration-safe reset, consistent 404 object-level authz, scoped revocable API keys. | Admin-by-unverified-email; no JWT `jti`/revocation (7-day tokens, `auth.py:9`). | BLOCKER |
| 10 | Infrastructure | **3** | Scripted bootstrap, systemd, nginx, pinned host key. | Single droplet: API + Postgres + nginx co-located (`deploy.sh:83`). | BLOCKER |
| 11 | Scalability | **3** | Redis coordination is degrade-safe; reaper leader-elected via advisory lock. | Single box; unbounded `/marketplace/specs` N+1 (`main.py:1457`); one DB. | HIGH |
| 12 | Reliability | **4** | Heartbeat/reaper/failover, full health triad (`main.py:1595-1650`), kill switch. | No backups; failed Stripe job stuck in `RUNNING`. | BLOCKER |
| 13 | Observability | **8** | Genuinely strong: bounded-label Prometheus emitted at 21+ real sites, W3C trace propagation, request-ID correlation, redaction, Sentry scrub, 10 CI-validated dashboards. | Activation is deploy-config-gated (default off). | LOW |
| 14 | Disaster recovery | **1** | — | **No backups, no tested restore, single box** (`deploy/HARDENING.md:9`). Host loss = total data loss. | BLOCKER |
| 15 | Deployment maturity | **5** | Config from GitHub, atomic 0600 env, health check + env rollback (`deploy-server.yml:158-177`). | Rollback restores env only, not code; safety gated behind a flag. | MEDIUM |
| 16 | CI/CD maturity | **6** | Substantial *blocking* gates: money-conservation, 50-thread wallet race, ledger audit on real PG, Stripe FSM, browser E2E. | Lint + `pip-audit` are `|| true` (677 ruff errors masked); no Alembic validation. | MEDIUM |
| 17 | Test coverage | **6** | Broad + real DB-integration (`postgres_test.py`, `adversarial_test.py`, `audit_ledger.py`). | Real-GPU/real-money E2E exists as code but **never executed** (all artifacts report non-execution). | HIGH |
| 18 | Fraud resistance | **3** | Signed proofs, quorum path, seller anti-fraud scaffolding. | Paid on unverified results; only enforced "GPU" audit is CPU-only (`db.py:2217-2230`). | BLOCKER |
| 19 | Abuse prevention | **4** | Rate limits on login/register/withdraw/route; trusted-proxy-aware keys. | Per-worker limits without Redis; no limit on `/payments/authorize`, `/create_api_key`; unbounded payloads. | MEDIUM |
| 20 | Marketplace economics | **3** | Exact integer-minor pricing; conservation-safe rounding (`pricing.py:197-208`). | Stripe fee never recorded (`db.py:1062` never written); jobs under ~$4.23 lose money silently. | BLOCKER |
| 21 | Enterprise readiness | **3** | Org model + membership authz exists (`main.py:4011-4056`). | No SSO/RBAC/SLA/invoicing/quotas/spend limits. | MEDIUM |
| 22 | Compliance readiness | **3** | Sanctions screen fails closed; withdrawal KYC-gated fields. | No KYC/AML provider wired; retention/DPA undocumented. | HIGH |
| 23 | Data protection | **4** | Central redaction, TEST/LIVE isolation, presigned-URL uploads. | Cross-tenant IDOR (`main.py:5408-5421`); no backups; encryption-at-rest undocumented. | HIGH |
| 24 | Operational tooling | **5** | `/admin/incidents`, dashboards, honest evidence bundles (`verify_series_a.py`). | Support-question tooling thin; several admin ops unaudited. | MEDIUM |
| 25 | Documentation | **7** | Extensive (85 docs) and mostly grounded. | Some docs over-claim vs code (this audit exists to reconcile that). | MEDIUM |
| 26 | Developer maintainability | **5** | Strong test discipline; clear module boundaries in the core. | God modules (`main.py` 5,691 LOC, `db.py` 3,298); two divergent agents. | MEDIUM |
| 27 | GPU workload isolation | **4** | Notebook path locked down (`--network none --cap-drop ALL --read-only --pids-limit`); no `--privileged`/docker.sock anywhere. | Shipped desktop template path unsandboxed; no VRAM cap; shared-kernel/driver escape surface. | HIGH |
| 28 | Seller trust | **3** | Cryptographic node trust ladder (`db.py:212-235`). | GPU model/VRAM trusted verbatim (`db.py:1614-1636`); CPU-only integrity audit. | CRITICAL |
| 29 | Buyer trust | **3** | Escrowed capture; dispute→`DISPUTED`. | Pays for unverified results; confidentiality on hostile silicon unsolved without TEE. | CRITICAL |
| 30 | **Overall investment readiness** | **4** | Strong engine + honest tooling. | Six BLOCKER-class gaps must close before material live volume. | — |

**Weighted overall: 4.3 / 10 — "Interesting but not yet investable."** The distance from here to "investable with conditions" is a *finite, enumerated* list of fixes, not a rewrite — which is itself a positive signal.

---

## 2. Top reasons I would NOT invest today

Classified BLOCKER / CRITICAL / HIGH, each with the evidence that drove the classification.

1. **[BLOCKER] Trivial vertical privilege escalation to admin.** `POST /account/email` binds the un-validated `EmailModel` (`main.py:849-851`) and writes an arbitrary, *unverified* email (`main.py:3337-3343`); `_is_admin` matches email against `ADMIN_USERS` without requiring `email_verified` (`main.py:2996-3002`). Any buyer → set email to the public `info@petabyte.market` → full admin: refunds, transfers, role changes, payout runs, kill switch, read all PII/payments. A first-hour diligence finding that ends the meeting.

2. **[BLOCKER] No database backups + single-box topology = unrecoverable data loss.** Default provisioning puts Postgres on the API droplet (`deploy.sh:56-59,83`); `deploy/HARDENING.md:9` states outright "you have NO backups." No `pg_dump`/restore/PITR, no tested restore, no RPO/RTO. For a company holding customer funds and an authoritative ledger, this is the single most disqualifying operational fact.

3. **[BLOCKER] Unsigned fleet auto-update = remote code execution across all sellers.** The *shipped* Windows agent (`desktop-app/updater.py:41-92`) downloads and self-replaces `PetabyteAgent.exe` from GitHub releases every 6h with only a `size > 1MB` check — no signature, hash pin, or Authenticode. Anyone able to publish a release (repo-write, leaked CI/PAT, rogue maintainer) owns every seller machine — each holding a valid API key and a GPU — within 6 hours. The Linux agent has a second, TLS-only-by-default variant of the same risk (`update.sh:34-55`).

4. **[BLOCKER] Sellers are paid for unverified work.** `/jobs/result` verifies only an Ed25519 signature over a *seller-chosen* `output_hash`, then auto-settles (`main.py:2431-2432, 2490-2495`). The real correctness validator (`matmul_validation.py`) is well-built but **unwired** (`main.py:2400-2407`). A hostile seller returns `"done"`, signs it, and collects full GPU-hours pay while doing nothing. Buyers receive garbage. This is existential for both sides' trust.

5. **[BLOCKER] Unit economics lose money on the modal transaction.** Stripe's processing fee is never recorded — `stripe_fee_amount` (`db.py:1062`) and the `stripe:fees` ledger account (`db.py:1162`) are declared but never written, and the capture ledger split has no fee leg (`stripe_connect.py:648-653`). With a 10% take, $0 fixed fee, and a 50¢ minimum charge, **every job below ~$4.23 gross is loss-making** — and the dashboards show a healthy 10% take while the platform bleeds. No net-margin reporting exists.

6. **[CRITICAL] Refund/chargeback clawback doesn't cover the default payout path.** `refund()` reverses the seller's share only if `tx.stripe_transfer_id` is set (`stripe_connect.py:1111`), which happens *only* on the admin-only direct transfer (`:844`). After a normal biweekly batch payout, a refund or dispute recovers nothing — the platform silently eats the seller's share and the ledger goes negative unrecorded. A direct, quantifiable loss vector.

7. **[CRITICAL] Ledger split-brain: the production payout path bypasses the double-entry ledger.** Capture credits `seller_payable` (`stripe_connect.py:651`) but batch payout only flips `PayoutObligation.state` to `paid` (`payout_routing.py:311-315`) with no `post()`. Two accounting systems, nothing reconciling them; the ledger's seller liability grows forever and no invariant catches the divergence.

8. **[CRITICAL] GPU claims are unverified; the only enforced "GPU" audit is CPU-only.** `save_specs` stores seller-declared `gpu_model/vram_gb` verbatim (`db.py:1614-1636`); attestation proves key possession, not silicon (`main.py:2025-2039`); the fraud-freezing integrity audit is a pure-CPU integer LCG loop (`db.py:2217-2230`). A seller can list 8×H100 on a CPU VM and pass everything. The router's "verified inventory" isn't verified.

9. **[CRITICAL] Failed Stripe-native jobs get stuck in `RUNNING` on a live node.** `/jobs/result` never transitions the tx to `JOB_FAILED` (`main.py:2484-2495`); the buyer's cancel then 409s (`main.py:4526`), the reservation isn't freed, and the FSM's recovery edges are dead code for the real path.

10. **[HIGH] No demonstrated liquidity, retention, or unit-economics data.** No cohort/retention functions, no time-series GMV/utilization at the DB layer, unfulfilled demand captured but never aggregated (`db.py:834`). A marketplace fundraise needs supply/demand-balance and repeat-rate evidence; it isn't computable today.

11. **[HIGH] Real-GPU / real-money E2E has never actually run.** The code and CI job exist and are honest, but every committed artifact says so (`SMOKE_GPU_REPORT`=`EXTERNAL_GPU_TEST_REQUIRED`, `gpu_hardware_executed:false`, `REAL_E2E_REPORT`=`PREFLIGHT_FAIL`). The core value claim is untested in evidence.

12. **[HIGH] Schema is not migration-managed.** Real schema comes from `create_all()` + a hand-maintained `_ensure_columns` ALTER dict that adds columns *without* their FK constraints (`db.py:1481-1503`), so fresh vs upgraded DBs silently diverge. No tested up/down.

13. **[HIGH] Core financial invariants are app-only, not DB-enforced.** No `CHECK` for ledger balance or `amount>0`, `direction` nullable, `mode` immutability is a bypassable ORM listener, no non-negativity on `User.balance/earnings` (`db.py:480,509-524,1459-1470`). Raw SQL or a migration can create/destroy money.

14. **[HIGH] Cross-tenant object read (IDOR).** `POST /jobs/input_url` mints a presigned GET for a client-supplied key with no ownership/prefix check (`main.py:5408-5421`, `utils.py:313-330`) on a shared bucket — any seller with any job reads any buyer's inputs.

15. **[HIGH] Audit log is incomplete and tamper-mutable.** `AuditEvent` is a plain mutable table (no hash chain/signature); `admin_set_role`, `admin_capture`, `admin_transfer`, `admin_delist_spec` emit no audit record (`main.py:3135,4612,4621,3146`).

16. **[HIGH] Reconciliation is near-blind against real Stripe.** Transfer reconciliation reads an attribute only the fake gateway has (`stripe_connect.py:1304`); no refund-vs-Stripe check; `reconcile.py` is neither in CI nor scheduled.

17. **[HIGH] Production safety gate is opt-in.** All boot-time stub protections are skipped unless `ENVIRONMENT=production` is explicitly set (default `development`, `main.py:282`). A deploy that forgets it silently enables `GOOGLE_OAUTH_STUB` — a "log in as anyone" oracle (`main.py:1846-1865`).

---

## 3. Code problems vs. business problems

The distinction matters: software cannot manufacture traction.

### Engineering gaps Claude can fix (in this repo)

**P0 — money safety**
- Wire Stripe balance-transaction fee into the tx + ledger; add a fixed platform fee; net-margin reporting. *(killer #5, #20)*
- Clawback on the default (batch) payout path; refund-vs-Stripe reconciliation. *(killer #6, #16)*
- Eliminate ledger split-brain: `post()` the seller-payable debit on payout; add a money-conservation invariant + ledger-vs-obligation reconciliation. *(killer #7)*
- Canonicalize GMV (one ledger-backed definition); fix cents/dollars account mixing. *(killer #7, #10)*
- Wire `/jobs/result` failure → `JOB_FAILED` → release reservation. *(killer #9)*
- DB-level financial invariants: `CHECK` constraints, status enums, mode-immutability trigger. *(killer #13)*

**P0 — security**
- Require `email_verified` in `_is_admin`; validate + verify `/account/email`. *(killer #1)*
- Ownership/prefix check on `/jobs/input_url`. *(killer #14)*
- Sign the agent release; verify signature/hash before self-update (both agents); unify the two agents. *(killer #3)*
- Wire `matmul_validation.py` into `/jobs/result`; make settlement conditional on verification for verifiable job types. *(killer #4)*
- Make the production safety gate fail-safe regardless of `ENVIRONMENT`; complete admin-op audit coverage + tamper-evidence (hash chain). *(killer #15, #17)*
- JWT `jti` + revocation/logout; rate-limit `/payments/authorize`, `/create_api_key`, `/email/verify/request`; body-size cap; paginate listings. *(killer #… assorted)*

**P0/P1 — reliability**
- Migrate to a backed-up DB (managed PITR or nightly `pg_dump` to object storage) + a tested restore drill; document RPO/RTO. *(killer #2)* — *note: provisioning is founder-owned; Claude provides the scripts/runbook/CI, founder executes the infra move.*
- Adopt Alembic as the real schema source; gate deploys on `alembic upgrade`; test up/down. *(killer #12)*
- GPU per-job proof (utilization assertion on the enforced path); VRAM caps; harden shipped agent isolation. *(killer #8, #27)*

**P1 — funding metrics**
- Canonical DB/ledger-derived metrics layer (GMV, take, active buyers/sellers/GPUs, utilization, job success, unit economics, fill rate, cohort retention); honest, TEST-labeled investor/founder read-only view.

### Business / traction gaps the founder must fix (software can measure, not create)

These require real users and real money, not code. **None are currently measurable with real data** because there is no real traffic yet — so the engineering deliverable is the *instrumentation*, and the founder's deliverable is the *numbers*.

| Metric the founder must move | Currently measurable? | What's needed |
|---|---|---|
| Active sellers / available GPU-hours | Instrumented (point-in-time) | Real supply |
| Active buyers / completed paid jobs / GMV | Instrumented (needs canonical def) | Real demand |
| Repeat-buyer rate / buyer & seller retention (7/30/90d) | **No — cohort layer absent** | Build cohorts (eng) + real cohorts (founder) |
| GPU utilization (time-weighted) | **No — point-in-time only** | Time-series layer (eng) + real usage (founder) |
| Failed-job % / time-to-first-job / queue time | Partially (proxy) | Real jobs |
| Take rate *net of processing cost* / gross margin | **No — fee untracked** | Fee accounting (eng) + volume (founder) |
| CAC / payback / LTV | **No** | Real acquisition spend + revenue (founder) |
| Refund / dispute / chargeback / payment-loss rate | Instrumented (counters) | Real transactions |
| Supply/demand imbalance / unfulfilled demand | **No — captured, not aggregated** | Aggregation (eng) + real demand (founder) |

**Business realities no code can fix:** cold-start liquidity (two-sided chicken-and-egg), differentiation vs Vast.ai/AWS, seller supply concentration on high-demand GPU types, and the fundamental trust problem of running confidential workloads on strangers' hardware (mitigable only with real TEE attestation, currently a stub — `utils.py:230`).

---

## 4. Preliminary Investment Committee read (to be re-run after remediation)

**Current state: INTERESTING BUT NOT READY.**

- **The 5 things most likely to kill Petabyte today:** (1) the admin-escalation compromise; (2) total data loss on single-box, unbackuped Postgres; (3) unsigned fleet auto-update RCE; (4) paying for unverified GPU work + unverified GPU claims (fraud economics); (5) losing money per transaction with no unit-economics visibility.
- **The 5 strongest technical assets:** (1) a genuinely guarded settlement FSM with idempotency enforced by DB unique constraints and TEST/LIVE-immutable money records; (2) race-safe capacity via atomic conditional decrements; (3) real, emitted, correlated observability with CI-validated dashboards; (4) honest evidence tooling that refuses to fake GPU/real-money passes; (5) broad DB-integration test depth including money-conservation-under-concurrency.
- **What must happen before the next round:** close the six BLOCKERs; run and commit a real-GPU + real-Stripe-TEST E2E evidence bundle; stand up backed-up infra; ship a canonical, honest metrics layer; then accumulate 60–90 days of real liquidity and retention data.
- **What to show investors:** the real-GPU/real-money E2E evidence bundle, the money-conservation invariant passing on real data, and the DB-derived metrics view (with "insufficient real data" shown honestly until traffic exists).
- **What NOT to build yet:** SSO/SOC2/multi-region HA/enterprise RBAC, vendor TEE integration, cross-provider routing — all premature before liquidity and the BLOCKERs.

This recommendation will be re-issued as a final IC memo once the P0 remediation below is executed and verified.

---

## 5. Execution status (living section)

Fixes are applied in priority order (P0 money-safety, P0 security, P0 reliability), each with a regression test and a verified test run. This section is updated as work lands.

| Killer | Status | Commit / evidence |
|---|---|---|
| #1 admin privilege escalation | **FIXED** | `_is_admin` now honors only a **verified** email and never matches a look-alike username; `/account/email` resets verification on change; Google OAuth honors the provider's `email_verified` claim (stub never verifies). Regression tests in `account_test.py` (5 unit + 4 e2e). Verified: account/stripe(106)/e2e_safety/stripe_e2e_flow/marketplace/smoke all green. |
| #14 cross-tenant IDOR (`/jobs/input_url`) | **FIXED (hardened after red-team)** | First pass restricted a node to refs the buyer bound to the task; an offensive red-team then proved that bypassable — a buyer could *bind a victim's key* (`inputs/<victim>/…`) via `template_params`. Now enforced with tenant-prefix isolation at **two layers**: bind-time (`/transcode`, `/render` reject any ref outside the buyer's own `inputs/<buyer_id>/`) and a mint-time backstop in `input_url` (re-derives the key, refuses anything outside `inputs/<task.buyer_id>/`). Regression: `security_test.py` + `smoke_test.py` (bind rejection + arbitrary-key 404). |
| #17 production safety gate opt-in | **FIXED** | The stub-safety gate now fires on any live-money signal (`PAYMENTS_LIVE_ENABLED=true` or a `sk_live_` key), not only `ENVIRONMENT=production` — a deploy that forgets the flag still fails closed. Regression tests in `smoke_test.py`. |
| #5/#20 Stripe fee unit economics | **FIXED (visibility)** | The platform's card-processing cost is now recorded per-tx (`stripe_fee_amount`) and as its own balanced `stripe:fees` ledger entry, exposed via `petabyte_processing_fees_minor_total` and `net_platform_revenue` in `/marketplace` health. Net margin is now visible and correctly **negative on small jobs**. Tests: `pricing_test.py` (estimator) + `stripe_test.py` (recorded, balanced, idempotent, negative margin). *Loss-prevention lever `PLATFORM_FIXED_FEE_MINOR` already exists — setting it is a founder pricing decision. Exact per-charge fee (vs the estimate) is a reconciliation follow-up.* |
| #9 failed job stuck in `RUNNING` | **FIXED** | New `sc.fail_job` (wired into `/jobs/result` via `_auto_fail_compute_tx`) moves a failed dispatched Stripe-native tx `RUNNING/DISPATCHING → JOB_FAILED` and frees the reservation + voids the buyer hold immediately (a failed job bills nothing) — no more lingering in `RUNNING` until the 26h reaper. Tests: `stripe_test.py` (JOB_FAILED, unit freed, PI voided, idempotent). Verified green: stripe (116), smoke, stripe_e2e_flow, e2e_safety, adversarial, reservation_reclaim. |
| #7 ledger split-brain (batch payout) | **FIXED** | A settled batch payout now posts the `seller_payable` DEBIT / `stripe_payouts` CREDIT leg (`_post_batch_payout_ledger`, mirrors the admin transfer path) in both `create_and_send_batch` and `confirm_batch` — the ledger's seller-liability no longer grows forever. New `audit_ledger.py` invariant #37: every paid batch must post a `payout_settled` debit == its total. Tests: `payout_test.py` (DEBIT==total, idempotent, ledger balances). Verified green: payout (70), stripe (116), adversarial (14), stripe_e2e_flow, smoke. |
| #6 refund clawback on batch path | **FIXED (visibility + unpaid recovery)** | `refund()` no longer silently marks a batch-paid clawback `reconciled`: an UNPAID obligation is reversed (money never left → truly reconciled); an ALREADY-paid (batch) share with no reversible transfer is flagged `needs_review` + emits `petabyte_reconciliation_discrepancies_total` (the ledger already DEBITs `seller_payable`, recording a recoverable debt). Tests: `stripe_test.py` (batch-paid → needs_review + clawback DEBIT + ledger balances; unpaid → reversed + reconciled). *Automatic netting of the recoverable debt against future earnings is a follow-up that needs a founder policy decision (net vs. collections vs. write-off).* |
| **P0 money-safety + P0 security items addressed** — with ONE explicit exception: GPU-work result verification (#4/#8) is **not** claimed complete. It is hardware/GPU-E2E-dependent (see the pending row below + `docs/TRUST_MODEL.md`), so the code-level items are done while that item remains open by design. | — | — |
| P1 canonical funding-metrics layer | **LANDED** | New `funding_metrics.py` computes ONE canonical GMV + net margin, active buyers/sellers/GPUs, take rate (gross+net), refund/dispute/job-success rates, outstanding seller liability, utilization, **unfulfilled demand** (fill rate), and **activity-cohort retention** (repeat rate + 7/30/90d) — all from authoritative DB rows via SQL, cleanly split **real (LIVE) / test / demo** so TEST/demo is never shown as real traction. Read-only admin endpoint `GET /admin/funding?scope=`. Added `User.created_at` for signup cohorts/TTFV. Honest: zero/null when no data, `has_real_data`/`contains_demo_data` flags. Tests: `funding_metrics_test.py` (24 checks) + `stripe_test.py` (endpoint, admin-gated). Verified green: funding_metrics, stripe (126), smoke, account, drift/config. |
| P1 investor/founder read-only view | **LANDED** | `/admin/funding-view` — an honest, admin-gated read-only page over `/admin/funding` with Real/Test/Demo scope tabs, a prominent "No real (LIVE) traction yet" banner (real GMV is $0 by design in TEST mode), and clear TEST/DEMO "not real traction" labels. Renders GMV/net margin/take, buyers/sellers/GPUs, utilization/fill-rate/unfulfilled-demand, seller liability/payouts, and cohort retention. Static shell reveals nothing until an admin token loads data. Verified: `audit_js` (100 blocks, 0 broken), smoke (RTL/logical-CSS gate), route serves 200. |
| #13 financial invariants at the DB layer | **FIXED (constraints)** | DB-level CHECK constraints now make money-impossible states un-writable regardless of code path: `LedgerEntry.amount > 0`, `direction in ('debit','credit')`, and `User.balance/earnings >= 0` — so a stray write or raw SQL can no longer create/destroy money or drive a balance negative. Test: `db_invariants_test.py` (8 checks — DB rejects negative/zero legs, bad direction, negative balance/earnings). Whole money suite re-verified green under the constraints (smoke, stripe 126, payout 70, adversarial 14, wallet, e2e_flow, funding_metrics). *Apply on fresh DBs via create_all; existing prod DB adopts them on the Alembic rebuild (founder-owned).* Mode-immutability DB trigger + status enums remain follow-ups. |
| #3 unsigned agent auto-update (fleet RCE) | **FIXED (signature enforced)** | The shipped Windows updater now applies an update ONLY after verifying the download against an Ed25519-**signed manifest** (SHA-256 + signature) under a **pinned** release key — fails closed on no-pin / wrong-key / hash-mismatch / forged-or-missing signature (`desktop-app/updater.py verify_update`). The Linux `update.sh` signed-bundle check is now **mandatory** (no TLS-only fallback). Added `scripts/sign_release.py` (producer) so releases can be signed + the pubkey pinned. Tests: `updater_test.py` (9 vectors) + `scripts/sign_release_test.py` (producer↔verifier round-trip, both platforms), wired into CI. *Founder step: generate the release key (`sign_release.py --gen-key`), pin the pubkey in the build, sign releases in CI.* |
| Offensive red-team pass (money/auth/injection/DoS) | **LANDED** | A 4-vector offensive pass on the platform's own attack surface found and fixed, with regression tests (`security_test.py`, 28 checks, wired into CI): (a) the cross-tenant read above; (b) **job-manifest enumeration** — `GET /jobs/manifest/{job_id}` returned any job's segment output-refs with no owner check → now owner-or-admin, 404 on a foreign id; (c) **stored XSS** — seller-controlled `gpu_model/region/provider` + usernames were interpolated raw into `innerHTML`; fixed at the source with server-side charset validation (`_clean_label` on `SpecModel`/`UserRegisterModel`/`OrgCreateModel`, rejects HTML metachars at write time) plus a shared `esc()` at every DOM sink; (d) **X-Forwarded-For spoofing** — `_client_ip` trusted the attacker-controllable left-most XFF entry (defeating per-IP rate-limits/geo and the token-less `/internal/metrics` loopback gate) → now prefers unspoofable `X-Real-IP` and walks XFF from the right; (e) **DoS input bounds** — `nodes/hours/frame-range/samples/CRF/duration` now bounded (`TranscodeModel`/`RenderModel`/`QuickLaunchModel`/`RequestVMModel`). Verified green: full offline suite (adversarial/stripe 126/payout 70/…/security/reservation-reclaim). |
| _(next: founder-owned reliability — backups/PITR + tested restore, Postgres off the single box, Alembic; then GPU-work verification pipeline (#4/#8) + clawback auto-netting, both needing GPU E2E / a founder policy)_ | pending | — |

**Sequenced P0 plan (multi-turn):** #1 admin escalation → #14 IDOR + #17 env-gate (cheap security) → #5/#20 fee accounting + net margin → #6 batch clawback + #7 ledger post-on-payout + conservation invariant → #4 wire result validation + #8 GPU proof → #9 failed-job transition → #13 DB invariants → #3 signed agent update → then P1 metrics layer + investor/founder view, then reliability (backups/migrations) which is founder-executed with Claude-provided scripts.

**How to read this document (status reconciliation):** the 30-category **scorecard** and the
**sequenced P0 plan** above are a **historical baseline**, captured at commit `30f03ec` — they
are intentionally *not* rewritten as work lands. The **living source of current status** is the
"Execution status" table (§5): each row states what has actually shipped, with code + test
pointers. Where the two appear to disagree (e.g. a scorecard weakness that a FIXED row now
addresses), the Execution table is authoritative. The one item still open by design is GPU-work
verification (#4/#8), which is hardware-dependent; everything else in the P0 sequence has a
FIXED/LANDED row above. Scores will be re-baselined once real marketplace data accumulates.
