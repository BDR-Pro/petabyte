"""sign_release_test.py — the release signer's output is accepted by BOTH shipped verifiers.

Closes the producer<->verifier loop offline:
  * the Windows manifest sign_release builds is accepted by desktop-app/updater.verify_update,
    and a tampered binary / wrong key is rejected;
  * the Linux raw .sig verifies with the pinned public key exactly as update.sh's
    `openssl pkeyutl -verify -rawin` would.

No network, no Windows, no GPU. Run: python scripts/sign_release_test.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "desktop-app"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402

import sign_release as sr   # noqa: E402
import updater              # noqa: E402  (the shipped Windows verifier)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


key = Ed25519PrivateKey.generate()
PUB_B64 = sr.pub_b64(key)

# a fake release exe + tarball
_fd, EXE = tempfile.mkstemp(suffix=".exe"); os.write(_fd, b"EXE" + os.urandom(2048)); os.close(_fd)
_fd, TAR = tempfile.mkstemp(suffix=".tar.gz"); os.write(_fd, b"TAR" + os.urandom(2048)); os.close(_fd)

# ---- Windows: producer manifest is accepted by the shipped verifier ----
manifest = sr.build_manifest(EXE, "1.4.0", key)
ok("signed manifest is ACCEPTED by desktop updater.verify_update",
   updater.verify_update(EXE, manifest, PUB_B64)[0] is True)
ok("same manifest is REJECTED against a different pinned key",
   updater.verify_update(EXE, manifest,
                         sr.pub_b64(Ed25519PrivateKey.generate()))[0] is False)
# tamper the binary -> hash no longer matches the signed manifest
with open(EXE, "ab") as f:
    f.write(b"malware")
ok("a tampered binary is REJECTED (sha256 no longer matches the signed manifest)",
   updater.verify_update(EXE, manifest, PUB_B64)[0] is False)

# ---- Linux: raw .sig verifies with the pinned public key (mirrors openssl -rawin) ----
sig = sr.sign_bundle_raw(TAR, key)
pub = key.public_key()
verified = True
try:
    pub.verify(sig, open(TAR, "rb").read())
except InvalidSignature:
    verified = False
ok("raw bundle signature verifies against the pinned public key", verified)
# a modified tarball fails verification
tampered = open(TAR, "rb").read() + b"x"
bad = False
try:
    pub.verify(sig, tampered)
except InvalidSignature:
    bad = True
ok("a modified tarball FAILS raw signature verification", bad)

for p in (EXE, TAR):
    os.remove(p)
print(f"\n=== sign_release: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
