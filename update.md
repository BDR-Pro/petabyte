# update.md — everything changed from the original

A complete record of how this bundle differs from the uploaded `Petabyte.zip`
(`lumaris_api-master` + `lumaris_agent-main`). Grouped by area, with the original
problem and what replaced it. The API is covered by an automated `smoke_test.py`
(**51 assertions, all passing**); agent host-side logic is import/behavior-checked;
GPU/KVM/Firecracker/Docker/exe paths are corrected by review (need real hardware
to execute).

---

## 0. Critical hygiene

- **Leaked secrets removed.** The original `lumaris_api/.env` committed real
  `WG_PRIVATE_KEY`, `SECRET_KEY`, and `SERVER_PRIVATE_KEY`. They are **compromised**
  and must be rotated (see `SECURITY.md`). This bundle ships no `.env` and no
  `dev.db`; it adds `.gitignore` + `template.env`.

---

## 1. API security fixes

| # | Original problem | Fix |
|---|------------------|-----|
| 1 | `gen_config_record` returned the **server's WireGuard private key** to every client | Per-request client keypair; server stores only the client pubkey; returns the client config. Server key never leaves the host. |
| 2 | Passwords hashed with `sha256_crypt` | **bcrypt** |
| 3 | `change_role` was a state-mutating **GET toggle** (CSRF-prone; authz decorative) | Authenticated **POST** with explicit role |
| 4 | `save_specs` wrote the username into an Integer column (broke on Postgres) | Resolve `user.id` first |
| 5 | Session leaks: `SessionLocal()` / `get_db().__next__()` never closed | Dependency-injected sessions everywhere |
| 6 | JWT expiry in local time; silent if `SECRET_KEY` missing | UTC-aware expiry; fail-fast on missing secret |
| 7 | API keys non-revocable | `jti` + revocation denylist + `/revoke_api_key` |
| 8 | `CORS allow_origins=["*"]` with credentials (insecure/invalid) | Env-driven allow-list (`ALLOWED_ORIGINS`) |
| 9 | `/prove` attestation was a `print()` stub | Real **Ed25519** signature verification |

## 2. API reliability

- **No double-sell:** atomic conditional UPDATE on `available_units`.
- **Idempotent bookings:** `Idempotency-Key` header (claim-before-side-effects).
- **Node liveness:** heartbeat + background **reaper**; offline specs unbookable.
- **Race-safe WireGuard IP allocation;** `pool_pre_ping` + statement timeout on Postgres; SQLite WAL + busy_timeout.
- **Health/readiness:** `/healthz`, `/readyz`; global exception handler (no stack traces leaked).

## 3. Task / job dispatch (secured)

- Original protocol let **any agent run any task** (shared key; tasks not tied to payment).
- Now a `Task` is tied to a paid **Booking** + spec. `GET /jobs/next` atomically
  claims work **only for specs the agent owns** (ownership = authz boundary);
  `/jobs/result` and `/jobs/vm_details` accept submissions only from the owning agent.
- The old hardcoded heartbeat status-code protocol (200/202/426 + `/send_task`) was
  removed in favor of `/heartbeat` (liveness) + `/jobs/next` (work).

## 4. Trust layer (new)

- **Signed proof-of-work:** `/prove` stores the node's Ed25519 pubkey; `/jobs/result`
  requires a signed proof (`output_hash` + `ts`) verified against it — binding each
  result to attested hardware. Forged/expired proof → 401 + reputation penalty.
- **Known-answer test workloads:** `POST /dispatch_test` queues a deterministic
  **integer** job (reproducible across GPUs — float results are not bit-identical);
  result hash is checked against the server-computed answer.
- **Reputation gating:** pass/fail moves a per-seller `reputation`; below
  `MIN_REPUTATION` the seller's specs become unbookable for paid work.
- **Buyer result retrieval:** `GET /tasks/{id}`.

## 5. Settlement (new)

- **Wallet:** buyers hold `balance`, sellers accrue `earnings`.
- **Escrow on booking:** funds atomically debited and held; insufficient → 402.
- **State machine** `escrowed → active → released | refunded`, with guarded
  conditional updates so a booking settles **exactly once**.
- **Auto-release** on successful job completion (seller + platform paid with the take-rate split).
- **Refund-on-reap:** the reaper refunds in-flight bookings of dead nodes, frees
  capacity, and fails their tasks — idempotently.
- **Append-only ledger** (deposit / escrow_hold / release_seller / release_platform /
  refund_buyer); `GET /bookings/{id}`, `POST /bookings/{id}/release`.

## 6. Marketplace + demo layer (new)

- `GET /specs` (bookable inventory, price-sorted) and `GET /marketplace/stats`.
- **CLI** `cli/petabyte.py`: `register/login/deposit/wallet/specs/run`. `run` books
  the cheapest matching GPU → escrow → dispatch → poll → print result. (E2E tested.)
- **Buyer dashboard** served at `/` (same-origin): live stats, wallet, GPU
  inventory with a live **$/hr-vs-AWS savings column**, one-click runs.
- **Bug fixed:** `/jobs/next` returned a body on `204 No Content` (uvicorn rejected it) → proper empty 204.

## 7. Payments / go-live (new)

- `/deposit` gated by `PAYMENTS_MODE` (`sandbox` mints test credits; `live` → 403).
- **Signed payment webhook** `POST /webhooks/payment`: HMAC-SHA256 over the raw body,
  idempotent on `event_id`. (Swap for `stripe.Webhook.construct_event` — see `deploy.md`.)
- Dashboard AWS reference price is env-driven (`AWS_REFERENCE_PRICE`), injected at serve time.

## 8. Agent (lumaris_agent)

| Area | Original | Fix |
|------|----------|-----|
| **RCE** | `notebook.py` ran untrusted buyer code **directly on the host** | Locked-down Docker sandbox: `--network none`, `--cap-drop ALL`, no-new-privileges, read-only rootfs + tmpfs, CPU/RAM/PID limits, output cap. **No host fallback** (refuses if Docker absent). |
| **Protocol** | hardcoded `"supersecretkey"`, wrong endpoints, prod URL baked in | Real `X-API-KEY`; `/jobs/next` + signed `/jobs/result`; all config via env. |
| **Heartbeat** | ran the job synchronously inside the heartbeat loop (long jobs → node reaped) | Heartbeat on its own thread, decoupled from execution. |
| **Signing** | none | `crypto.py`: one Ed25519 identity for attestation **and** signed results (verified to interop with the API and to produce identical test hashes). |
| **VM bugs** | QEMU `format=raw` (cloud image is qcow2; silent boot fail + cross-tenant disk sharing); Firecracker control via unsupported `requests http+unix://`; bzImage used as Firecracker kernel | qcow2 + per-tenant overlay; Firecracker via httpx UDS; bzImage/IOMMU caveats documented; Docker "VM" hardened. |
| `ui.py` | hardcoded secret | reads config from env |

**New agent files:** `crypto.py`, `attest_node.py`, `provision.py`, `install.sh`,
`petabyte-agent.service`, `.env.example`, `INSTALL.md`.

## 9. Deploy + onboarding (new)

- `lumaris_api/deploy/`: `deploy.sh`, `gunicorn_conf.py`, `lumaris-api.service`,
  `lumaris-reaper.service`, `nginx-lumaris.conf`, `DEPLOY.md`.
- **One-line node installer** (`install.sh` + `provision.py`): detect hardware →
  register → attest → mint key → start service. Verified end-to-end to produce a
  bookable node.
- Root docs: `deploy.md` (this deployment guide), `SECURITY.md`, `FIXES.md`,
  per-component READMEs.

---

## What could NOT be executed in this environment (needs real hardware)

- QEMU / Firecracker boot, GPU (VFIO) passthrough — require KVM + a GPU.
- The Docker notebook sandbox — requires a Docker daemon (the logic and the
  no-host-fallback safety check are verified; container flags need a daemon to run).
- The Windows `.exe` packaging.

These are corrected by code review and clearly guarded; test on a real seller node
before production.

---

## Test coverage (`lumaris_api/smoke_test.py`, 51 assertions, all passing)

capacity/oversell, idempotency, heartbeat/reaper liveness, WireGuard safety,
job dispatch + ownership boundary, signed proof-of-work, forged-signature
rejection, known-answer pass/fail, reputation-gated paid work, escrow → release
with payout split, double-release guard, refund-on-reap (made whole + idempotent),
and the signed payment webhook (credit / bad-sig 401 / replay idempotent).
The CLI and the installer's provisioning path are verified end-to-end against a
live server.

## 10. Confidential computing / TEE (added)

- `POST /attestation/challenge` (server-issued nonce, replay protection),
  `POST /prove_tee` (verify TEE report: nonce + freshness + measurement allowlist
  + vendor signature → mark spec `confidential`).
- Pluggable verifier (`utils.verify_tee_report`): tested Ed25519 stub; seams
  documented for NVIDIA NRAS / AMD SEV-SNP / Intel TDX.
- `GET /specs/{id}/attestation` for **buyer-side** independent verification before
  sending data; `GET /specs?confidential=` filter; `request_vm
  {require_confidential}` gate.
- New fields: `SellerSpec.confidential/tee_vendor/tee_measurement/tee_report`;
  `AttestationChallenge` table. Env: `TEE_TRUSTED_ROOT`, `TEE_MEASUREMENT_ALLOWLIST`.

## 11. Organizations + data residency (added)

- `Organization` + `OrgMember` (roles admin/billing/member), shared wallet with
  `budget_cap`, `Booking.org_id`. Endpoints: `POST /orgs`, `GET /orgs/{id}`,
  `POST /orgs/{id}/members`, `POST /orgs/{id}/deposit`, `GET /orgs/{id}/usage`.
- Org-charged booking: `request_vm {org_id}` debits the org wallet atomically with
  budget-cap enforcement; refunds (incl. refund-on-reap) return to the org.
- Data residency: `SellerSpec.region/country`; `GET /specs?region=` filter;
  `request_vm {require_region}` gate (composable with `require_confidential`).

## 12. GeoIP region verification (added)

- `SellerSpec.detected_country` + `region_verified`; set on heartbeat from the
  node's source IP via pluggable `utils.geolocate_country` (GEOIP_STUB for tests,
  GEOIP_DB/MaxMind for prod).
- Residency gate hardened: `require_region`/`require_country` now require
  `region_verified` (self-declared region no longer satisfies a residency ask).
- `/specs` exposes `detected_country`/`region_verified`.

## 13. Templates / benchmarks / job mgmt / scoped keys / analytics (added)

- Templates: `GET /templates`, `create_task` template support, `jobs/next` template
  payload; agent `_run_template` (GPU + HF model + cache volume).
- Benchmark: `POST /benchmark`, signed `POST /jobs/benchmark_result`,
  `SellerSpec.benchmark_tokens_sec` surfaced in `/specs`.
- Job mgmt: `Task.priority/progress/retries`, `POST /tasks/{id}/retry`,
  `POST /jobs/progress`, `POST /jobs/log`, WebSocket `/ws/tasks/{id}/logs`.
- Scoped API keys (`create_api_key?scopes=`, enforced via require_scope);
  `GET /orgs/{id}/analytics`. SSO deferred (named-deal fast-follow).

## 14. Backup / restore + game servers (added)

- `Checkpoint` table; `Task.backup_enabled/backup_interval_s/volume/latest_checkpoint_ref/interrupted_at`.
- `POST /jobs/checkpoint` (signed), `GET /tasks/{id}/checkpoints`, `POST /tasks/{id}/restore`;
  `jobs/next` carries backup config + `restore_from`.
- `settle_dead_specs` reschedules backup tasks (grace fallback to refund via
  `BACKUP_RESCHEDULE_GRACE_S`); non-backup behavior unchanged.
- Game-server templates (minecraft/valheim/factorio); agent backup/restore helpers.

## 15. Secure backup uploads (added)

- `POST /jobs/backup_url` / `POST /jobs/restore_url`: per-object pre-signed PUT/GET,
  tenant-prefixed keys, per-task client-side encryption key (sealed at rest),
  content-hash integrity on restore. Nodes hold no standing S3 credentials.
- `Task.enc_key`; `utils.mint_presigned_put/get`, `seal_secret/open_secret`.
- `deploy.sh` bucket auto-create + hardening; S3 env placeholders in template.env.

## 16. Reputation / AI Router / Render (added)

- Reputation: `ReputationEvent` log + spec counters; `compute_reputation` (derived
  score); events on completion/failure/fraud/benchmark/heartbeat;
  `GET /specs/{id}/reputation`; `reputation_score` in `/specs`.
- Router (`router.py`, `POST /solve`): intent -> ranked placement plan over verified
  own inventory; distinct-provider redundancy; provider-agnostic candidate seam.
- Render (`POST /render`, `split_frames`): frame-range fan-out across nodes; `render`
  task type; `blender` template; agent `_run_render`.

## 17. Containerized render (correction)

- `_run_render` now launches Blender as a container (pull-on-demand, `--gpus all`,
  `--network none`); no host Blender install.
- `POST /jobs/input_url` (pre-signed GET for the scene); frames uploaded via the
  existing pre-signed PUT. `jobs/next` render payload includes the container image.

## 18. Seller payouts + scheduled withdrawals (added)

- `SellerPayoutMethod` / `Payout` / `PayoutSchedule`; `try_debit_earnings`,
  `request_payout`, `set_payout_status`, `compute_next_run`, `run_due_schedules`.
- Endpoints: `/wallet/methods` (+`/verify`), `/wallet/withdraw`, `/wallet/payouts`,
  `/wallet/schedule`. `payout_providers.py` (stub + gift_card/usdc/bank seams,
  `screen()` for KYC/AML). `tools/payout_worker.py` (timer service).

## 19. Email / notifications (added)

- `User.email/notify_email`; `Notification` table; `notify_providers.py` (stub +
  SendGrid/SES/Postmark seams); `notifications.py` (templated dispatch + opt-out).
- `POST /account/email`, `GET /notifications`; payout worker `on_status` -> emails
  on confirmed/failed; withdraw -> 'requested' email.

## 20. Video transcoding + fan-out assembly (added)

- `ffmpeg` template; `transcode`+`stitch` task types; `POST /transcode` (single or
  segment-parallel); `POST /uploads/url` (buyer input upload); `GET /jobs/manifest/{id}`.
- `MultiNodeJob`/`JobSegment` manifest + auto-stitch on completion, reused to give
  `/render` output assembly. Agent `_run_transcode`/`_run_stitch` (containerized FFmpeg).

## 21. Idle fallback (added)

- `SellerSpec.idle_fallback` + idle report fields; `set_idle_fallback`,
  `record_idle_report`. Endpoints: `POST /nodes/idle_fallback`, `POST /nodes/idle_report`,
  `GET /nodes/{id}/idle`; heartbeat returns the flag.
- Agent: NiceHash-in-a-container controller with hard paid-work preemption; wallet
  local to the node.

## 22. Unified idle mining + functional providers + security assessment

- `IdleSettlement`; `reconcile_idle_earnings` (worker `pb-<spec>`, idempotent,
  `idle_mining` ledger credit); `nicehash.py`; `tools/idle_reconcile.py`; agent mines
  as `pb-<spec_id>` to the platform account. Dropped per-seller-wallet path.
- Payout + email provider adapters rewritten as functional real-API code.
- `SECURITY_ASSESSMENT.md` added; static scan + auth-coverage + money-path review.

## 23. UX pass (dashboard redesign + CLI polish)

- `static_dashboard.py` redesigned (indigo/amber/cyan, Space Grotesk + JetBrains Mono,
  live count-up board, trust badges, streaming console, a11y). CLI gets color + tags.

## 24. Windows seller nodes (WSL2)

- `lumaris_agent/install.ps1` (PowerShell bootstrap: WSL2 + Ubuntu + systemd +
  standard install.sh + logon Scheduled Task); `install.sh` adds
  nvidia-container-toolkit when GPU present; `WINDOWS.md`.

## 25. Website / frontend + Google sign-in

- `pages.py`: landing `/`, `/marketplace`, `/install`, `/developers`, `/investors`,
  `/keys`; dashboard moved to `/app`. `GET /marketplace/specs` (public), `GET
  /install.sh`, Google OAuth (`/auth/google/login|callback`), `/account/keys` +
  `/keys/{jti}/revoke`, key `label`. Token persisted in localStorage. `frontend.md`,
  `template.env` (Google vars).
