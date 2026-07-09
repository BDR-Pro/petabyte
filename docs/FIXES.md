# Petabyte — fixes applied

Two halves were reconciled into one secure, tested system: the **API**
(`lumaris_api`) and the seller **agent** (`lumaris_agent`). The API is fully
covered by an automated smoke test (27 assertions, all passing). The agent's
host-side logic is import- and behavior-checked; its KVM/GPU/Firecracker paths
require real hardware to execute (noted below).

## API (lumaris_api) — security + correctness

- **WireGuard server private key leak (critical):** `gen_config_record` returned
  the server's private key to every client. Replaced with per-request client
  keypair generation; the server stores only the client's public key and returns
  the client's own config. Server key never leaves the host.
- **Passwords:** `sha256_crypt` → **bcrypt**.
- **Self-serve role toggle / CSRF:** `change_role` GET toggle → authenticated
  **POST** with explicit role.
- **save_specs bug:** persisted the username into an Integer column (broke on
  Postgres). Now resolves `user.id` first.
- **Session leaks:** every `SessionLocal()`/`get_db().__next__()` that never
  closed is replaced with dependency-injected sessions.
- **JWT expiry** is now UTC-aware; missing `SECRET_KEY` fails fast.
- **API keys** carry a `jti` with a revocation denylist + `/revoke_api_key`.
- **CORS:** `allow_origins=["*"]` with credentials (insecure/invalid) → explicit
  env-driven allow-list.

## API — reliability

- **No double-sell:** atomic conditional UPDATE on `available_units`.
- **Idempotent bookings** via `Idempotency-Key`.
- **Node liveness:** heartbeat + background reaper; offline specs aren't bookable.
- **Race-safe WireGuard IP allocation;** `pool_pre_ping` + statement timeout for Postgres.
- **Hardware attestation:** `/prove` now verifies a real **Ed25519** signature
  (was a `print()` stub).
- Health endpoints `/healthz`, `/readyz`; global exception handler.

## API — task/job protocol (secured)

The bolted-on task protocol let **any agent run any task** (auth was a shared
key; tasks weren't tied to payment). Rebuilt around ownership:

- `Task` is tied to a **Booking** (i.e. paid) and a **spec**.
- `POST /create_task` — buyer queues work against a booking they own.
- `GET /jobs/next` — agent atomically claims the next job **only for specs it owns**
  (ownership = the authz boundary). Verified: a foreign agent gets 204.
- `POST /jobs/result` / `POST /jobs/vm_details` — only the owning agent may submit.

## Agent (lumaris_agent)

- **Remote code execution (critical):** `notebook.py` ran untrusted buyer code
  **directly on the host** (`NotebookClient().execute()`). Replaced with a
  locked-down Docker sandbox: `--network none`, `--cap-drop ALL`,
  `--security-opt no-new-privileges`, `--read-only` + tmpfs, hard CPU/RAM/PID
  limits, output-size cap. **No host-execution fallback** — if Docker is absent
  it refuses to run (verified).
- **Protocol match:** talks to the secured API (`/jobs/next`, `/jobs/result`,
  `/jobs/vm_details`) with the real encrypted `X-API-KEY`. Removed the hardcoded
  `"supersecretkey"` and hardcoded prod URL; all config via env.
- **Decoupled heartbeat:** runs on its own thread so a long job no longer makes
  the node look offline (and get reaped mid-job).
- **VM fixes (`vm.py`):** QEMU `format=raw` → **qcow2 + per-tenant overlay**
  (was a silent boot failure and a cross-tenant data-bleed); Firecracker control
  switched from unsupported `requests` `http+unix://` to **httpx UDS**; Docker
  "VM" hardened (pids-limit, no-new-privileges, cap-drop); VFIO/IOMMU-group and
  bzImage-vs-vmlinux caveats documented.
- `ui.py` no longer hardcodes a secret.

## Hygiene

- Leaked `.env` and `dev.db` excluded; `.gitignore` + `template.env` / `.env.example` added.
- See **SECURITY.md** — the committed secrets are compromised and must be rotated.

## What could NOT be executed in this environment (needs real hardware)

- QEMU/Firecracker boot and GPU (VFIO) passthrough — require KVM + a GPU.
- The Docker notebook sandbox — requires a Docker daemon (logic + the
  no-host-fallback safety check are verified; container flags need a daemon to run).
- The Windows `.exe` packaging (`build_exe.py`).
These paths are corrected by code review and clearly guarded/annotated, but you
must test them on a real seller node before production.

---

## Trust layer (added) — signed proof-of-work, known-answer tests, reputation

Builds on the existing Ed25519 attestation. Verified end-to-end in `smoke_test.py`.

- **Signed proof-of-work on every result.** `/prove` now stores the node's
  Ed25519 pubkey. `/jobs/result` requires a signed `proof` (`output_hash` + `ts`)
  and verifies it against that pubkey — binding each result to the attested
  hardware. A forged/expired signature is rejected (401) and penalizes reputation.
  The agent signs every result with the same key it attested with (`crypto.py`).
- **Known-answer test workloads.** `POST /dispatch_test` queues a deterministic
  job; the agent computes it and returns a signed hash; the API compares it to
  the server-computed expected hash. Uses **integer arithmetic** (reproducible on
  any GPU/driver) — float results are not bit-identical across hardware, so exact
  output-hash tests on Blender/AI jobs would false-fail honest sellers.
- **Reputation gating.** Pass/fail updates a per-seller `reputation`. Below
  `MIN_REPUTATION` the seller's specs become unbookable for paid work
  (`can_accept_paid_jobs=False`). Verified: repeated failed tests drop reputation
  and a low-rep seller's spec returns 403 on `request_vm`.
- **Buyer result retrieval:** `GET /tasks/{id}` (owner-scoped).

Design note: kept **Ed25519** (already plumbed, faster) rather than the RSA-4096
from the reference; made the attestation nonce server-relevant; deferred
output re-download/re-hash until an artifact store exists.

### Smoke test now covers (33 assertions, all passing)
booking/capacity/oversell, idempotency, heartbeat/reaper liveness, WG safety,
job dispatch + ownership boundary, **signed proof-of-work, forged-signature
rejection, known-answer pass/fail, and reputation-gated paid work.**

---

## Settlement layer (added) — escrow, payout ledger, refund-on-reap

Money now actually moves, with once-only guards so it can't be double-paid.
All paths verified in `smoke_test.py`.

- **Wallet + deposit.** Buyers hold a `balance`; sellers accrue `earnings`.
  `POST /deposit` is a sandbox top-up (production: a payment-provider webhook),
  `GET /wallet` reads balances.
- **Escrow on booking.** `request_vm` checks funds, **atomically debits** the buyer
  (conditional UPDATE — no overspend), reserves a unit, and holds the gross in
  escrow (`status=escrowed`). Insufficient funds → 402.
- **State machine:** `escrowed → active` (on task creation) `→ released`
  (seller + platform paid) or `→ refunded` (buyer made whole). Release and refund
  use guarded conditional updates, so a booking settles **exactly once**.
- **Auto-release on job success.** A completed signed job result releases its
  booking: seller `earnings += seller_payout`, platform `revenue += platform_fee`.
- **Refund-on-reap (the reliability guarantee).** The reaper now calls
  `settle_dead_specs`: when a node goes offline, its in-flight bookings are
  refunded to the buyer, capacity is freed, and their tasks are failed —
  idempotently (no double refund on repeated reaper cycles).
- **Append-only ledger** records every movement (deposit / escrow_hold /
  release_seller / release_platform / refund_buyer) so balances are always
  reconstructable after a crash. Buyer/seller booking views via `GET /bookings/{id}`.

Production note: `/deposit` is the one intentionally-sandboxed seam — swap it for
Stripe/stablecoin settlement without touching the escrow logic.

### Smoke test (now 53 assertions, all passing)
adds: deposit/wallet, escrow-on-book + buyer debit, active-on-task,
auto-release with correct payout split, double-release guard, and
**refund-on-reap made whole + idempotent**.

---

## Demo layer (added) — CLI, marketplace browse, buyer dashboard

The "investor can watch it work in 90 seconds" layer. CLI verified end-to-end
against a live server; dashboard verified to serve.

- **`GET /specs`** — bookable inventory (attested + online + has capacity + trusted
  seller), price-sorted. **`GET /marketplace/stats`** — public nodes-online /
  GPUs-listed / jobs-completed / GMV for the dashboard hero numbers.
- **CLI (`cli/petabyte.py`)** — `register / login / deposit / wallet / specs / run`.
  `run notebook.ipynb --gpu H100` picks the cheapest matching GPU, escrows funds,
  dispatches the notebook, polls, and prints the result. E2E tested: book → escrow
  → dispatch → COMPLETED with output, buyer debited correctly.
- **Buyer dashboard** — served by the API at `/` (same-origin, no CORS). Live
  stats, wallet + deposit, GPU inventory with a **$/hr-vs-AWS savings column**, and
  one-click job runs. This is the screen to record for investors.
- **Bug fixed:** `/jobs/next` returned a body with `204 No Content` (uvicorn
  "Response content longer than Content-Length"); now a proper empty 204.

---

## One-line node installer (added)

Removes the supply-side onboarding friction: `bash <(curl … install.sh)` turns a
GPU box into a bookable node in one command.

- **`install.sh`** — installs Docker + Python, fetches the agent, runs provisioning,
  installs the `petabyte-agent` systemd service.
- **`provision.py`** — detects CPU/RAM/GPU, registers the spec, **attests with the
  agent's Ed25519 key**, mints a 90-day API key, writes `/etc/petabyte/agent.env`.
  Verified end-to-end: provisioning produces a node that is attested, online (after
  first heartbeat), and **bookable in `/specs`** with its detected hardware.
- **`petabyte-agent.service`** — runs the heartbeat + job loop; same signing key
  for attestation and results.
- See `lumaris_agent/INSTALL.md`.

---

## Go-live edits (added) — gated deposits, payment webhook, env-driven price

- **`/deposit` gated by `PAYMENTS_MODE`.** Default `sandbox` keeps the demo top-up;
  `live` returns 403 so balances can't be minted for free.
- **Signed payment webhook `POST /webhooks/payment`.** Verifies an HMAC-SHA256
  signature over the raw body (swap for `stripe.Webhook.construct_event` in prod),
  credits the buyer, and is **idempotent on `event_id`** (no double-credit on
  retries). Verified: bad signature → 401, valid → credit, replay → no re-credit;
  live-mode `/deposit` → 403 while the webhook still credits.
- **Dashboard AWS reference price is env-driven** (`AWS_REFERENCE_PRICE`), injected
  at serve time — no code edit to keep the savings column honest.
- Production env documented in `template.env` and `deploy/DEPLOY.md`
  (PAYMENTS_MODE, PAYMENT_WEBHOOK_SECRET, ALLOWED_ORIGINS, MIN_REPUTATION,
  AWS_REFERENCE_PRICE).

### Note on the VPN
WireGuard config generation is correct and leak-free, but live peer application
stays OFF (`WG_APPLY=false`) by design — the notebook-job path (CLI + dashboard)
needs no VPN. Real tunnels require a privileged peer-reconciler service + NAT +
UDP 51820; deferred until interactive VM rental is a customer ask.

---

## Confidential computing (added) — "the seller can't see your data"

Extends attestation from *integrity* (work ran correctly) to *confidentiality*
(seller can't inspect the data). Pluggable TEE verifier with a tested stub and
clearly-marked seams for the real vendor verifiers.

- **Challenge–response:** `POST /attestation/challenge` issues a one-time,
  server-side nonce the TEE report must embed (replay protection).
- **`POST /prove_tee`:** verifies a TEE remote-attestation report — nonce binding,
  freshness, **enclave-measurement allowlist**, and the vendor signature — then
  marks the spec `confidential`. Stub uses Ed25519 against `TEE_TRUSTED_ROOT`;
  production swaps in NVIDIA NRAS (H100 CC) / AMD SEV-SNP (VCEK chain) / Intel TDX.
- **Buyer-side zero-trust:** `GET /specs/{id}/attestation` returns the raw report so
  the BUYER verifies it against the vendor root **before uploading data** — they
  never trust the seller's or even Petabyte's word. (Verified in the smoke test.)
- **Filtering + gating:** `GET /specs?confidential=true`; `request_vm
  {require_confidential:true}` rejects non-CC hardware (403) so sensitive jobs
  only land in enclaves.
- Env: `TEE_TRUSTED_ROOT`, `TEE_MEASUREMENT_ALLOWLIST`.

Verified: TEE attest accepted, bad measurement rejected, replayed nonce rejected,
forged vendor signature rejected, confidential filter, confidential-only gate, and
**buyer independent verification of the enclave report**.

Positioning: integrity is guaranteed cryptographically today; confidentiality on
untrusted nodes is delivered by CC attestation — route sensitive jobs only to
`confidential=true` specs, everything else to standard nodes.

---

## Organizations + data residency (added) — enterprise/academic enablement

The organizational layer institutional buyers need before they can say yes.

- **Org accounts + roles.** `POST /orgs` (creator = admin), `POST /orgs/{id}/members`
  with roles **admin / billing / member**. Admin manages members; admin/billing
  fund the wallet; members spend.
- **Shared wallet + budget cap.** `POST /orgs/{id}/deposit` funds a shared balance
  with an optional `budget_cap`. `request_vm {org_id}` charges the org wallet
  (atomic, budget-capped) instead of the individual; refunds return to the org.
- **Usage export / invoicing.** `GET /orgs/{id}/usage` — per-booking line items +
  total, the seed of real invoices/cost-center reporting (from the ledger).
- **Data residency.** Specs carry `region`/`country`; `GET /specs?region=` filters;
  `request_vm {require_region}` rejects out-of-region hardware (GDPR/residency gate),
  composable with `require_confidential`.

Verified: role enforcement (member can't add members or deposit), org-wallet debit,
**budget-cap enforcement**, non-member can't charge the org, residency gate, and
usage export.

What's still NON-code for institutional sales (sales artifacts, not features):
a Trust Center page, a DPA template, a SOC 2 roadmap, and a security-questionnaire
(CAIQ/VSA) answer doc. SSO/SAML and a formal audit come later.

---

## GeoIP region verification (added) — residency becomes a control, not a label

Previously `region`/`country` were self-declared (a routing hint, not a guarantee).
Now they're IP-verified.

- **On heartbeat**, the node's source IP is geolocated; `detected_country` is stored
  and `region_verified` is set only when **declared country == detected country**.
- **The residency gate now requires verification:** `request_vm {require_region}`
  and `{require_country}` only accept specs with `region_verified == true`, so a node
  declaring DE while reporting from an SG IP is rejected (verified in the test).
- `/specs` surfaces `detected_country` + `region_verified`.
- **Pluggable lookup** (`utils.geolocate_country`): tested stub via `GEOIP_STUB`;
  production points `GEOIP_DB` at a MaxMind GeoLite2 DB (or swap an ipinfo API call).

Honest assurance level (state this in the Trust Center): region is **IP-verified**,
which catches mislabeling but is defeatable by VPN/proxy. Hard residency guarantees
need provider/TEE-attested datacenter location — roadmap, and it binds to the same
attestation chain as confidential computing.

---

## Templates, benchmarks, job management, scoped keys, analytics (added)

**#9 One-click templates** — `GET /templates` (Ollama, vLLM, TensorRT-LLM, ComfyUI,
SD WebUI). `create_task {task_type:"template", template, template_params:{model}}`;
`jobs/next` hands the agent the image/port/cache/model; the agent launches the
container (GPU, HF model, a named cache volume for model caching) and reports the
endpoint via `/jobs/vm_details`.

**#4 Benchmarks** — `POST /benchmark` dispatches a job; the agent submits a SIGNED
`/jobs/benchmark_result` (tokens/sec + a `meta` dict for SD images/sec, etc.),
recorded on the spec and surfaced in `/specs` (`benchmark_tokens_sec`) — the input
to the dashboard's $/token-vs-AWS comparison.

**#5 Job management** — `Task.priority` (higher served first), `POST /tasks/{id}/retry`
(bounded re-queue of failed tasks), `POST /jobs/progress` + progress in
`GET /tasks/{id}`, and **live logs over WebSocket** at `/ws/tasks/{id}/logs?token=`
(buyer-owned, fed by the agent's `/jobs/log`).

**#10 Enterprise** — **scoped API keys** (`create_api_key?scopes=node,jobs`; enforced,
e.g. a key without `node` can't heartbeat) and **cost analytics**
`GET /orgs/{id}/analytics` (spend totals, by status, by spec). Org accounts/teams/
usage shipped earlier. **SSO (SAML/OIDC) intentionally deferred** — it's a
week of work done for a named deal, not speculatively.

Agent gains `_run_template`, `_run_benchmark`, progress/log reporting. Container
launch + the real benchmark harness need a GPU node to execute; the dispatch,
signing, recording, retry, priority, progress, and WebSocket paths are all tested.

---

## Backup / restore for any stateful task (added) + game-server templates

A general durability layer (game servers are one consumer). The API tracks backup
references + integrity hashes; the bytes go node -> object storage directly (the
API is never a data plane).

- **Per-task backups:** `create_task {backup_enabled, backup_interval_s, volume}`.
  The agent snapshots the volume every interval and submits a SIGNED
  `POST /jobs/checkpoint` (snapshot_ref + size + content_hash) → stored as a
  `Checkpoint`, newest tracked on the task.
- **Restore on claim:** `jobs/next` hands the agent `restore_from` (the latest
  snapshot) so it pulls + restores the volume before starting.
- **Reschedule on node death:** the reaper RESCHEDULES backup-enabled tasks (resume
  from the last checkpoint) and keeps the booking active, instead of refund-and-fail.
  A grace window (`BACKUP_RESCHEDULE_GRACE_S`, default 900s) falls back to refund if
  the node never returns. Non-backup tasks keep the original refund-on-reap behavior.
- **Manual restore:** `POST /tasks/{id}/restore` (latest or a chosen checkpoint);
  `GET /tasks/{id}/checkpoints` lists history.
- **Game-server templates:** minecraft / valheim / factorio (stateful, backup-friendly).
- Agent: `_restore_volume`, `_backup_once`, `_start_backup_thread` (S3/`aws s3` seams;
  need BACKUP_BUCKET + creds on the node to execute).

HONEST assurance (for the Trust Center, NOT a "0% loss / 99% uptime" claim):
recovery point = the backup interval (e.g. ≤5 min); on failure the task resumes from
the last checkpoint when the node returns (same-node today; cross-node rescheduling
is roadmap). Publish measured uptime from heartbeat data rather than guaranteeing it.

---

## Secure direct-from-node backups (added)

Replaces the insecure `aws s3 cp`-with-ambient-creds placeholder.

- **`POST /jobs/backup_url`** mints a per-object, 15-min **pre-signed PUT URL** +
  the per-task encryption key. Nodes hold NO standing object-storage credentials and
  can write exactly one tenant-prefixed key (`backups/{buyer}/{task}/...`).
- **`POST /jobs/restore_url`** mints a pre-signed GET URL + the signed `content_hash`
  so the agent verifies integrity (and decrypts) before restoring.
- Agent encrypts the tarball client-side before upload; verifies the hash on restore.
- `deploy.sh` creates + hardens the bucket (private, versioned, TLS-only, SSE,
  lifecycle); S3 env placeholders added to `template.env`.
- Verified: tenant-prefixed grant, non-owner denied, presigned PUT/GET, hash returned,
  unknown-snapshot rejected. (boto3 calls stubbed via `S3_STUB` in tests.)

---

## Reputation, AI Router, Render farm (added)

**Reputation (event-sourced).** Per-spec counters (jobs completed/failed, fraud,
latency, heartbeats) + an append-only `ReputationEvent` log. `compute_reputation`
derives an auditable 0-100 score + breakdown ON READ (not a mutable, forgeable
integer). Signals recorded automatically: completion (+latency), failure, fraud
(forged/expired result signatures), benchmarks, uptime. `GET /specs/{id}/reputation`
returns the breakdown + recent events; `/specs` surfaces `reputation_score`. This is
the compounding, hard-to-copy dataset — and the input the router routes on.

**AI Router — `POST /solve`.** Intent in (workload, gpu_class, min_vram, region,
country, confidential, redundancy, budget), placement plan out. Hard-filters verified
inventory then scores by blended reputation / price / throughput, selecting N nodes
across DISTINCT providers for real redundancy. Own inventory only today;
`router.gather_candidates` is the provider-agnostic seam where external-cloud
adapters plug in later (the honest version of "the global compute exchange").
Verified: 2-node distinct-provider plans, region/confidential/price honoring, 409 on
no-fit.

**Render farm — `POST /render`.** Splits a frame range across N router-selected
nodes (contiguous chunks), books each, and dispatches a `render` task per node;
a dropped frame just re-renders via retry. `blender` template added; agent
`_run_render` (Blender CLI + pre-signed output upload). Verified: 1-100 split into
1-50/51-100 across two nodes, each node receiving its subrange.

HONEST framing for the pitch: "we discover, VERIFY, route, and manage compute across
our network of private GPU providers today, with a provider-agnostic router built to
absorb public-cloud capacity — and a reputation dataset that makes our routing
smarter than renting raw boxes." Multi-cloud adapters are roadmap, not a present
claim.

---

## Render runs in a container (correction) — sellers never install Blender

The earlier `_run_render` shelled out to a HOST-installed `blender` binary — wrong:
it would force every seller to install Blender. Fixed to the platform's containerized
model (same as vLLM/Ollama/game servers):

- The render task carries a container **image** (`jobs/next` returns it); the agent
  `docker run`s Blender **pulled on demand and cached** — the seller installs only
  Docker + the NVIDIA runtime, once. Nodes stay generic (render today, LLM tomorrow).
- **No host-binary fallback:** if Docker is absent the render fails (consistent with
  the sandbox). GPU via `--gpus all` (NVIDIA Container Toolkit).
- **Scene in / frames out via pre-signed URLs:** the node pulls the `.blend` with a
  `POST /jobs/input_url` GET grant and uploads encrypted frames via the one-object
  `POST /jobs/backup_url` PUT grant — no standing object-storage creds on the node.

Verified: the render task carries an image + GPU flag, and the node fetches the scene
via a pre-signed GET. (Actual container execution needs a Docker node.)

Cold-start note: first render of an image on a node pays a one-time image pull;
subsequent renders reuse the cached layer. Pre-warming popular images is a future
routing signal ("already-cached" nodes score higher for that workload).

---

## Seller payouts + scheduled withdrawals (added)

Withdraw seller earnings via swappable rails; USD stays the unit of account.

- **Provider abstraction** (`payout_providers.py`): one `PayoutProvider` interface
  with a tested stub and real-adapter seams — **gift_card** (Tremendous/Tango),
  **usdc** (Circle, low-fee chain), **bank** (Stripe Connect). Gift cards = lightest
  compliance and the pragmatic first rail for hard-to-bank global sellers.
- **Flow:** add method -> verify (KYC + sanctions `screen()` seam) -> `POST
  /wallet/withdraw` atomically debits earnings and enqueues a `Payout`
  (requested -> sent/confirmed | failed; failure refunds). Same guarded/idempotent
  pattern as escrow.
- **Scheduled auto-withdraw:** `POST /wallet/schedule {day_of_week, hour, minute,
  utc_offset_minutes, min_amount}` — e.g. **Monday 08:00 local**. `run_due_schedules`
  fires due schedules (skips if under `min_amount`), advances to next week. Run by
  `tools/payout_worker.py` on a systemd timer.
- Verified: earnings accrual, unverified-method block, atomic withdraw, provider
  confirm, over-withdraw 402, schedule compute (future Monday 08:00), due-firing,
  balance emptied, next-week advance. (Provider + KYC/AML stubbed via `PAYOUT_STUB`.)

HONEST scope: the code is the escrow pattern pointed at a payout adapter; the real
project is KYC/AML/sanctions/tax + legal review (the `screen()` and provider seams).
Gift cards never accepted as BUYER funding (fraud/laundering risk) — payout side only.

---

## Email / notifications (added)

Transactional email with the same swappable-provider pattern as payouts.

- **Provider abstraction** (`notify_providers.py`): `EmailProvider` with a tested stub
  + real seams (SendGrid / AWS SES / Postmark), toggled by `NOTIFY_STUB`/`EMAIL_PROVIDER`.
- **Dispatch** (`notifications.py`): renders an event from a template, records it to a
  `Notification` audit log, sends via the provider, and respects the user's email +
  opt-out (`notify_email`). Safe no-op (status `skipped`) if the user has no email.
- **Events wired:** `payout.requested` (on withdraw), `payout.confirmed` /
  `payout.failed` (from the worker's `on_status` hook). Templates also ready for
  `booking.refunded` and `job.completed`.
- **Endpoints:** `POST /account/email` (set address + opt-out), `GET /notifications`
  (audit log). `User.email` + `User.notify_email` added.
- Verified: withdraw emits a 'requested' email (sent), the worker emits 'confirmed'
  (sent), and a user with no email is recorded as 'skipped'. (Delivery stubbed via
  `NOTIFY_STUB`.)

---

## Video transcoding + fan-out assembly (added) — also fixes render stitching

- **FFmpeg template** (`ffmpeg`, NVENC image) + **`transcode` task type**: codec
  (h264/h265/av1), resolution, bitrate/CRF, container, GPU (NVENC) or CPU.
- **`POST /transcode`**: single node for short files; for long ones, splits the
  timeline into N segments (contiguous), routes each to a verified node, and tracks
  a **manifest**. Segments transcode in parallel; a dropped one re-transcodes.
- **Manifest + stitch layer** (`MultiNodeJob`/`JobSegment`, reused by render): when
  all segments finish, the API auto-books a node and dispatches a **stitch** task
  (FFmpeg concat for transcode; frame-collect for render) → single assembled output.
  `GET /jobs/manifest/{id}` shows per-segment status + the final `output_ref`. This is
  the output-assembly piece render was missing — **render now uses the same manifest**.
- **Buyer one-click upload:** `POST /uploads/url` returns a pre-signed PUT under the
  buyer's own `inputs/{buyer}/…` prefix; buyer uploads the video, then calls
  `/transcode` with that ref.
- Agent: containerized `_run_transcode` (FFmpeg NVENC, scene/output via pre-signed
  URLs, **no host install**) + `_run_stitch` (concat/collect).
- Verified: upload grant, 2-segment fan-out + contiguous split, containerized task
  handoff, all-segments→assembling→complete with assembled output, single-node path,
  and render assembling via the shared manifest.

**Adobe:** deliberately NOT added — it's a licensing/OS problem (proprietary,
Windows/macOS, EULA restricts cloud/rented use), not a compute one. Path is
enterprise BYOL render-engine on Windows nodes + legal review; open alternatives
(Blender, FFmpeg, DaVinci Resolve) cover most needs. Deferred until a customer needs it.

---

## Idle fallback (added) — a node earns a trickle when unrented (seller retention)

Framed honestly as supply-side retention ("your GPU always earns something"), NOT an
autonomous revenue model. NiceHash (auto-switches algorithm, pays BTC) via container.

- **Opt-in per node, OFF by default:** `POST /nodes/idle_fallback {spec_id, enabled}`;
  the flag rides the heartbeat response so the agent knows whether to mine when idle.
- **Paid work ALWAYS preempts:** the agent kills the miner the instant it claims a job
  (`stop_idle_miner()` before running any task); starts it only on a 204 (no work).
- **Seller's NiceHash wallet stays on the node** (`NICEHASH_ADDRESS`/`IDLE_MINING`
  local env) — Petabyte never receives creds or holds mining funds; earnings go
  straight to the seller. Optional `POST /nodes/idle_report` + `GET /nodes/{id}/idle`
  give the seller visibility only.
- Agent: `start_idle_miner`/`stop_idle_miner` (container, `--gpus all`), gated by BOTH
  local creds and the platform flag.
- Verified: OFF by default, opt-in/out, heartbeat signal, non-owner can't toggle,
  idle-report visibility. (Actual mining container needs Docker+GPU — a stub seam.)

HONEST caveats (in the docs): mining is often unprofitable after power cost — the
seller decides; it's a floor, not a business; Petabyte takes no cut and holds no
mining funds. This is a marketplace-stickiness feature, not "revenue without buyers."

---

## Idle mining unified into one balance + functional providers + security pass

- **Unified idle earnings:** each node mines to Petabyte's NiceHash account as worker
  `pb-<spec_id>`; `reconcile_idle_earnings` credits the seller's ONE balance
  `amount*(1-NICEHASH_TAKE_RATE)` as an idempotent `idle_mining` ledger entry
  (`IdleSettlement` unique on worker+period), platform keeps the cut. Sellers need NO
  NiceHash account/wallet and withdraw via the existing payout+schedule system.
  `nicehash.py` (HMAC-signed API, stubbed via `NICEHASH_STUB`); `tools/idle_reconcile.py`
  worker. Dropped the per-seller-wallet path; opt-in + hard preemption unchanged.
  Verified: credit math, platform cut, idempotency per period, worker-id attribution.
- **Provider stubs made FUNCTIONAL:** payout (Tremendous/Circle/Stripe) and email
  (SendGrid/SES/Postmark) adapters are now real API-call code (need creds to run) —
  no more NotImplementedError. Stubs remain only for tests.
- **Security assessment** (`SECURITY_ASSESSMENT.md`): static scan clean (no
  eval/exec/shell/SQLi/hardcoded secrets), 66/67 routes auth-guarded (the 1 is
  self-authenticating), money paths atomic+idempotent, isolation enforced. Residual
  risk is the live adversarial tests (sandbox escape, TEE authenticity, preemption).

---

## UX pass — redesigned dashboard + CLI polish

- **Buyer dashboard rebuilt** (`static_dashboard.py`, served at `/`) with a distinct
  identity: deep indigo "night-grid" base, energy-amber + electric-cyan accents (the
  energy-to-intelligence thesis, not a generic dark-green terminal), Space Grotesk +
  JetBrains Mono. Signature = a **live exchange board** whose stats count-up as jobs
  settle. Now surfaces reputation score, verified-region and confidential **badges**,
  tokens/sec, and the vs-cloud saving; streaming job console; proper empty/error
  states, keyboard focus, reduced-motion, responsive. Same-origin, price injected via
  `AWS_REFERENCE_PRICE`. Verified it serves.
- **CLI polish** (`cli/petabyte.py`): color output (respects `NO_COLOR`/non-TTY),
  clearer specs table with trust tags, and ✓/✗ run headers. Verified end-to-end.

---

## Windows seller nodes (added)

Windows machines join via **WSL2** running the standard (tested) Linux agent — one
codebase, no second agent. `install.ps1` (elevated PowerShell one-liner): verifies
admin + NVIDIA driver → installs WSL2 + Ubuntu 24.04 (one reboot may be needed) →
enables systemd → runs the normal `install.sh` inside WSL → Scheduled Task keeps the
node online at logon. `install.sh` now also installs **nvidia-container-toolkit**
when a GPU is present (native Ubuntu AND WSL2) so Docker gets `--gpus all`.
Buyer jobs run in Docker *inside the WSL2 VM* — an extra VM boundary protecting the
seller's Windows host. Docs: `lumaris_agent/WINDOWS.md` (incl. honest limits:
sleep/hibernate = offline + reaper refund; battery throttling).
