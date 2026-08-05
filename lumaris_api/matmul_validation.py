"""Server-side result validation for the `pytorch-matmul-v1` workload.

WHY THIS EXISTS
---------------
Petabyte must never pay a seller because their agent said `completed=true`. For a
deterministic compute job the platform re-derives everything it can and refuses to
settle unless the result is provably the one it asked for, produced on the attested
hardware. This module is that check — pure, deterministic, and unit-testable
WITHOUT a GPU (the GPU only produces the manifest; validation is arithmetic +
signature verification).

It is intentionally decoupled from the job/settlement wiring: give it the job the
server issued and the manifest the agent returned, and it returns a verdict. The
caller (a future `/jobs/result` handler for this template) decides settlement —
and MUST only capture + transfer on `VALID` (see `may_pay`).

VALIDATION STATES (a seller is paid ONLY on VALID)
    PENDING          not yet evaluated
    VALID            every check passed; safe to capture + transfer
    INVALID          a check failed; do NOT pay (refund/release per policy)
    INCONCLUSIVE     cannot confirm correctness (e.g. no numeric reference, or
                     telemetry shows no GPU activity); do NOT auto-pay
    MANUAL_REVIEW    needs a human; do NOT auto-pay

The manifest hash and signature use the SAME canonical-JSON + Ed25519 scheme the
rest of the platform uses (see utils.verify_signed_proof, agent crypto.sign_proof),
so a manifest signed by the agent verifies here unchanged.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable

from utils import verify_signed_proof   # same Ed25519 + canonical-JSON used platform-wide

TEMPLATE_NAME = "pytorch-matmul-v1"
VALIDATOR_VERSION = "matmul-validator/1"

PENDING = "PENDING"
VALID = "VALID"
INVALID = "INVALID"
INCONCLUSIVE = "INCONCLUSIVE"
MANUAL_REVIEW = "MANUAL_REVIEW"

# Fields that go into the canonical manifest hash. Order is irrelevant (canonical
# JSON sorts keys); `manifest_hash` and `agent_signature` are excluded on purpose.
_MANIFEST_FIELDS = (
    "job_id", "transaction_id", "template", "template_version", "container_digest",
    "seed", "nonce", "matrix_size", "iterations", "dtype",
    "gpu_uuid", "gpu_model", "cuda_version", "pytorch_version",
    "elapsed_ms", "result_sum", "result_mean", "result_norm", "sample_values",
)


def canonical_manifest_hash(manifest: dict) -> str:
    """SHA-256 over the canonical JSON of the manifest fields (excluding the hash
    and signature). Prefixed 'sha256:' to match the platform's digest style."""
    payload = {k: manifest.get(k) for k in _MANIFEST_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


@dataclass
class ExpectedJob:
    """The authoritative, server-issued parameters for one matmul job. The server
    generates seed + nonce; matrix_size/iterations/dtype are server-controlled."""
    job_id: str
    transaction_id: str
    seed: int
    nonce: str
    matrix_size: int
    iterations: int
    dtype: str = "float32"
    template_version: str = "1"
    allowed_container_digests: tuple[str, ...] = ()
    min_elapsed_ms: float = 1.0            # a real GPU matmul cannot take ~0ms
    max_elapsed_ms: float = 120_000.0      # strict maximum runtime (ms)
    # Optional numeric reference (result_sum/mean/norm). Without it, numerics
    # cannot be confirmed and the verdict is INCONCLUSIVE (never auto-paid).
    expected_summary: dict | None = None
    rel_tol: float = 1e-3
    abs_tol: float = 1e-3


@dataclass
class ValidationResult:
    status: str
    reason: str
    validator_version: str = VALIDATOR_VERSION
    expected_summary: dict | None = None
    reported_summary: dict | None = None
    tolerance_used: dict | None = None
    checks: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == VALID


def may_pay(status: str) -> bool:
    """The ONLY status that authorises capture + seller transfer."""
    return status == VALID


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _within(reported, expected, rel_tol, abs_tol) -> bool:
    r, e = _num(reported), _num(expected)
    if r is None or e is None:
        return False
    return abs(r - e) <= max(abs_tol, rel_tol * abs(e))


def validate(expected: ExpectedJob, manifest: dict, *, attest_pubkey: str,
             signature: str, seen_manifest_hashes: Iterable[str] = (),
             max_signature_age_s: int = 600) -> ValidationResult:
    """Validate one reported matmul manifest against the server-issued job.

    `manifest`   the agent's reported result (see _MANIFEST_FIELDS + manifest_hash).
    `attest_pubkey` the spec's attestation pubkey (binds result -> attested HW).
    `signature`  the agent's Ed25519 signature over the signed proof.
    `seen_manifest_hashes` manifest hashes already accepted (duplicate guard).
    """
    checks: dict = {}
    reported_summary = {k: manifest.get(k) for k in ("result_sum", "result_mean", "result_norm")}
    tol = {"rel_tol": expected.rel_tol, "abs_tol": expected.abs_tol}

    def result(status, reason):
        return ValidationResult(status, reason, expected_summary=expected.expected_summary,
                                reported_summary=reported_summary, tolerance_used=tol,
                                checks=checks)

    # 0) structural: required fields present
    required = set(_MANIFEST_FIELDS) | {"manifest_hash"}
    missing = [k for k in required if manifest.get(k) is None]
    checks["structure"] = not missing
    if missing:
        return result(INVALID, f"manifest missing required fields: {sorted(missing)}")

    # 1) identity binding: this manifest must be for THIS job/transaction/template
    if str(manifest["job_id"]) != str(expected.job_id):
        checks["job_id"] = False
        return result(INVALID, "job_id does not match the issued job")
    if str(manifest["transaction_id"]) != str(expected.transaction_id):
        checks["transaction_id"] = False
        return result(INVALID, "transaction_id does not match the issued job")
    if manifest.get("template") != TEMPLATE_NAME:
        checks["template"] = False
        return result(INVALID, f"template is not {TEMPLATE_NAME}")
    if str(manifest.get("template_version")) != str(expected.template_version):
        checks["template_version"] = False
        return result(INVALID, "template_version mismatch")
    checks["identity"] = True

    # 2) challenge binding: server-issued seed + nonce + shape must be echoed exactly.
    #    A mismatch means the agent did not run OUR challenge (possible replay/precompute).
    for k, exp in (("seed", expected.seed), ("nonce", expected.nonce),
                   ("matrix_size", expected.matrix_size), ("iterations", expected.iterations),
                   ("dtype", expected.dtype)):
        if str(manifest.get(k)) != str(exp):
            checks["challenge"] = False
            return result(INVALID, f"challenge mismatch on '{k}' (expected {exp!r})")
    checks["challenge"] = True

    # 3) container digest allowlist (only enforced when an allowlist is configured)
    if expected.allowed_container_digests:
        if manifest.get("container_digest") not in expected.allowed_container_digests:
            checks["container_digest"] = False
            return result(INVALID, "container_digest not in the approved allowlist")
    checks["container_digest"] = True

    # 4) manifest hash: re-derive and compare (detects any field tampering)
    recomputed = canonical_manifest_hash(manifest)
    if recomputed != manifest.get("manifest_hash"):
        checks["manifest_hash"] = False
        return result(INVALID, "manifest_hash does not match the reported fields")
    checks["manifest_hash"] = True

    # 5) duplicate submission guard
    if manifest["manifest_hash"] in set(seen_manifest_hashes):
        checks["duplicate"] = False
        return result(INVALID, "duplicate result submission (manifest already accepted)")
    checks["duplicate"] = True

    # 6) signature: binds the manifest hash to the attested hardware key.
    proof = {"output_hash": manifest["manifest_hash"], "ts": manifest.get("ts")}
    try:
        verify_signed_proof(attest_pubkey, proof, signature, max_age_s=max_signature_age_s)
        checks["signature"] = True
    except ValueError as e:
        checks["signature"] = False
        return result(INVALID, f"invalid agent signature: {e}")

    # 7) runtime bounds
    elapsed = _num(manifest.get("elapsed_ms"))
    if elapsed is None or elapsed > expected.max_elapsed_ms:
        checks["runtime"] = False
        return result(INVALID, "elapsed_ms missing or exceeds the maximum runtime")
    if elapsed < expected.min_elapsed_ms:
        checks["runtime"] = False
        # Too fast to be a real GPU matmul of this size -> needs telemetry review.
        return result(INCONCLUSIVE, "elapsed_ms below the plausible floor; telemetry review needed")
    checks["runtime"] = True

    # 8) telemetry consistency (optional): if we were told GPU util and it's flat 0,
    #    the "GPU job" may not have used the GPU -> cannot confirm.
    gpu_util = manifest.get("telemetry_max_gpu_util")
    if gpu_util is not None and _num(gpu_util) == 0:
        checks["telemetry"] = False
        return result(INCONCLUSIVE, "telemetry reports 0% GPU utilisation")
    checks["telemetry"] = True

    # 9) numeric correctness within tolerance (needs a server reference)
    if not expected.expected_summary:
        checks["numeric"] = None
        return result(INCONCLUSIVE,
                      "no numeric reference available; correctness unconfirmed")
    for k in ("result_sum", "result_mean", "result_norm"):
        if not _within(manifest.get(k), expected.expected_summary.get(k),
                       expected.rel_tol, expected.abs_tol):
            checks["numeric"] = False
            return result(INVALID, f"numeric result '{k}' outside tolerance")
    checks["numeric"] = True

    return result(VALID, "all checks passed")
