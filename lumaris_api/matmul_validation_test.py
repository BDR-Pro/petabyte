"""Offline unit tests for the pytorch-matmul-v1 result validator.

No GPU required: the GPU only produces a manifest; validation is arithmetic +
signature verification. We forge manifests + signatures with a throwaway Ed25519
key and assert the verdict for the happy path and every failure mode the task
requires (wrong seed/nonce/digest, tampered fields, bad/expired signature,
duplicate submission, runtime bounds, telemetry, numeric tolerance).

Run: python matmul_validation_test.py
"""
import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import matmul_validation as mv

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- signing helpers (mirror lumaris_agent/crypto.py) --------------------------
_key = Ed25519PrivateKey.generate()
PUB = base64.b64encode(_key.public_key().public_bytes_raw()).decode()
OTHER = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()


def sign(proof: dict) -> str:
    msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(_key.sign(msg)).decode()


def make(expected: mv.ExpectedJob, *, ts=None, overrides=None, sign_key_ok=True,
         summary=(120.0, 0.5, 34.6)):
    """Build a fully-consistent, signed manifest for `expected`, then apply overrides."""
    ts = int(time.time()) if ts is None else ts
    m = {
        "job_id": expected.job_id, "transaction_id": expected.transaction_id,
        "template": mv.TEMPLATE_NAME, "template_version": expected.template_version,
        "container_digest": "sha256:abc123", "seed": expected.seed, "nonce": expected.nonce,
        "matrix_size": expected.matrix_size, "iterations": expected.iterations,
        "dtype": expected.dtype, "gpu_uuid": "GPU-xxxx", "gpu_model": "NVIDIA L4",
        "cuda_version": "12.1", "pytorch_version": "2.4.0", "elapsed_ms": 5000.0,
        "result_sum": summary[0], "result_mean": summary[1], "result_norm": summary[2],
        "sample_values": [1.0, 2.0, 3.0], "ts": ts,
    }
    if overrides:
        m.update(overrides)
    m["manifest_hash"] = mv.canonical_manifest_hash(m)
    proof = {"output_hash": m["manifest_hash"], "ts": ts}
    key_used = _key if sign_key_ok else None
    if key_used is None:
        # sign with a different key -> signature won't verify against PUB
        bad = Ed25519PrivateKey.generate()
        msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
        sig = base64.b64encode(bad.sign(msg)).decode()
    else:
        sig = sign(proof)
    return m, sig


REF = {"result_sum": 120.0, "result_mean": 0.5, "result_norm": 34.6}


def expected(**kw):
    base = dict(job_id="job-1", transaction_id="tx-1", seed=42, nonce="n0nce",
                matrix_size=2048, iterations=5, dtype="float32",
                allowed_container_digests=("sha256:abc123",),
                expected_summary=dict(REF))
    base.update(kw)
    return mv.ExpectedJob(**base)


# ---- happy path ---------------------------------------------------------------
e = expected()
m, sig = make(e)
r = mv.validate(e, m, attest_pubkey=PUB, signature=sig)
ok("VALID: consistent, signed, in-tolerance, allowlisted", r.status == mv.VALID)
ok("VALID => may_pay is True", mv.may_pay(r.status) is True)

# manifest-hash recompute is stable + prefix
ok("manifest hash is sha256-prefixed", m["manifest_hash"].startswith("sha256:"))

# ---- identity / challenge binding --------------------------------------------
m, sig = make(e, overrides={"job_id": "job-OTHER"})
ok("INVALID: wrong job_id", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, overrides={"transaction_id": "tx-OTHER"})
ok("INVALID: wrong transaction_id", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, overrides={"nonce": "wrong"})
ok("INVALID: wrong nonce (no precompute/replay)", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, overrides={"seed": 999})
ok("INVALID: wrong seed", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, overrides={"template_version": "2"})
ok("INVALID: wrong template_version", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

# ---- container digest allowlist ----------------------------------------------
m, sig = make(e, overrides={"container_digest": "sha256:evil"})
ok("INVALID: container digest not allowlisted", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

# ---- manifest tampering (hash mismatch) --------------------------------------
m, sig = make(e)
m["result_sum"] = 999999.0   # change a hashed field WITHOUT recomputing the hash
ok("INVALID: tampered field breaks manifest_hash", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

# ---- signature ----------------------------------------------------------------
m, sig = make(e, sign_key_ok=False)
ok("INVALID: signature from wrong key", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, ts=int(time.time()) - 5000)   # older than 600s window
ok("INVALID: expired signature (replay window)", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

# ---- duplicate submission -----------------------------------------------------
m, sig = make(e)
r = mv.validate(e, m, attest_pubkey=PUB, signature=sig, seen_manifest_hashes={m["manifest_hash"]})
ok("INVALID: duplicate manifest submission", r.status == mv.INVALID)

# ---- runtime bounds -----------------------------------------------------------
m, sig = make(e, overrides={"elapsed_ms": 999999.0})
ok("INVALID: elapsed exceeds max runtime", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

m, sig = make(e, overrides={"elapsed_ms": 0.0})
ok("INCONCLUSIVE: elapsed below plausible floor", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INCONCLUSIVE)

# ---- telemetry ----------------------------------------------------------------
m, sig = make(e, overrides={"telemetry_max_gpu_util": 0})
ok("INCONCLUSIVE: telemetry shows 0% GPU", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INCONCLUSIVE)

# ---- numeric tolerance --------------------------------------------------------
m, sig = make(e, summary=(120.0005, 0.5001, 34.6003))  # within default tol
ok("VALID: numerics within tolerance", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.VALID)

m, sig = make(e, summary=(200.0, 0.5, 34.6))           # sum way off
ok("INVALID: numeric result outside tolerance", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

# no reference -> cannot confirm correctness -> INCONCLUSIVE (never auto-paid)
e_noref = expected(expected_summary=None)
m, sig = make(e_noref)
r = mv.validate(e_noref, m, attest_pubkey=PUB, signature=sig)
ok("INCONCLUSIVE: no numeric reference", r.status == mv.INCONCLUSIVE)
ok("INCONCLUSIVE => may_pay is False", mv.may_pay(r.status) is False)

# ---- missing fields -----------------------------------------------------------
m, sig = make(e)
del m["gpu_uuid"]
m["manifest_hash"] = mv.canonical_manifest_hash(m)   # even if re-hashed, missing field is caught
proof = {"output_hash": m["manifest_hash"], "ts": m["ts"]}
sig = sign(proof)
ok("INVALID: missing required field", mv.validate(e, m, attest_pubkey=PUB, signature=sig).status == mv.INVALID)

print(f"\n=== matmul-validation: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
