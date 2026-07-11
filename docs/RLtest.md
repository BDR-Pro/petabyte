# RLtest.md — Real-life test plan

The automated suite (`lumaris_api/smoke_test.py`, 231 assertions) drives the real
FastAPI app + DB in-process and proves the **logic**: money movement, state
machines, auth, ownership boundaries, signature verification, reschedule/grace,
routing, frame-splitting. It uses **stubs** where hardware isn't available:
`S3_STUB` (object storage), `GEOIP_STUB` (geolocation), the TEE `_verify_stub`
(no NVIDIA/AMD), and it never runs Docker/GPU/Blender/Stripe.

This document is the other half: the tests you must run on **real hardware and
real services** to validate the stubbed edges. For each feature: what the smoke
test already covers, the real-life setup, the exact steps, and the pass criteria.

Legend: ✅ = covered by smoke test · 🔌 = needs real infra (this doc).

---

## 0. Test environment

Minimum honest rig (see also `deploy.md`):

- **API host** — Ubuntu 24.04 droplet (1 vCPU/2GB), Postgres, nginx, HTTPS. No GPU.
- **Seller node A** — a machine with 1 GPU + Docker + NVIDIA Container Toolkit.
- **Seller node B, C** — cheap CPU boxes (or spare laptops) for inventory depth,
  residency, and multi-node/redundancy tests.
- **Buyer** — your laptop (CLI + browser dashboard).
- **Object storage** — an S3 bucket or Cloudflare R2 (for backup/render tests).
- Optional: an NVIDIA **H100 in CC mode** or an AMD **SEV-SNP** host (confidential),
  a **MaxMind GeoLite2** DB (residency), a **Stripe** test account (payments).

Env to set before go-live tests: `PAYMENTS_MODE`, `S3_BUCKET` + creds, `GEOIP_DB`,
`TEE_TRUSTED_ROOT`/`TEE_MEASUREMENT_ALLOWLIST`, `AWS_REFERENCE_PRICE`.

---

## 1. Deployment & health 🔌
**Covered ✅:** `/healthz`, `/readyz` logic.
**Real test:** run `bash deploy/deploy.sh` on the droplet; switch `DATABASE_URL` to
Postgres; run `alembic upgrade head`; `certbot --nginx`.
**Steps:**
1. `curl https://api.<domain>/healthz` → `{"status":"ok"}`.
2. `curl https://api.<domain>/readyz` → `{"status":"ready"}` (proves DB reachable).
3. `systemctl status lumaris-api lumaris-reaper` → both `active (running)`.
4. Kill Postgres briefly → `/readyz` returns 503; restore → 200.
**Pass:** health green over HTTPS; reaper running as its own service; no stack
traces in `journalctl -u lumaris-api`.

---

## 2. Node onboarding (installer) 🔌
**Covered ✅:** provisioning path (register→attest→mint key→write env) against a live
server with hardware-detection stubbed.
**Real test:** run the one-liner on a real GPU box.
**Steps:**
1. On node A: `PETABYTE_API_URL=https://api.<domain> PETABYTE_USER=alice
   PETABYTE_PASS=… PRICE_PER_HOUR=1.5 bash <(curl -fsSL https://<host>/install.sh)`.
2. Confirm it installs Docker, detects the GPU via `nvidia-smi`, and writes
   `/etc/petabyte/agent.env` (chmod 600) with API_URL/API_KEY/SPEC_ID/AGENT_KEY.
3. `systemctl status petabyte-agent` → running; `journalctl -u petabyte-agent -f`
   shows heartbeats.
**Pass:** within ~1 min the node appears in `GET /specs` as attested + online with the
**detected** GPU model/VRAM (not typed by hand), and is bookable.

---

## 3. Marketplace booking + escrow (money) 🔌
**Covered ✅:** escrow debit, release split, refund, ledger — all in-process.
**Real test:** end-to-end over the network with the CLI.
**Steps (buyer laptop):**
1. `PETABYTE_API_URL=https://api.<domain> python cli/petabyte.py register/login`.
2. `deposit 50` (sandbox) → `wallet` shows 50.
3. `specs` lists node A; `run hello.ipynb --gpu <model> --hours 1`.
4. Watch node A's `journalctl` claim + run the job; CLI prints `COMPLETED`.
5. `wallet` shows balance reduced by the hourly price; the seller's `earnings`
   increased by price×(1−take_rate); platform revenue by the rest.
**Pass:** exactly one debit, one seller payout, one platform fee per job; numbers
reconcile; `GET /bookings/{id}` shows `released`.

---

## 4. Trust: attestation & signed proof-of-work 🔌
**Covered ✅:** Ed25519 verify, forged/expired rejection, known-answer pass/fail.
**Real test:** confirm a real node's result verifies and a tampered one is caught.
**Steps:**
1. Run a job on node A (real agent signs with the key minted at install).
2. Inspect `POST /jobs/result` in logs — signature verifies, booking releases.
3. **Negative:** on a scratch node, tamper the agent to sign results with a
   different key; submit → expect 401, reputation/fraud penalty recorded.
4. Dispatch a known-answer test (`POST /dispatch_test`); a node that skips/fakes
   compute fails the hash check.
**Pass:** honest node's work verifies and pays; tampered signature is rejected and
increments `fraud_count` (see §15).

---

## 5. Confidential computing (TEE) 🔌 — needs H100 CC / SEV-SNP
**Covered ✅:** challenge/nonce replay, measurement allowlist, buyer-side verify,
booking gate — with a STUB verifier.
**Real test:** replace the stub with the real vendor verifier and attest real hardware.
**Setup:** on an H100-CC node install NVIDIA nvtrust; set the API's `verify_tee_report`
to call NVIDIA NRAS (verify the JWT against NVIDIA JWKS) instead of `_verify_stub`;
populate `TEE_MEASUREMENT_ALLOWLIST` with your approved measurements.
**Steps:**
1. `POST /attestation/challenge` → nonce; agent produces a real NRAS report bound to it.
2. `POST /prove_tee` with the real report → spec marked `confidential`.
3. As a buyer, `GET /specs/{id}/attestation` and **verify the report yourself**
   against NVIDIA's roots before sending data.
4. Book with `require_confidential:true` → lands only on the CC node.
5. **Negative:** point a non-CC node at `/prove_tee` → rejected.
**Pass:** only genuine CC hardware attests; buyer-side verification succeeds against the
real vendor root; sensitive job never lands on non-CC hardware.

---

## 6. Data residency (GeoIP) 🔌 — needs MaxMind + real IPs
**Covered ✅:** declared-vs-detected logic, spoof rejection — with `GEOIP_STUB`.
**Real test:** set `GEOIP_DB=/path/GeoLite2-Country.mmdb` (unset `GEOIP_STUB`).
**Steps:**
1. Bring up node B on a real EU IP; declare `country=DE, region=eu-west`; heartbeat.
   → `region_verified=true`, `detected_country=DE`.
2. Bring up a node on a non-EU IP but declare DE → `region_verified=false`.
3. Book with `require_region:eu-west` → only the truly-EU node accepts (spoofed one
   gets 403).
4. **VPN caveat:** run node B behind a DE VPN while physically elsewhere — note it
   passes (documented limit; hard residency needs provider/TEE attestation).
**Pass:** IP-verified region gates correctly; the honest assurance level matches the
Trust Center wording.

---

## 7. Organizations, budgets, analytics 🔌
**Covered ✅:** roles, shared-wallet debit, budget cap, refund-to-org, usage/analytics.
**Real test:** multi-user over the network.
**Steps:** create an org; add a second real user as `member`; fund with `budget_cap`;
have the member book on the org wallet from their own laptop; exceed the cap → 402;
kill the node mid-job → refund returns to the **org** wallet; pull `GET
/orgs/{id}/usage` and `/analytics`.
**Pass:** roles enforced across real accounts; budget cap holds; refunds land in the
org; analytics reconcile with actual bookings.

---

## 8. Payments (Stripe) 🔌 — needs Stripe test account
**Covered ✅:** HMAC webhook, idempotency, live-mode `/deposit` 403.
**Real test:** wire Stripe (swap the code shown in `deploy.md` §8b).
**Steps:** set `PAYMENTS_MODE=live` + `PAYMENT_WEBHOOK_SECRET`; create a test Checkout
Session with the buyer `username` in metadata; complete payment with a Stripe test
card; Stripe fires `checkout.session.completed` → balance credited exactly once;
replay the event via Stripe CLI → no double credit; `/deposit` returns 403.
**Pass:** real card → real balance; idempotent on retries; no free credits in live mode.

---

## 9. Templates: Ollama / vLLM / game servers 🔌 — needs Docker+GPU
**Covered ✅:** catalog, task dispatch, image/port/params handoff.
**Real test:** actually launch the containers on node A.
**Steps:**
1. Book node A; `create_task template=vllm params={model: <HF id>}`.
2. Node pulls `vllm/vllm-openai`, runs with `--gpus all`, mounts the HF cache volume.
3. `GET /tasks/{id}` shows the reported endpoint; hit the OpenAI-compatible API and
   get a completion.
4. Repeat for `ollama` and `minecraft` (connect a Minecraft client to the node:port).
**Pass:** container comes up, GPU visible inside it (`nvidia-smi` in-container), model
cached on 2nd run, buyer reaches the live endpoint.

---

## 10. Benchmark (tokens/sec) 🔌 — needs GPU + a real harness
**Covered ✅:** dispatch + signed result recording + `/specs` surfacing.
**Real test:** wire a real harness in the agent's `_run_benchmark` (run a fixed prompt
through a local model, count generated tokens / wall-time).
**Steps:** `POST /benchmark`; node runs the harness; `POST /jobs/benchmark_result` with
the real number; `GET /specs` shows a plausible `benchmark_tokens_sec` (e.g. an H100
in the thousands); the dashboard's $/token-vs-AWS column updates.
**Pass:** the number is real and stable across runs (±10%), signed, and per-node.

---

## 11. Job management: priority / retry / progress / live logs 🔌
**Covered ✅:** priority ordering, retry, progress, WebSocket streaming (in-process).
**Real test:** over the network with a real long job.
**Steps:** submit a low- and high-priority job; confirm high runs first; kill a job so
it fails, `POST /tasks/{id}/retry`, confirm re-run; run a multi-minute job and watch
`GET /tasks/{id}` progress climb; open `wss://api/ws/tasks/{id}/logs?token=…` and see
lines stream live as the agent emits them.
**Pass:** priority respected on a real queue; retry re-runs; progress + logs stream to a
remote client in real time.

---

## 12. Backup / restore + reschedule-on-death 🔌 — needs S3 + kill a node
**Covered ✅:** checkpoint record, restore pointer, reschedule vs refund, grace fallback.
**Real test — the marquee demo:**
1. Configure S3 (§14). Book node A; run a **stateful** job (e.g. Minecraft) with
   `backup_enabled, backup_interval_s=120, volume=world`.
2. Change the world (place blocks); wait for ≥1 backup (see a `Checkpoint` appear via
   `GET /tasks/{id}/checkpoints`).
3. **Pull the power / `docker kill` / unplug node A.** Reaper detects death.
4. Confirm the task is **rescheduled** (not failed) and the booking stays **active**
   (no refund) — `GET /tasks/{id}` pending, booking active.
5. Bring node A back (or a same-owner node) → agent claims the task, restores the
   world from the last checkpoint (blocks you placed are back).
6. **Grace:** keep the node dead past `BACKUP_RESCHEDULE_GRACE_S` → booking refunds.
**Pass:** ≤interval data loss on recovery; no refund while recoverable; refund if never
recovers. Record this on camera — it's the reliability story.

---

## 13. Secure backup uploads (pre-signed URLs) 🔌 — needs real S3
**Covered ✅:** grant minting, tenant-prefix, non-owner denial, hash-on-restore — stubbed.
**Real test:** with live S3.
**Steps:**
1. `deploy.sh` bucket bootstrap creates + hardens the bucket (verify: private,
   versioned, TLS-only, SSE, lifecycle via `aws s3api get-bucket-*`).
2. Agent requests `POST /jobs/backup_url` → uploads an **encrypted** object to the
   pre-signed PUT. Confirm the node has **no** standing AWS creds (`env | grep AWS`
   on the node should be empty).
3. In the bucket, confirm the object is under `backups/{buyer}/{task}/…` and is
   ciphertext (not a readable tar).
4. **Negative:** try the pre-signed URL after 15 min → expired/denied; try to PUT a
   different key with the same URL → denied.
5. Restore: corrupt the object in S3 → agent's hash check fails and refuses to restore.
**Pass:** node holds no keys; objects tenant-isolated + encrypted; tampering caught.

---

## 14. Reputation (accumulation) 🔌
**Covered ✅:** event recording, derived score, fraud on forged sig.
**Real test:** let it accumulate over real jobs and days.
**Steps:** run dozens of jobs across nodes A/B/C over a week; kill some mid-job; run
benchmarks; then read `GET /specs/{id}/reputation`.
**Pass:** score tracks reality — high-uptime, high-completion nodes score above flaky
ones; `avg_latency_s`, `completion_rate`, `heartbeats`, `benchmark_tokens_sec` are all
populated from real events; a node you deliberately made flaky ranks lower and the
router (§15) picks it less.

---

## 15. AI Router (/solve) 🔌
**Covered ✅:** hard-filter + score + distinct-provider redundancy + 409.
**Real test:** with a real, varied fleet (nodes A/B/C differing in price, GPU, region,
reputation).
**Steps:** `POST /solve {workload, gpu_class, region, confidential, redundancy:2,
max_price_per_hour}`; verify the plan picks the best real nodes across **distinct
owners**, honors region/confidential/price, and that a plan you then book actually runs.
**Pass:** placement matches what a human expert would pick given the live fleet;
redundancy spans providers; impossible asks 409.

---

## 16. Render farm 🔌 — needs Docker+GPU on ≥2 nodes + S3
**Covered ✅:** frame-splitting, router selection, per-node task + image handoff,
scene-fetch grant.
**Real test:** render a real .blend across nodes.
**Steps:**
1. Upload a `.blend` to the bucket; note its ref.
2. `POST /render {blend_ref, frame_start:1, frame_end:100, nodes:2, gpu_class:…}`.
3. Each node pulls the **Blender container** (not a host install — verify no Blender
   on the host), fetches the scene via `POST /jobs/input_url`, renders its subrange
   with `--gpus all`, uploads frames via the pre-signed PUT.
4. Collect frames from both nodes → a complete 1–100 sequence.
5. Kill one node mid-render → only its frames re-render (retry), others untouched.
**Pass:** two nodes render disjoint halves in parallel with **only Docker installed**;
frames reassemble into the full sequence; a node failure costs only its chunk.
**Known gaps to build first:** output-manifest/stitching endpoint (report "all frames
done" as one deliverable) and per-frame (vs per-hour) billing.

---

## 17. Agent sandbox security 🔌 — adversarial
**Covered ✅:** the agent refuses to run without Docker (no host fallback).
**Real test:** attack the sandbox.
**Steps:** submit a job whose code tries to (a) reach the network (`--network none`
should block), (b) read the host filesystem (read-only rootfs, mounts), (c) escalate
(cap-drop ALL, no-new-privileges), (d) exhaust memory/CPU (limits), (e) fork-bomb
(pids-limit). Also submit a job that tries to read another tenant's backup prefix in S3.
**Pass:** every attempt is contained; no host compromise, no cross-tenant access; the
node stays healthy.

---


## 18. Seller payouts + scheduled withdrawals 🔌 — needs payout provider + KYC/AML
**Covered ✅:** earnings accrual, method verify gate, atomic withdraw, provider confirm,
over-withdraw 402, schedule compute (Monday 08:00), due-firing, next-week advance —
all with `PAYOUT_STUB` and a stubbed `screen()`.
**Real test:** wire a real payout provider + compliance, then pay a real seller.
**Setup:** create a Tremendous (or Tango) sandbox account; implement
`TremendousProvider.send` (and/or `CircleUSDCProvider`/`StripeBankProvider`); wire
`screen()` to a real sanctions check (Chainalysis/TRM) and method `/verify` to real
KYC (Persona/Sumsub). Set the payout worker on a systemd timer (every 5 min).
**Steps:**
1. Seller earns real balance from completed jobs (§3).
2. `POST /wallet/methods {kind:"gift_card", destination:<your email>}` → `/verify`
   (real KYC runs).
3. `POST /wallet/withdraw {amount}` → the worker calls the provider → you receive a
   **real** gift-card email (sandbox). `GET /wallet/payouts` shows `confirmed` + the
   provider's txn ref.
4. `POST /wallet/schedule {day_of_week, hour, utc_offset_minutes}` for ~2 min ahead;
   leave the worker running → at the scheduled time it auto-withdraws and advances a
   week.
5. **Negative:** point `destination` at a sanctioned/blocked address → `screen()`
   rejects, payout marked `failed`, earnings refunded.
6. **Idempotency:** kill the worker mid-send and restart → the payout is not sent
   twice.
**Pass:** a real seller receives real value on the chosen rail; scheduled withdraw
fires at the right local time; screening blocks bad destinations; no double-pay; USD
ledger reconciles with what was sent.
**Compliance gate (do BEFORE launch, not code):** KYC on sellers, OFAC/sanctions
screening, 1099/tax reporting, money-transmission legal review. Gift cards are
payout-side ONLY — never accept them as buyer funding.

## 19. Email / notifications 🔌 — needs an email provider
**Covered ✅:** template rendering, audit log, opt-out, payout event wiring.
**Real test:** set `EMAIL_PROVIDER` + creds (SES/SendGrid/Postmark); implement `.send`.
**Steps:** `POST /account/email` with a real inbox; do a withdraw → receive the
'processing' email; let the worker confirm → receive the 'complete' email with the
provider reference; set `notify_email:false` → confirm no email but the action still
works; `GET /notifications` shows the audit trail with `sent` status.
**Pass:** real emails arrive for payout lifecycle; opt-out suppresses delivery;
deliverability configured (SPF/DKIM on your domain).

## 20. Video transcoding + assembly 🔌 — needs Docker+GPU (NVENC) + S3
**Covered ✅:** buyer upload grant, fan-out split, containerized task handoff, manifest
assembly (segments→stitch→complete), single-node path, render via the shared manifest.
**Real test:** transcode a real file across nodes with NVENC.
**Steps:**
1. `POST /uploads/url` → PUT a real .mp4 to the pre-signed URL.
2. `POST /transcode {input_ref, codec:h265, nodes:2, duration_seconds:<len>,
   gpu_class:…}`. Each node pulls the **FFmpeg NVENC container** (verify no host
   ffmpeg), fetches its segment via `/jobs/input_url`, transcodes with `--gpus all`,
   uploads via the pre-signed PUT.
3. When all segments finish, the stitch task concats them → `GET /jobs/manifest/{id}`
   shows `complete` + `output_ref`. Download and play it — full length, no A/V desync.
4. Verify keyframe-aligned cuts (no corrupt segment boundaries after concat).
5. Kill a node mid-segment → only that segment re-transcodes.
**Pass:** parallel NVENC transcode with only Docker installed; segments concat into one
clean file; a node failure costs only its segment.
**Known gap:** per-segment (vs per-hour) billing.

## 21. Idle fallback (NiceHash) 🔌 — needs Docker+GPU + a NiceHash account
**Covered ✅:** opt-in flag, heartbeat signal, report endpoint, ownership, opt-out.
**Real test — the critical property is PREEMPTION:**
1. On a GPU node set `IDLE_MINING=true` + `NICEHASH_ADDRESS`; `POST /nodes/idle_fallback
   {enabled:true}`.
2. Leave it unrented → miner container starts; NiceHash dashboard shows the rig; a
   trickle accrues to the SELLER's wallet (not Petabyte).
3. **Book a paid job on that node.** The miner must be killed within seconds and the
   paid job gets the full GPU (check `nvidia-smi` — only the job's process). When the
   job ends and the node is idle again, mining resumes.
4. `POST /nodes/idle_fallback {enabled:false}` → mining stops and stays off.
**Pass:** mining NEVER runs concurrently with paid work; earnings land in the seller's
own wallet; opt-out is respected. **If preemption ever fails, disable the feature** —
paid jobs must never be degraded by mining.
**Reality check:** confirm the trickle actually exceeds the node's power cost before
promoting this; for many GPUs it won't (it's a floor, seller's choice).

## 22. Windows seller node (WSL2) 🔌 — needs a Windows 11 + NVIDIA machine
**Covered ✅:** nothing executable here — installer + docs only; the agent inside is
the standard tested Linux agent.
**Steps:** elevated PowerShell one-liner → (reboot if WSL fresh) rerun → verify
`wsl -d Ubuntu-24.04 -u root -- systemctl status petabyte-agent`; `nvidia-smi` inside
WSL shows the GPU; book a job → runs with `--gpus all`; log off/on → auto-start task
brings the node back; sleep the machine mid-job → reaper refunds; wake → heartbeats
resume.
**Pass:** a Windows gaming PC lists, rents, and settles exactly like a Linux node.

## Priority order for a funding demo

1. §2 onboarding + §3 booking/escrow (the loop works, on real hardware).
2. §9 one-click vLLM (a live endpoint in 30s) + §10 a real tokens/sec number.
3. §12 backup → kill node → recover (the reliability moment, on camera).
4. §16 render across 2 nodes (parallelism + the container model).
5. §15 /solve (the "solve compute, don't rent GPUs" story) + §14 reputation.

Everything above rests on logic already proven by the 231 smoke assertions; these
real-life tests validate the hardware-facing edges the smoke suite deliberately stubs.

---

## 23. One-click launch (`/launch`) end-to-end 🔌 — needs a real node
**Covered ✅:** `/launch` auto-picks the cheapest eligible node, books (escrow via
`request_vm`), starts a template task, returns `booking_id/task_id/port`; rejects
unknown template (400), no auth (401), no funds (402), no node (409). All in the
smoke suite.
**Not covered — needs a real node:** that the container actually starts on the node
and that the launch panel's poll of `/tasks/{id}` eventually shows a **real
`connection_string`** the buyer can use.
**Steps:** with seller node A online, sign in as a funded buyer, click **Launch**
on a template card (`/account`, `/gamers`, `/artists`). Confirm the node runs the
image and reports `vm_details`; the panel flips from "Preparing your VM…" to a real
address.
**Pass:** one click → reserved → connectable, no curl.

## 24. Reachable VM / SSH gateway / NAT traversal 🔌🔌 — NOT BUILT (needs 2-3 real VMs)
**Status:** **unbuilt** (see `docs/vm-rental.md`, `docs/isolation-roadmap.md`).
The agent can *report* `ip/port/connection_string`, but there is no gateway that
proxies a **stable `petabyte.market` address** to a live node, and no reverse
tunnel for nodes behind NAT. This is the single most important thing to build and
it **cannot be tested in the sandbox** — it needs real machines behind real routers.
**Real test (the proof):** node behind (simulated) NAT dials out via frp/WireGuard
to a public gateway; buyer runs `ssh vm-<id>@petabyte.market` (or opens
`https://<id>.petabyte.market`) and lands in the container. No raw seller IP is ever
exposed.
**Pass:** buyer connects through a stable Petabyte URL to a NAT'd node.

## 25. Failover: same URL, new node 🔌🔌 — NOT BUILT (needs 2 nodes + S3)
**Status:** **designed, unbuilt.** The `Buyer1/VM1 → new IP, same URL` model needs:
durable routing table (`vm_id → current_node`), periodic checkpoint → S3, and an
orchestrator that on node death picks a new seller, restores the snapshot, restarts
the container, and **re-points the routing row** — connect string unchanged.
**Real test:** launch a VM on node A, write a file, kill node A. Within the recovery
window the same address resolves to node B with the last snapshot's state.
**Pass:** address constant across failover; data restored to the last checkpoint
(crash-consistent, not zero-loss — set that expectation with users).

## 26. Isolation runtime (gVisor now, Firecracker later) 🔌🔌 — needs real nodes + adversarial testing
**Status:** hardening from `docs/isolation-roadmap.md` is **not yet in the agent**.
Today jobs run under stock Docker on the node.
**Phase 1 real test (gVisor):** run the agent with `--runtime=runsc` + the hardening
flags; run adversarial buyer payloads (container-escape attempts, host FS probes,
resource bombs) and confirm containment; confirm GPU still works under gVisor.
**Phase 2 real test (Kata/Firecracker):** a tenant gets a **separate kernel**; verify
GPU passthrough into the microVM on a known GPU/driver combo before promising it.
**Pass:** buyer code cannot touch the host or other tenants; seller cannot read the
workload; GPU performance is acceptable.

## 27. Adversarial money-path concurrency ✅ — covered in software (lumaris_api/adversarial_test.py)
**Covered ✅:** a dedicated stress test (`python adversarial_test.py`, 11 assertions,
run repeatedly for race stability) hammers the money paths concurrently and proves:
- 6 buyers racing `/launch` for 3 units → no oversell, every success holds exactly one unit;
- 8 racing stops of the same VM → booking settles exactly once;
- stop-vs-extend races → extend's debit is atomic and refunded if it loses to a settle;
- failover-vs-stop-vs-refund races → booking terminal at most once, no orphaned capacity;
- **conservation invariant:** deposits == wallets + escrow + seller earnings + platform
  revenue, to the cent, after every storm. No negative balances anywhere.

**Bugs this test caught and fixed (kept here for honesty):** booking not following the
VM on failover (paid the wrong seller / leaked the new node's unit); extend debiting
into an already-settled booking (money vanished); ORM read-modify-write wallet updates
erasing concurrent atomic debits; double-migration of one VM by racing reapers
(double-reserve); unguarded booking re-point after settle (orphaned unit). All settle,
extend, stop, and migrate transitions are now guarded/atomic (CAS or conditional
UPDATE) — the same discipline Postgres will enforce in production.

**Still needs real machines:** the same storms under true multi-process Postgres load
(sqlite serializes writers, so some interleavings are milder here). Re-run
`adversarial_test.py` against the managed Postgres before going live with real money.
