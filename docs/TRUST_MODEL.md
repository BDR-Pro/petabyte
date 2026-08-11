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

**Honest gaps (closeable in software — roadmap, not yet enforced)**
- The strongest validator (`matmul_validation.py`) is **not yet wired into the live result
  path**, and results are bound to a seller-chosen `output_hash`, not to a server- or
  quorum-recomputed hash of the actual output bytes. **Fix in flight (#65):** put a real
  content hash in the result model and re-verify / quorum-compare it.
- Audits/quorum arrive as a distinct `test` task the agent can branch on, and run only when
  scheduled. **Fix:** subject a random fraction of *real* jobs to redundant re-execution.
- `benchmark_verified` is derived from a **self-reported** `tokens_sec` (an agent env var),
  so it is a *signed, attributable claim* — **not** an independent measurement. The trust
  ladder must present it as self-reported, and marketing must never call it "measured." (#64)

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
| `PETABYTE_LOCKDOWN_EGRESS` | `true` | Install the container egress firewall. |
| `PAYOUT_HOLD_DAYS` | `14` | Fraud-catch window before payouts settle. |
