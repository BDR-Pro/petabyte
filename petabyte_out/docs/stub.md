# stub.md — what's stubbed right now

Every place the code stands in for real external infrastructure, why, and exactly
what to swap for production. Nothing here is a bug — these are deliberate seams so
the logic is testable without GPUs/TEEs/clouds/banks. The 145 smoke assertions
exercise the logic **around** each stub; the stub replaces only the external call.

Toggle summary (env → stub active):
`S3_STUB`, `GEOIP_STUB`, `PAYOUT_STUB`, `NOTIFY_STUB`, `TEE_TRUSTED_ROOT` (stub
verifier), `PAYMENTS_MODE=sandbox`, `WG_APPLY=false`, `GEOIP_DB`/`GEOIP_STUB` unset.

---

## 1. Object storage (backups, render I/O)
- **Where:** `lumaris_api/utils.py` → `mint_presigned_put`, `mint_presigned_get`.
- **Stub:** when `S3_STUB=true`, returns a fake URL `https://<bucket>.s3.stub.local/<key>?op=...`.
- **Real:** unset `S3_STUB`, set `S3_BUCKET`/`S3_REGION`/`S3_ENDPOINT` + AWS creds;
  the code already calls `boto3.generate_presigned_url`. Bucket bootstrap is in
  `deploy/deploy.sh`.
- **Tested around it:** grant minting, tenant-prefix keys, non-owner denial,
  content-hash-on-restore, encryption plumbing.

## 2. IP geolocation (data residency)
- **Where:** `lumaris_api/utils.py` → `geolocate_country`.
- **Stub:** `GEOIP_STUB` (JSON `{ip: country}`) maps test IPs to countries.
- **Real:** set `GEOIP_DB=/path/GeoLite2-Country.mmdb` (MaxMind); the code reads it
  via `geoip2`. Or swap in an ipinfo/IPregistry API call.
- **Tested around it:** declared-vs-detected verification, spoofed-IP rejection, the
  residency booking gate.
- **Honest limit:** IP geolocation is VPN/proxy-defeatable; hard residency needs
  provider/TEE-attested datacenter location (see #3).

## 3. Confidential computing / TEE attestation
- **Where:** `lumaris_api/utils.py` → `verify_tee_report` / `_verify_stub`.
- **Stub:** verifies an Ed25519 signature against `TEE_TRUSTED_ROOT` + a measurement
  allowlist + the server-issued nonce. Structurally identical to real remote
  attestation, but the "vendor" is a test key, not real silicon.
- **Real:** replace `_verify_stub` with the vendor verifier:
  - NVIDIA H100 CC → verify the NRAS JWT against NVIDIA's JWKS (nvtrust SDK).
  - AMD SEV-SNP → verify the report's VCEK cert chain to AMD ARK/ASK.
  - Intel TDX → verify the quote via Intel DCAP.
  Populate `TEE_MEASUREMENT_ALLOWLIST` with approved enclave measurements.
- **Tested around it:** challenge/nonce replay protection, measurement allowlist,
  buyer-side independent verification, the `require_confidential` booking gate.

## 4. Payments in (buyer funding)
- **Where:** `lumaris_api/main.py` → `payment_webhook`.
- **Stub:** generic HMAC-SHA256 over the raw body (`PAYMENT_WEBHOOK_SECRET`);
  `PAYMENTS_MODE=sandbox` also lets `/deposit` mint test credits.
- **Real:** `PAYMENTS_MODE=live` + swap the signature check for
  `stripe.Webhook.construct_event` (exact diff in `deploy.md` §8b); read the buyer
  `username` from Checkout Session metadata.
- **Tested around it:** signature verify, idempotency on `event_id`, live-mode
  `/deposit` 403.

## 5. Payments out (seller payouts) + compliance
- **Where:** `lumaris_api/payout_providers.py`.
- **Stub:** `PAYOUT_STUB=true` → `StubProvider` confirms instantly; `screen()` passes.
- **NOW FUNCTIONAL:** `TremendousProvider`/`CircleUSDCProvider`/`StripeBankProvider`
  `.send` are real API calls — set the provider creds to use them. Still wire
  `screen()` to real sanctions/AML (Chainalysis/TRM) + `/verify` to KYC (Persona/Sumsub).
- **Tested around it:** atomic earnings debit, requested→confirmed|failed state
  machine, refund-on-failure, over-withdraw 402, the weekly schedule
  (`compute_next_run` / `run_due_schedules`).
- **Honest note:** the real cost here is compliance + legal, not the adapter.

## 6. Agent workload execution (Docker / GPU)
- **Where:** `lumaris_agent/task_fetcher.py` → `_run_notebook`, `_run_template`,
  `_run_render`, `_run_benchmark`; `lumaris_agent/notebook.py` (sandbox).
- **Stub:** none — these are **not run in the smoke suite** (no Docker/GPU in CI).
  They are syntax- and import-checked only. The safety design (no host fallback,
  `--network none`, cap-drop, read-only, limits) is coded but needs a Docker daemon
  to exercise.
- **Real:** run the agent on a Docker+GPU node (see `RLtest.md` §9, §16, §17).

## 7. Benchmark harness
- **Where:** `lumaris_agent/task_fetcher.py` → `_run_benchmark`.
- **Stub:** reads `BENCH_TOKENS_SEC` env as a placeholder number.
- **Real:** run a fixed prompt through a local model and count generated
  tokens / wall-time; report the measured value.
- **Tested around it:** dispatch, signed `/jobs/benchmark_result`, `/specs` surfacing.

## 8. Render scene/frame transfer
- **Where:** `lumaris_agent/task_fetcher.py` → `_run_render`.
- **Stub:** the container launch + pre-signed scene fetch/frame upload aren't run
  (no Docker/S3 in CI). API side (`/jobs/input_url`, image handoff) IS tested.
- **Real:** needs a Docker+GPU node + S3 (RLtest §16). Output-manifest/stitching is
  now BUILT (shared with transcode); per-frame billing still not built.

## 8b. Video transcode / stitch execution
- **Where:** `lumaris_agent/task_fetcher.py` → `_run_transcode`, `_run_stitch`.
- **Stub:** container FFmpeg (NVENC) + concat not run in CI (no Docker/GPU). API side
  (fan-out split, manifest, auto-stitch, `/uploads/url`, `/transcode`) IS tested.
- **Real:** Docker+GPU node with an NVENC FFmpeg image + S3 (RLtest §20). Keyframe-
  aligned splitting happens in the agent via ffmpeg `-ss/-to`.

## 9. MicroVM / Firecracker / QEMU
- **Where:** `lumaris_agent/vm.py`.
- **Stub:** corrected-by-review (qcow2+overlay, Firecracker over UDS) but not
  runnable without KVM + a GPU; bzImage/IOMMU caveats documented.
- **Real:** a bare-metal host with KVM + VFIO passthrough.

## 10. WireGuard peer application
- **Where:** `lumaris_api` VPN config + agent.
- **Stub/off:** `WG_APPLY=false` by design — config generation is real and leak-free,
  but the server-side peer is never applied. The notebook/template/render paths need
  no VPN.
- **Real:** a privileged peer-reconciler service + NAT + UDP 51820, only when
  interactive VM rental (SSH into a live box) becomes a customer ask.

## 11. Node hardware detection
- **Where:** `lumaris_agent/provision.py` → `detect()`.
- **Stub:** in tests, GPU is supplied via `GPU_MODEL`/`GPU_COUNT`/`VRAM_GB` env.
- **Real:** `nvidia-smi` on the node (already coded); env override remains for manual
  cases. Provisioning logic IS tested end-to-end against a live server.

## 12. Email / notifications
- **Where:** `lumaris_api/notify_providers.py` → `StubEmailProvider`, `get_email_provider`.
- **Stub:** `NOTIFY_STUB=true` → records the notification without sending.
- **NOW FUNCTIONAL:** the SendGrid/SES/Postmark `.send` methods are real API calls;
  set `EMAIL_PROVIDER` + creds to use them (SPF/DKIM for deliverability).
- **Tested around it:** template rendering, audit log, opt-out (`skipped`), the
  payout `requested`/`confirmed`/`failed` wiring.

## 13. Idle-fallback mining (NiceHash) — unified balance
- **Attribution is real, not stubbed:** each node mines as worker `pb-<spec_id>` to
  Petabyte's account; `reconcile_idle_earnings` credits the seller's unified balance
  idempotently. `nicehash.py` earnings pull is functional (HMAC-signed) behind
  `NICEHASH_STUB`.
- **Where:** `lumaris_agent/task_fetcher.py` → `start_idle_miner`/`stop_idle_miner`.
- **Stub:** the miner container isn't run in CI (no Docker/GPU). The opt-in flag,
  heartbeat signal, report endpoint, and ownership checks ARE tested.
- **Real:** on the node set `IDLE_MINING=true` + `NICEHASH_ADDRESS` (+ `NICEHASH_RIG`/
  `NICEHASH_IMAGE`); the agent runs the miner only when unrented and kills it the
  instant a paid job is claimed. Wallet stays on the node.

## 14. Windows nodes (WSL2 bootstrap)
- **Where:** `lumaris_agent/install.ps1` + `WINDOWS.md`.
- **Stub:** cannot be executed here (no Windows) — PowerShell is unlinted; treat as
  a carefully-written seam. The Linux agent it bootstraps IS the tested one.
- **Real:** run on a Windows 11 + NVIDIA machine (RLtest §22): install, reboot case,
  GPU visible in WSL (`nvidia-smi`), job with `--gpus all`, logon auto-start,
  sleep→reaper-refund→wake-resume.

## 15. Google sign-in (OAuth)
- **Where:** `lumaris_api/main.py` → `/auth/google/login`, `/auth/google/callback`.
- **Stub:** `GOOGLE_OAUTH_STUB=true` short-circuits to a demo email (flow tested).
- **Real:** functional code — set `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` from a Google
  Cloud OAuth client; it does the real token + userinfo exchange. See `frontend.md`.

---

## What is NOT stubbed (real, in-process, tested)
Escrow/wallet/ledger, booking + capacity, idempotency, JWT + API keys + scopes,
Ed25519 attestation & signed proof-of-work verification, reputation event math,
router placement, frame-splitting, org accounts/budgets, reschedule-on-death + grace,
payout state machine + scheduling — all execute the real production code paths
against a real DB in the smoke suite.
