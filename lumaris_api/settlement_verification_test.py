"""Offline tests for the result-verification settlement gate (audit #4/#8).

Proves settlement_verification.decide() returns the right action for each case, using the REAL
matmul validator + Ed25519 signing (no GPU, no DB): a verifiable job pays only on a VALID verdict,
FAILS on a provably-wrong result, and DEFERS (fail-closed) when it can't be verified; everything
else settles on content-hash + async reverify.

Run: python settlement_verification_test.py
"""
import base64
import json
import os
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import matmul_validation as mv
import settlement_verification as sv

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# --- signing (mirrors lumaris_agent/crypto.py + matmul_validation_test) ---
_key = Ed25519PrivateKey.generate()
PUB = base64.b64encode(_key.public_key().public_bytes_raw()).decode()


def _sign(proof: dict) -> str:
    msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(_key.sign(msg)).decode()


CHALLENGE = dict(job_id="job-1", transaction_id="tx-1", seed=42, nonce="n0nce",
                 matrix_size=2048, iterations=5, dtype="float32",
                 allowed_container_digests=["sha256:abc123"],
                 expected_summary={"result_sum": 120.0, "result_mean": 0.5, "result_norm": 34.6})


def _manifest(expected, *, overrides=None, ts=None, summary=(120.0, 0.5, 34.6)):
    ts = int(time.time()) if ts is None else ts
    m = {"job_id": expected.job_id, "transaction_id": expected.transaction_id,
         "template": mv.TEMPLATE_NAME, "template_version": expected.template_version,
         "container_digest": "sha256:abc123", "seed": expected.seed, "nonce": expected.nonce,
         "matrix_size": expected.matrix_size, "iterations": expected.iterations,
         "dtype": expected.dtype, "gpu_uuid": "GPU-x", "gpu_model": "NVIDIA L4",
         "cuda_version": "12.1", "pytorch_version": "2.4.0", "elapsed_ms": 5000.0,
         "result_sum": summary[0], "result_mean": summary[1], "result_norm": summary[2],
         "sample_values": [1.0, 2.0, 3.0], "ts": ts}
    if overrides:
        m.update(overrides)
    m["manifest_hash"] = mv.canonical_manifest_hash(m)
    sig = _sign({"output_hash": m["manifest_hash"], "ts": ts})
    return m, sig


class _Task:
    def __init__(self, *, template=None, challenge=None, manifest=None, signature=None):
        self.template = template
        self.template_params = json.dumps({"matmul_challenge": challenge}) if challenge else "{}"
        self.result_proof = json.dumps({"manifest": manifest}) if manifest else "{}"
        self.result_signature = signature


_exp = mv.ExpectedJob(**CHALLENGE)

# 1) non-verifiable job type -> settle (content-hash + async reverify carry it)
act, _ = sv.decide(_Task(template="notebook"), None, attest_pubkey=PUB)
ok("non-verifiable job type settles", act == sv.SETTLE)
act, _ = sv.decide(_Task(template=None), None, attest_pubkey=PUB)
ok("job with no template settles", act == sv.SETTLE)

# 2) verifiable + valid challenge + valid signed manifest -> settle
m, sig = _manifest(_exp)
act, why = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=CHALLENGE, manifest=m, signature=sig),
                     None, attest_pubkey=PUB)
ok("verifiable job with a VALID manifest settles", act == sv.SETTLE)
ok("settle reason cites verification VALID", "VALID" in why)

# 3) verifiable + provably wrong result (numerics out of tolerance) -> FAIL (bill nothing)
mbad, sbad = _manifest(_exp, summary=(200.0, 0.5, 34.6))
act, why = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=CHALLENGE, manifest=mbad, signature=sbad),
                     None, attest_pubkey=PUB)
ok("verifiable job with an INVALID result FAILS (never pays)", act == sv.FAIL)

# 3b) forged signature (wrong key) -> INVALID -> FAIL
m2, _ = _manifest(_exp)
_badsig = base64.b64encode(Ed25519PrivateKey.generate().sign(b"x")).decode()
act, _ = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=CHALLENGE, manifest=m2, signature=_badsig),
                   None, attest_pubkey=PUB)
ok("verifiable job with a forged signature FAILS", act == sv.FAIL)

# 4) verifiable but NO challenge issued -> defer (fail-closed)
act, _ = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=None, manifest=m, signature=sig),
                   None, attest_pubkey=PUB)
ok("verifiable job with no server challenge DEFERS (fail-closed)", act == sv.DEFER)

# 5) verifiable + challenge but NO manifest carried -> defer
act, _ = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=CHALLENGE, manifest=None, signature=sig),
                   None, attest_pubkey=PUB)
ok("verifiable job with no result manifest DEFERS", act == sv.DEFER)

# 6) verifiable + valid but no attestation pubkey to bind to hardware -> defer
act, _ = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=CHALLENGE, manifest=m, signature=sig),
                   None, attest_pubkey=None)
ok("verifiable job with no attest pubkey DEFERS", act == sv.DEFER)

# 7) INCONCLUSIVE (no numeric reference) -> defer, never pay
_ch_noref = dict(CHALLENGE); _ch_noref["expected_summary"] = None
_exp_noref = mv.ExpectedJob(**_ch_noref)
mnr, snr = _manifest(_exp_noref)
act, why = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=_ch_noref, manifest=mnr, signature=snr),
                     None, attest_pubkey=PUB)
ok("verifiable job with no numeric reference is INCONCLUSIVE -> DEFERS (never auto-pays)",
   act == sv.DEFER and "INCONCLUSIVE" in why)

# 8) operator opt-out: SETTLEMENT_REQUIRE_VERIFICATION=false lets a missing-challenge job settle
os.environ["SETTLEMENT_REQUIRE_VERIFICATION"] = "false"
act, _ = sv.decide(_Task(template=mv.TEMPLATE_NAME, challenge=None, manifest=None, signature=None),
                   None, attest_pubkey=PUB)
ok("SETTLEMENT_REQUIRE_VERIFICATION=false lets an unverifiable job settle (explicit opt-out)",
   act == sv.SETTLE)
os.environ.pop("SETTLEMENT_REQUIRE_VERIFICATION", None)

print(f"\n=== settlement-verification: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
