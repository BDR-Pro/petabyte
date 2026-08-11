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
# anti-replay: an OLDER validly-signed manifest must be REJECTED under a NEWER release tag.
# (A publisher without the signing key could otherwise re-upload an old signed exe+manifest.)
ok("a validly-signed OLD manifest is REJECTED when replayed under a newer tag",
   updater.verify_update(EXE, manifest, PUB_B64,
                         expected_asset=sr.ASSET_NAME, expected_version="9.9.9")[0] is False)
ok("the manifest is ACCEPTED when the release tag matches its signed version",
   updater.verify_update(EXE, manifest, PUB_B64,
                         expected_asset=sr.ASSET_NAME, expected_version="1.4.0")[0] is True)
ok("a manifest for a DIFFERENT asset is REJECTED",
   updater.verify_update(EXE, manifest, PUB_B64,
                         expected_asset="Evil.exe", expected_version="1.4.0")[0] is False)
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

# ---- pin_pubkey.py: the release workflow bakes the PUBLIC key into the exe before build ----
# Prove the pin step is real: rewriting updater's _PINNED_RELEASE_PUBKEY makes the shipped
# verifier trust a manifest signed by the matching private key (and only that key).
import importlib  # noqa: E402
import pin_pubkey as pk  # noqa: E402 — desktop-app is on sys.path

_orig = open(pk.UPDATER, encoding="utf-8").read()
try:
    # unset env -> non-breaking no-op (build still succeeds, auto-update fail-closed)
    os.environ.pop("PETABYTE_RELEASE_PUBKEY", None)
    ok("pin_pubkey is a no-op (exit 0) when the pubkey env is unset", pk.main() == 0)
    ok("pin_pubkey leaves the pin empty when unset", '_PINNED_RELEASE_PUBKEY = ""' in open(pk.UPDATER).read())

    # invalid pubkey -> fail the build loudly (a bad pin is worse than none)
    os.environ["PETABYTE_RELEASE_PUBKEY"] = "not-base64!!"
    ok("pin_pubkey FAILS (exit 1) on an invalid pubkey", pk.main() == 1)

    # valid pubkey -> pinned, and updater now verifies a manifest signed by the matching key
    os.environ["PETABYTE_RELEASE_PUBKEY"] = PUB_B64
    ok("pin_pubkey succeeds with a valid pubkey", pk.main() == 0)
    ok("updater.py now carries the pinned key", f'_PINNED_RELEASE_PUBKEY = "{PUB_B64}"' in open(pk.UPDATER).read())
    importlib.reload(updater)
    os.environ.pop("PETABYTE_RELEASE_PUBKEY", None)   # prove the SOURCE pin works, not the env
    ok("the pinned SOURCE value is what the updater reads", updater._pinned_pubkey() == PUB_B64)
    _fd, EXE2 = tempfile.mkstemp(suffix=".exe"); os.write(_fd, b"EXE" + os.urandom(1024)); os.close(_fd)
    m2 = sr.build_manifest(EXE2, "2.0.0", key)
    ok("the pinned build verifies a manifest signed by the release key (no explicit pubkey arg)",
       updater.verify_update(EXE2, m2, updater._pinned_pubkey())[0] is True)
    os.remove(EXE2)
finally:
    open(pk.UPDATER, "w", encoding="utf-8").write(_orig)   # restore the source file
    os.environ.pop("PETABYTE_RELEASE_PUBKEY", None)
    importlib.reload(updater)

for p in (EXE, TAR):
    os.remove(p)
print(f"\n=== sign_release: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
