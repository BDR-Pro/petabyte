"""tee_test.py — confidential computing is REAL and ENFORCED, never faked.

Two honest guarantees, offline:
  * the software-stub TEE verifier is REFUSED in production (or when TEE_REQUIRE_HARDWARE=true),
    so a `confidential=True` badge can never be minted from the stub where it would tell a
    buyer their workload is hidden from the seller when it is not;
  * a confidential attestation goes STALE — spec_confidential_active gates on freshness, so a
    months-old flag can't authorize a confidential booking/dispatch today.

No network, no GPU, no real TEE. Run: python tee_test.py
"""
import base64
import json
import os
import types
from datetime import timedelta

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

os.environ.setdefault("DATABASE_URL", "sqlite:///./tee_test.db")
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ.pop("TEE_REQUIRE_HARDWARE", None)
os.environ.pop("ENVIRONMENT", None)
os.environ["TEE_VERIFIER"] = "stub"

_SK = Ed25519PrivateKey.generate()
os.environ["TEE_TRUSTED_ROOT"] = base64.b64encode(_SK.public_key().public_bytes_raw()).decode()
os.environ["TEE_MEASUREMENT_ALLOWLIST"] = "mr_h100_cc_v1"

import utils   # noqa: E402
import db as dbmod   # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def signed_report(nonce="n1", measurement="mr_h100_cc_v1", ts=None):
    import time
    rep = {"nonce": nonce, "measurement": measurement, "vendor": "nvidia-h100-cc",
           "ts": int(ts if ts is not None else time.time())}
    msg = json.dumps(rep, sort_keys=True, separators=(",", ":")).encode()
    sig = base64.b64encode(_SK.sign(msg)).decode()
    return rep, sig


def raises(fn, needle=None):
    try:
        fn()
        return False
    except ValueError as e:
        return (needle in str(e)) if needle else True


# -------------------------------------------------- verifier: allowed in dev, closed in prod
rep, sig = signed_report()
ok("dev: stub verifier accepts a valid signed report",
   utils.verify_tee_report(rep, sig, "n1") == "mr_h100_cc_v1")

os.environ["TEE_REQUIRE_HARDWARE"] = "true"
ok("TEE_REQUIRE_HARDWARE=true: stub is REFUSED (fail closed, no fake confidential)",
   raises(lambda: utils.verify_tee_report(*signed_report(), "n1"), "hardware"))
del os.environ["TEE_REQUIRE_HARDWARE"]

os.environ["ENVIRONMENT"] = "production"
ok("production: stub is REFUSED (fail closed)",
   raises(lambda: utils.verify_tee_report(*signed_report(), "n1"), "hardware"))
del os.environ["ENVIRONMENT"]

ok("dev again: stub works once the hardware requirement is lifted",
   utils.verify_tee_report(*signed_report(), "n1") == "mr_h100_cc_v1")

os.environ["TEE_VERIFIER"] = "nonesuch"
ok("an unknown TEE_VERIFIER is REJECTED",
   raises(lambda: utils.verify_tee_report(*signed_report(), "n1"), "unknown TEE verifier"))
os.environ["TEE_VERIFIER"] = "stub"

# a still-valid report with a WRONG nonce / stale ts / bad measurement still fails
ok("wrong nonce rejected", raises(lambda: utils.verify_tee_report(rep, sig, "other"), "nonce"))
ok("expired report rejected",
   raises(lambda: utils.verify_tee_report(*signed_report(ts=0), "n1"), "expired"))
ok("non-allowlisted measurement rejected",
   raises(lambda: utils.verify_tee_report(*signed_report(measurement="mr_bad"), "n1"),
          "allowlist"))


# -------------------------------------------------- freshness (spec_confidential_active)
now = dbmod._utcnow()


def spec(confidential=True, attested_delta=None):
    ns = types.SimpleNamespace(confidential=confidential, tee_attested_at=None)
    if attested_delta is not None:
        ns.tee_attested_at = now - attested_delta
    return ns


ttl = dbmod._tee_attestation_ttl_s()
ok("fresh confidential attestation is ACTIVE",
   dbmod.spec_confidential_active(spec(attested_delta=timedelta(0)), now=now) is True)
ok("attestation within the TTL is ACTIVE",
   dbmod.spec_confidential_active(spec(attested_delta=timedelta(seconds=ttl - 60)), now=now))
ok("attestation past the TTL is STALE (not active)",
   dbmod.spec_confidential_active(spec(attested_delta=timedelta(seconds=ttl + 60)), now=now)
   is False)
ok("confidential flag with NO attestation timestamp is not active (fail closed)",
   dbmod.spec_confidential_active(spec(confidential=True, attested_delta=None), now=now) is False)
ok("a non-confidential spec is never active",
   dbmod.spec_confidential_active(spec(confidential=False, attested_delta=timedelta(0)), now=now)
   is False)


print(f"\n=== tee: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
