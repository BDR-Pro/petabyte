"""updater_test.py — the desktop agent applies SIGNED updates only (fleet-RCE guard).

verify_update() is the security boundary: an update is applied ONLY when the downloaded exe's
SHA-256 matches a manifest that is Ed25519-signed by the PINNED release key. This proves it
fails CLOSED for every tampering vector (wrong file, wrong key, missing/forged signature, no
pinned key) and accepts a genuinely-signed release.

No network, no Windows, no GPU: verify_update is a pure function. Run: python updater_test.py
"""
import base64
import hashlib
import json
import os
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import updater

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# release signer: the private key stays offline; only the public key is pinned into the build.
_key = Ed25519PrivateKey.generate()
PUB = base64.b64encode(_key.public_key().public_bytes_raw()).decode()
OTHER_PUB = base64.b64encode(
    Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode()

# a fake "release exe"
_fd, EXE = tempfile.mkstemp(suffix=".exe")
os.write(_fd, b"PETABYTE-AGENT-BINARY-" + os.urandom(4096))
os.close(_fd)
SHA = hashlib.sha256(open(EXE, "rb").read()).hexdigest()


def signed_manifest(sha=SHA, version="1.2.3", asset="PetabyteAgent.exe", key=_key):
    core = {"asset": asset, "version": version, "sha256": sha}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    m = dict(core)
    m["sig"] = base64.b64encode(key.sign(blob)).decode()
    return m


# ---- happy path: correctly-signed manifest for the exact file verifies ----
ok("a correctly-signed release verifies", updater.verify_update(EXE, signed_manifest(), PUB)[0] is True)

# ---- fail closed: no pinned key -> refuse (this is the "unsigned update" default) ----
ok("no pinned public key -> REFUSED", updater.verify_update(EXE, signed_manifest(), "")[0] is False)

# ---- tampered binary: manifest signed for a different digest -> refuse ----
bad_sha = hashlib.sha256(b"totally different bytes").hexdigest()
ok("sha256 mismatch (swapped binary) -> REFUSED",
   updater.verify_update(EXE, signed_manifest(sha=bad_sha), PUB)[0] is False)

# ---- attacker signs a valid-looking manifest with THEIR key -> refuse against pinned key ----
ok("manifest signed by a NON-pinned key -> REFUSED",
   updater.verify_update(EXE, signed_manifest(key=Ed25519PrivateKey.generate()), PUB)[0] is False)
ok("correct signer but verified against the WRONG pinned key -> REFUSED",
   updater.verify_update(EXE, signed_manifest(), OTHER_PUB)[0] is False)

# ---- forged/stripped signature -> refuse ----
m = signed_manifest(); m["sig"] = base64.b64encode(b"not a real signature").decode()
ok("garbage signature -> REFUSED", updater.verify_update(EXE, m, PUB)[0] is False)
m2 = signed_manifest(); del m2["sig"]
ok("manifest with no signature -> REFUSED", updater.verify_update(EXE, m2, PUB)[0] is False)

# ---- missing required fields -> refuse ----
m3 = signed_manifest(); del m3["sha256"]
ok("manifest missing sha256 -> REFUSED", updater.verify_update(EXE, m3, PUB)[0] is False)

# ---- a signature that's valid over DIFFERENT core fields can't be replayed (version bump) ----
m4 = signed_manifest(version="1.2.3"); m4["version"] = "9.9.9"   # tamper a signed field
ok("tampering a signed field (version) invalidates the signature -> REFUSED",
   updater.verify_update(EXE, m4, PUB)[0] is False)

# ---- private-repo-safe update source: PETABYTE_UPDATE_URL bypasses the GitHub API ----
# A private source repo makes the default api.github.com release lookup 404 for anonymous agents.
# With PETABYTE_UPDATE_URL set, _latest() must read a domain-hosted release JSON and NOT touch
# GitHub — so going private never silently kills desktop auto-update. (Signature verification is
# unchanged and already covered above, so the transport swap can't weaken integrity.)
import urllib.request as _urlreq


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, *a):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_captured = {}


def _fake_urlopen(req, timeout=None):
    _captured["url"] = getattr(req, "full_url", req)
    return _FakeResp({"tag": "v9.9.9",
                      "exe_url": "https://petabyte.market/dl/PetabyteAgent.exe",
                      "manifest_url": "https://petabyte.market/dl/PetabyteAgent.exe.manifest.json"})


_orig_urlopen = _urlreq.urlopen
_urlreq.urlopen = _fake_urlopen
try:
    os.environ["PETABYTE_UPDATE_URL"] = "https://petabyte.market/desktop/latest.json"
    _tag, _exe, _man = updater._latest()
    ok("PETABYTE_UPDATE_URL: _latest reads the domain-hosted release JSON (private-repo safe)",
       _tag == "v9.9.9" and _exe.endswith("PetabyteAgent.exe") and _man.endswith(".manifest.json"))
    ok("PETABYTE_UPDATE_URL: the GitHub API is NOT contacted (domain source wins)",
       _captured.get("url") == "https://petabyte.market/desktop/latest.json")
finally:
    _urlreq.urlopen = _orig_urlopen
    os.environ.pop("PETABYTE_UPDATE_URL", None)


os.remove(EXE)
print(f"\n=== updater: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
