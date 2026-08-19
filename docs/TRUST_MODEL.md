# Petabyte trust model — what's enforced vs. what needs hardware

Three properties the marketplace is built to guarantee, and an honest account of how far
each is enforced **today in code** vs. what fundamentally requires a hardware TEE or a larger
feature. Nothing here is aspirational marketing — each "enforced" item points at code + tests.

---

## 1. "No seller should know the job load" — job confidentiality

**Enforced today**
- The dispatch payload never carries the buyer's username, org, or email; `claimed_by` is the
  seller's own id. Platform secrets are never in the payload.
- Cross-tenant reads are blocked: an assigned node can only presign object keys under the
  task-buyer's own `inputs/<buyer_id>/` prefix (`main.py` `input_url` + bind-time checks;
  `security_test.py`). One seller can never read another tenant's data.
- Object data is client-side encrypted at rest (Fernet + optional SSE) so the *storage
  operator* can't read it.
- **Confidential computing is now enforced, not decorative** (see §confidential below): a
  `require_confidential` booking fails closed unless the target spec holds a **fresh** TEE
  attestation, and in production the software stub cannot mint that attestation at all.

**Requires a hardware TEE — NOT solvable in software**
- Hiding the *bytes being computed* (notebook code, the scene/video the GPU processes, model
  weights, outputs) from a **host-root seller**. The node must decrypt to compute, so any key
  it holds and any mounted volume / process memory is readable by the machine's owner. Only an
  encrypted-memory enclave (AMD SEV-SNP / Intel TDX / NVIDIA H100 CC) with real vendor remote
  attestation closes this. Petabyte's verifier is **pluggable and fail-closed** for exactly
  this reason — the day a real verifier is configured, `confidential` becomes a hardware fact.

**Honest gap (closeable without TEE, not yet done):** the dispatch payload still embeds the
buyer's numeric id + original filename inside object refs, and logs the job type locally.
These let a seller *profile* the workload (not read it). Tracked as a follow-up: opaque
per-object handles + metadata minimization.

### Confidential computing — what changed
- `utils.verify_tee_report` is a **pluggable verifier** (`TEE_VERIFIER`, default `stub`). Real
  vendor verifiers (NVIDIA NRAS JWT / AMD VCEK chain / Intel DCAP) register in one map.
- **Fail closed in production:** with `TEE_REQUIRE_HARDWARE=true` (and always when
  `ENVIRONMENT=production`), the software stub is **refused** — a `confidential=True` badge
  can never be minted from it where it would mislead a buyer. (`tee_test.py`)
- **Freshness:** a confidential attestation is stamped (`tee_attested_at`) and expires after
  `TEE_ATTESTATION_TTL_S` (default 24h). `db.spec_confidential_active` gates the booking on
  *fresh* attestation, so a stale flag attests nothing about the machine today.

---

## 2. "No seller could fabricate a GPU or a job result"

**Enforced today**
- Every result is Ed25519-signed by the node's attested device key with a replay window; a
  bad signature is rejected **and freezes the seller's payouts** (`/jobs/result`).
- Known-answer platform audits + redundant-execution **quorum** freeze sellers who diverge
  (`seller_audit.py`, `quorum.py`, tests).
- A deterministic result validator exists (`matmul_validation.py`): challenge binding,
  container-digest allowlist, runtime floor, telemetry-zero check, numeric tolerance.
- Payouts hold for `PAYOUT_HOLD_DAYS` (default 14) so a fraud freeze can catch a bad actor
  before money leaves.

**Landed**
- **Gamer-style GPU authenticity check (benchmark vs. public reference), multi-benchmark.** The
  way a gamer proves a card is real — run a benchmark, compare the score to the numbers everyone
  publicly knows for that exact card — across several benchmarks, each with its own per-GPU public
  reference table (`gpu_benchmark.py`). Every measured score travels **inside the node's signed
  proof** (attributable), and the server grades each against the **claimed** `gpu_model`
  (`classify_all`):

  | metric | what it is | public reference | freezes payouts? |
  |---|---|---|---|
  | `tflops_fp16` | measured FP16 dense matmul TFLOPS | vendor datasheet tensor peak | **yes** |
  | `blender_optix` | Blender Open Data score (OptiX, samples/min) | opendata.blender.org | no (advisory) |
  | `cinebench_2024_gpu` | Cinebench 2024 GPU (Redshift) | Maxon Cinebench | no (advisory) |
  | `pugetbench_resolve` | PugetBench — DaVinci Resolve Studio | pugetsystems.com | no (advisory) |
  | `pugetbench_premiere` | PugetBench — Premiere Pro | pugetsystems.com | no (advisory) |
  | `hashrate_ethash_mhs` | mining hashrate (DaggerHashimoto/Ethash MH/s) | NiceHash / miner community | no (advisory) |

  **Blender is the flagship 3D benchmark** because Petabyte *renders Blender* — the agent already
  shells out to a Blender container, so the benchmark measures the real workload, and Blender Open
  Data publishes a per-GPU median to compare against (`task_fetcher._measure_blender_score` runs
  the official `benchmark-launcher-cli` where installed). Cinebench covers Cinema 4D / Redshift;
  PugetBench covers the video-editing fleet. **Mining hashrate** (NiceHash / Ethash) is a
  *memory-bandwidth* proxy — a different GPU dimension than compute (TFLOPS) or RT-core render — so
  a card can't fake bandwidth it lacks; a node's idle-mining hashrate (`/nodes/idle_report`) is
  compared to the public per-GPU number automatically.

  A score far below what the claimed card can do → verdict `implausibly_low`; above what it can do
  → `suspiciously_high`; within the (wide) band → `consistent`, shown to buyers as
  **"Benchmark-consistent — matches public reference data for the advertised card."** Only the
  hardware-invariant **FP16 TFLOPS** metric may **freeze payouts** (`freeze_for_fraud`, on a gross
  over-claim below `GPU_BENCH_FRAUD_FLOOR_FRAC`, default 20 % of peak). The **render/video metrics
  are advisory**: a mismatch flags the listing and suppresses the trust boost but never auto-freezes,
  because their public medians depend on Blender/driver version, scene, and (for Puget) the whole
  system — corroboration, not proof. A card absent from a metric's table resolves to `unknown_model`
  (recorded, shown, never flagged). Tests: `gpu_benchmark_test.py` (per-metric + aggregate) +
  `smoke_test.py` (FP16 freeze on over-claim, Blender consistent + advisory-flag-no-freeze).

  *Honest limits:* it verifies a performance **class**, not the exact die (adjacent tiers overlap,
  so it catches gross over-claims — H100-listed-but-T4 — not an A100-for-H100 swap); render
  benchmarks rank GPUs **differently** than TFLOPS (RT-core presence dominates OptiX), which is why
  each metric has its own table; and it stops **over**-claiming, not bait-and-switch (benchmark a
  real card, run the job elsewhere) — that needs the benchmark to become a platform-dispatched,
  seed-bound, server-timed re-run against a random fraction of *real* jobs. This is the
  reference-comparison half of that. Reference numbers are approximate public medians (wide
  tolerance) — recalibrate against each source's live dataset.
- **Results now bind to the real output bytes (#65).** Every completed render/transcode/stitch
  result carries a `content_hash` = sha256 of the *plaintext* output bytes, **inside the signed
  proof** (both agents), and the server persists it (`Task.result_content_hash`). Quorum
  comparison uses this content hash. So a seller commits to the actual output — two honest nodes
  doing the same deterministic work produce the same hash — instead of signing a bare object-ref
  string.
- **Real-job re-verification is now wired (`reverify.py`).** A random fraction
  (`REVERIFY_SAMPLE_RATE`, default 0 / opt-in) of completed **deterministic** real jobs
  (render/transcode/stitch) is **re-executed on independent nodes** and the signed content hashes
  compared — quorum on *real* work, not just a distinct `test` task. A node whose hash diverges
  from the honest majority is **frozen for fraud**; with only one shadow a mismatch is
  inconclusive and holds both for review (never a false freeze). Reuses the QuorumCheck engine.
  Tests: `reverify_test.py` (honest agree / faker outvoted-and-frozen / sampling gate / no
  fan-out). *Remaining:* full server-side recompute of the *uploaded object* still needs real
  object storage; the cross-node hash comparison is in place now.
- **The benchmark is server-seeded, server-timed, and replay-proof.** Every dispatched benchmark
  now carries a **fresh server proof-of-work challenge** (`create_benchmark_task` seeds a random
  `bench_seed`); the node must return the correct `compute_test_hash(size, seed)` for *that* seed
  **inside the signed proof**. A wrong answer means the number wasn't produced by real, current
  computation on the node — a fabricated or replayed benchmark can't solve a seed it never saw —
  so it is rejected (`409`) and **freezes the seller's payouts**. The platform also observes the
  wall-clock dispatch→result server-side (`Task.assigned_at` → `benchmark_elapsed_s`) and
  **consumes** the task on submission (a re-submission gets `409`). Tests: `smoke_test.py`
  (correct answer → `pow_verified`; fabricated answer → `409` + freeze).
- **Benchmark tier is honestly labelled (#64).** A benchmark inconsistent with the claimed GPU
  model's public reference data is flagged, not rewarded; a bare self-report (no public band) is
  "Benchmark-reported", stated as **node-reported and signed (attributable), not independently
  measured** — never "measured".

**Honest gaps (closeable in software — roadmap, not yet enforced)**
- The strongest validator (`matmul_validation.py`) **is** wired into live settlement:
  `settlement_verification.decide(...)` runs on the auto-settle-on-result path
  (`AUTO_SETTLE_ON_RESULT`, on by default) and uses it, so `pytorch-matmul-v1` pays only
  on a VALID verdict (fail-closed). What remains is wiring it into the **reverify
  comparison** — with the signed `content_hash` stored and `reverify.py` re-executing
  real jobs, that comparison is the next step.
- The benchmark now carries a fresh **server-seeded proof-of-work** (a fabricated/replayed number
  can't answer the seed) + server-timing, so it proves *real, current computation on the node*.
  What it does **not** yet prove is that the throughput number came from *that GPU*: the
  integer proof-of-work runs on any CPU. Making the seeded workload itself the FLOP-heavy GPU
  matmul, and checking the reported rate against the server-observed time for a server-fixed FLOP
  count, is the remaining upgrade (the GPU-model signal today is the public-reference band check).

**Requires hardware attestation**
- Proving the *specific silicon* (an "H100" really is an H100; VRAM is real) and that work ran
  *on a GPU* for non-deterministic / interactive jobs. Self-reported telemetry and container
  digests only become evidence when they come from attested hardware. The current TEE verifier
  is a stub; §confidential above makes it honest (fail-closed) until a real one is wired.

---

## 3. "No seller could be harmed by a job they run" — seller protection

**Enforced today** (`lumaris_agent` / `desktop-app` / `install.sh`; `sandbox_test.py`)
- Images are **platform-controlled** — a buyer picks a template *name* from a fixed catalog;
  no arbitrary-image injection. No job container mounts the docker socket, host FS, or secrets;
  none run `--privileged` or `--network host`.
- **Every** buyer container runs with `--cap-drop ALL` + `no-new-privileges` + pids/memory
  caps (Linux and the shipped desktop agent). Render/transcode/stitch run `--network none`;
  render passes Blender `--disable-autoexec`.
- A host **egress firewall** (`install.sh`, `DOCKER-USER` chain) DROPs container traffic to the
  cloud-metadata endpoint (`169.254.0.0/16` — IAM credential theft) and the seller's private
  LAN (`10/8`, `192.168/16`). A job can't remove the rules because it holds no NET_ADMIN/RAW.
- The buyer's service port is published to `127.0.0.1` only (was `0.0.0.0` on desktop).

**Roadmap (defense-in-depth, not yet shipped):** install + require gVisor (`runsc`) as the
default runtime; ephemeral per-booking cache volumes; scoped `--gpus device=…`.

---

## Configuration knobs
| Var | Default | Meaning |
|---|---|---|
| `TEE_VERIFIER` | `stub` | Which TEE verifier to use (real: `nvidia-nras`/`sev-snp`/`tdx`). |
| `TEE_REQUIRE_HARDWARE` | (prod: on) | Refuse the software stub — no fake confidential badges. |
| `TEE_ATTESTATION_TTL_S` | `86400` | How long a confidential attestation stays valid. |
| `GPU_BENCH_LOW_FRAC` | `0.30` | Benchmark ≥ this × the claimed model's peak reads as consistent. |
| `GPU_BENCH_HIGH_FRAC` | `1.15` | Above this × peak is `suspiciously_high` (never a freeze). |
| `GPU_BENCH_FRAUD_FLOOR_FRAC` | `0.20` | Below this × peak = gross over-claim → payout freeze. |
| `PETABYTE_LOCKDOWN_EGRESS` | `true` | Install the container egress firewall. |
| `PAYOUT_HOLD_DAYS` | `14` | Fraud-catch window before payouts settle. |
