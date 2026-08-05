# Buyer → Seller GPU E2E Report

```
FINAL STATUS:
BLOCKED_EXTERNAL  (live flow un-runnable from this environment; see evidence)

PUBLIC SITE:
Unverifiable from this environment — https://petabyte.market returns HTTP 403
at the Anthropic egress gateway (policy denial, not TLS). Health unknown.

GPU:
Not detected — no route to the seller Droplet (165.22.236.63), no SSH, no
nvidia-smi in this environment.

TEMPLATES:
Audited: 12 container templates + 8 built-in task types (docs/WORKLOAD_TEMPLATE_AUDIT.md).
GPU-verified working: 0 (blocked — needs live GPU).  Hidden: 0.  Removed: 0.
(No template deleted blindly; a live verification matrix is the required next step.)

STRIPE TEST PAYMENT:
Not attempted — no Stripe keys in this environment and Stripe API is behind the
same denying egress gateway. The authorize→capture code path EXISTS and passes
offline tests (stripe_test.py), but no real test PaymentIntent was created here.

SELLER TEST TRANSFER:
Not attempted — same reason. Connect transfer code EXISTS and passes offline
tests; no real transfer created.

SUCCESSFUL STANDARD RUNS:
0  (require 2; cannot run live)

FAILURE TESTS:
0 live.  (The offline suite already covers many failure paths — forged
signature, duplicate capture, duplicate transfer, illegal FSM transitions.)

AUTOMATED TESTS:
See "Automated test results" below (offline suites run in this environment).

CRITICAL REMAINING BLOCKERS:
1. No network egress to the Droplets, the live site, or Stripe from this session.
2. No SSH client/key (DEPLOY_SSH_KEY is a GitHub secret, absent here).
3. No GPU/torch/nvidia-smi in this session.
4. IMPLEMENTATION GAP (in-repo, real): the validated-matmul paid flow is not
   wired end-to-end today (details in "Gap analysis"). Even with access it would
   not pass yet without the net-new work listed.

SAFE TO POWER OFF DROPLETS:
This run created NO state on either Droplet (it never reached them). From this
run's perspective there is nothing to preserve. Keep them powered on only if you
intend to run the live E2E next; otherwise they are safe to power off. Only you
should approve destroying them.
```

---

## 1. Roles (as specified)

- **Buyer Droplet** `137.184.198.133` — buyer-side test client / browser + API.
- **Seller GPU Droplet** `165.22.236.63` — Petabyte seller agent + real GPU.
- **Public target** `https://petabyte.market` — final proof must go through here.
- **Buyer account:** `testUser` (password redacted).
- **Seller account:** `testUserSeller` (password redacted).

No password, SSH key, Stripe key, or webhook secret appears in this report,
in the artifacts, or in this branch's git history.

## 2. Why the live flow could not run from this session (direct evidence)

Reconnaissance was run **before** any change. All paths the task depends on are
blocked at the environment level:

| Requirement | Probe | Result |
|---|---|---|
| SSH to buyer `137.184.198.133:22` | TCP connect | **timeout** (blocked) |
| SSH to seller `165.22.236.63:22` | TCP connect | **timeout** (blocked) |
| `ssh` client present | `command -v ssh` | **absent** |
| `DEPLOY_SSH_KEY` in env | `printenv` | **absent** (it is a GitHub Actions secret) |
| Reach `https://petabyte.market` | `curl --cacert <bundle>` via proxy | **HTTP 403** CONNECT denied (policy, not TLS) |
| Direct HTTPS to Droplet IPs :443 | `curl --noproxy '*'` | intercepted by *"Anthropic Egress Gateway CA"*, **HTTP 403** |
| Stripe keys / Stripe API | env + egress | **absent / denied** |
| GPU present | `nvidia-smi` | **absent**; `torch` not installed |

The TLS certificates presented for the "direct" connections to both Droplet IPs
are issued by **`O=Anthropic, CN=Egress Gateway ... CA`** — i.e. the sandbox's
egress gateway transparently intercepts and denies these destinations. This is a
network **policy denial**, verified with the correct CA bundle, not a
misconfiguration I can fix from inside the sandbox.

**Conclusion:** the buyer→seller paid E2E (SSH into the Droplets, install the
seller agent, detect the GPU, drive the public site, create Stripe test objects)
is **not executable from this Claude Code session.** Per the task's own
"External blockers" rule, this is verified with evidence, is not an ordinary
implementation bug, and the exact required user action is given in §6.

**No live evidence was fabricated.** No Stripe objects, GPU records, transfers,
screenshots, or Playwright traces were invented. `artifacts/e2e-run-state.json`
records `status: BLOCKED_EXTERNAL`.

## 3. What the platform actually implements today (code review)

Evidence is cited by `file:line`. Full inventory drove `docs/WORKLOAD_TEMPLATE_AUDIT.md`.

### Strong: the money state machine (production-shaped, tested)
- Explicit FSM `DRAFT → PAYMENT_AUTHORIZED → GPU_RESERVED → DISPATCHING →
  RUNNING → METERING_FINALIZED → PAYMENT_CAPTURE_PENDING → PAYMENT_CAPTURED →
  SELLER_TRANSFER_PENDING → SELLER_TRANSFERRED → COMPLETED` with guarded
  transitions and failure edges — `stripe_connect.py:53-97`.
- Manual-capture PaymentIntent (`capture_method="manual"`), server-side
  re-verification of `requires_capture` — `stripe_connect.py:299-326`.
- Reserve-after-authorize, partial capture of **metered** usage, Connect
  transfer to seller (separate charges + transfers, at-most-once), refund +
  transfer reversal, double-entry ledger — `stripe_connect.py:330-802`.
- Webhooks with signature verification, at-most-once processing, and
  reconciliation — `main.py:3495`, `stripe_connect.py:821-992`.
- Immutable TEST/LIVE `mode` on every financial record; live keys refused unless
  an explicit multi-flag gate is set. Offline suite `stripe_test.py` drives the
  whole FSM incl. idempotency/duplicate-capture/duplicate-transfer.

### Present: job dispatch + signed results + known-answer validation
- `GET /jobs/next` atomic ownership-scoped claim; task types `notebook`, `test`,
  `benchmark`, `render`, `transcode`, `stitch`, `template`, `vm` —
  `main.py:1757-1803`.
- `POST /jobs/result` verifies an **Ed25519 signed proof** against the spec's
  attestation key (600s replay window) — `main.py:1806-1868`, `utils.py:156-171`.
- **Server-generated known-answer** test workloads (size+seed, server computes
  the expected integer hash, agent must match) — `main.py:1775`,
  `db.py:compute_test_hash`, `record_test_result`.
- Real GPU **batch** execution exists for `render` (Blender `--gpus all`) and
  `transcode` (ffmpeg NVENC `--gpus all`) — `lumaris_agent/task_fetcher.py`.

## 4. Gap analysis — why the *requested* validated-matmul paid flow is not yet end-to-end

The requested flow (buyer pays → seller GPU runs `pytorch-matmul-v1` → server
validates the numeric result → meters real GPU seconds → captures → transfers)
needs four net-new pieces. None are "external"; all are real engineering:

1. **No `pytorch-matmul-v1` workload.** `grep -i matmul` across the tree returns
   nothing. The `pytorch` template is a bare base image ("bring your own
   script"). The LLM `benchmark` harness is an explicit **stub**
   (`task_fetcher.py:294-307`, `"harness":"stub"`).
2. **No numeric/manifest result validation.** For real jobs, `/jobs/result`
   stores only a signature + `output_hash`. There is no manifest re-hash,
   numeric tolerance check, nonce/seed re-binding, container-digest allowlist, or
   `validation_status ∈ {PENDING,VALID,INVALID,INCONCLUSIVE,MANUAL_REVIEW}`.
3. **Metering is not measured from the GPU.** `record_metering` takes seconds
   from an **admin/test endpoint** (`main.py:3382`); there is no agent→metering
   bridge feeding real GPU wall-clock into the ComputeTransaction.
4. **The paid path is not wired to the compute FSM.** `/launch` and `/request_vm`
   are gated on the internal wallet, not on a verified Stripe ComputeTransaction;
   `/jobs/result` settles via the legacy `release_booking` wallet path, while
   capture/transfer live in the ComputeTransaction FSM driven manually/by tests.
   The repo itself flags this as "the central rewire" and **not done**
   (`docs/REMOVED_PAYMENT_STUBS.md:91`).

## 5. Work done in this run (in-repo, offline-verified only)

- `docs/WORKLOAD_TEMPLATE_AUDIT.md` — full template + task-type audit.
- `artifacts/e2e-run-state.json`, `docs/OVERNIGHT_E2E_PROGRESS.md` — honest,
  restartable state (status `BLOCKED_EXTERNAL`).
- `lumaris_api/matmul_validation.py` — the **`pytorch-matmul-v1` result
  validator** (the piece the task most emphasizes: "Petabyte must not trust the
  seller merely reporting completed"). Pure-Python, deterministic, **buildable
  and unit-testable without a GPU**: canonical manifest hashing (SHA-256),
  nonce/seed re-binding, template-version + container-digest allowlist, numeric
  tolerance comparison, runtime bounds, Ed25519 signature verification, duplicate
  detection, and the `PENDING/VALID/INVALID/INCONCLUSIVE/MANUAL_REVIEW` decision
  with reasons.
- `lumaris_api/matmul_validation_test.py` — unit tests for the validator
  (VALID + each INVALID/INCONCLUSIVE path). Wired into `run_tests.sh` and CI.

**Scope honesty:** the validator is a unit-tested *component*. It is **not yet
wired into the live `/jobs/result` path**, and it has **not** been exercised
against a real GPU-produced manifest (no GPU/infra access). It exists so the
central validation logic is correct and tested before the live wiring — it is
groundwork, **not** a claim of end-to-end success.

## 6. Exact action required to unblock (choose one)

The live E2E needs an environment that can (a) SSH to both Droplets with
`DEPLOY_SSH_KEY`, (b) reach `https://petabyte.market` and the Stripe API, and (c)
has Stripe **test** keys configured on the deployed platform.

- **Option A — run from the buyer Droplet.** SSH in yourself, install Playwright
  there (it already has open internet to the site), and run the browser flow from
  there. The seller agent install commands are in `lumaris_agent/INSTALL.md`.
- **Option B — GitHub Actions job.** A workflow with `secrets.DEPLOY_SSH_KEY` +
  Stripe **test** secrets and open egress can SSH to both Droplets and drive the
  flow. (This still requires the §4 implementation work first.)
- **Option C — grant this session egress + the SSH key.** Allow the sandbox to
  reach the two Droplet IPs on :22 and `petabyte.market`/Stripe, and provide the
  SSH key by a secure channel (not in chat/logs/git).

Before any live paid run, first complete the §4 implementation (the matmul
workload + agent harness, the metering bridge, the validation wiring using
`matmul_validation.py`, and the paid-path→FSM rewire), because the flow will not
pass end-to-end without them.

## 7. Automated test results (this environment)

See the CI `tests` workflow and `lumaris_api/run_tests.sh`. The new
`matmul_validation_test.py` is included. Offline suites (smoke, adversarial,
stripe, payout, email, matmul-validation) run on SQLite here; Postgres-only
invariants run in CI.

## 8. Remaining limitations

- No live buyer→seller transaction was performed; all live evidence fields
  (PaymentIntent/Charge/Transfer IDs, GPU model/UUID, job/reservation IDs,
  webhook event IDs, screenshots, Playwright trace) are **absent by necessity**
  and must be filled by a run from an environment with access.
- No template is marked `WORKING_AND_TESTED`: that requires a real GPU run.
- The §4 implementation gap remains; `matmul_validation.py` closes part of it
  (validation logic) but the workload, metering bridge, and paid-path wiring are
  still to do and must be verified live.
