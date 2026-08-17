"""Offline tests for admin-uploadable desktop releases (/admin/desktop/release + serving).

Proves the "make it easy for an admin to publish a new Windows build" flow is safe:
  * only a platform admin can publish (unauth -> 401, non-admin -> 403);
  * the server refuses a build whose bytes don't match its signed manifest, and — when a release
    public key is configured — whose signature doesn't verify (so a bad/unsigned build is never
    served); it NEVER signs anything itself;
  * a valid upload is served immediately at /download/windows, /desktop/latest.json and the
    manifest URL — the private-safe, no-GitHub path.

No network. Run: python desktop_release_test.py
"""
import os
import json
import base64
import hashlib

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./desktop_release.db")
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_test"
os.environ["NOTIFY_STUB"] = "true"
os.environ["ADMIN_USERS"] = "deskadmin"                # platform admin used below

# A release keypair: the PUBLIC half is configured on the server (defense-in-depth signature
# check); the PRIVATE half stays here, standing in for the offline signer.
_rk = Ed25519PrivateKey.generate()
_PUB_B64 = base64.b64encode(_rk.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
os.environ["PETABYTE_RELEASE_PUBKEY"] = _PUB_B64

for _f in ("desktop_release.db", "desktop_release.db-wal", "desktop_release.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)

import shutil  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import db as dbmod  # noqa: E402
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()
import main  # noqa: E402

# start from a clean release dir so serving assertions reflect only what this test publishes
shutil.rmtree(main._desktop_release_dir(), ignore_errors=True)

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _reg_login(u):
    c.post("/register_user", json={"username": u, "password": "hunter2-correct-horse"})
    r = c.post("/login", data={"username": u, "password": "hunter2-correct-horse"})
    c.cookies.clear()   # Bearer-based suite; drop the ambient cookie so no-auth checks stay honest
    return r.json()["access_token"]


admin_h = {"Authorization": f"Bearer {_reg_login('deskadmin')}"}
user_h = {"Authorization": f"Bearer {_reg_login('regular')}"}


def _signed_manifest(exe_bytes, version="1.4.0", sha=None):
    core = {"asset": "PetabyteAgent.exe", "version": version,
            "sha256": sha or hashlib.sha256(exe_bytes).hexdigest()}
    canon = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    m = dict(core)
    m["sig"] = base64.b64encode(_rk.sign(canon)).decode()
    return m


def _upload(headers, exe_bytes, manifest_dict):
    return c.post("/admin/desktop/release", headers=headers, files={
        "exe": ("PetabyteAgent.exe", exe_bytes, "application/octet-stream"),
        "manifest": ("PetabyteAgent.exe.manifest.json",
                     json.dumps(manifest_dict).encode(), "application/json"),
    })


EXE = b"MZ" + b"\x00" * 4094   # a stand-in "exe" blob (content is irrelevant; the hash binds it)

# ---- gating: only a platform admin may publish ----
ok("no auth -> 401 (cannot publish a build unauthenticated)",
   _upload({}, EXE, _signed_manifest(EXE)).status_code == 401)
ok("a non-admin user -> 403 (publishing is admin-only)",
   _upload(user_h, EXE, _signed_manifest(EXE)).status_code == 403)

# ---- nothing published yet -> honest empty state, never a dead link ----
ok("before any publish, /desktop/latest.json is 404 (no release yet)",
   c.get("/desktop/latest.json").status_code == 404)

# ---- integrity: a build whose bytes don't match its manifest is refused ----
_bad_sha = _signed_manifest(EXE, sha="0" * 64)   # signed, but wrong digest
ok("admin upload with a sha256 that doesn't match the .exe -> 400 (mismatched pair refused)",
   _upload(admin_h, EXE, _bad_sha).status_code == 400)

# ---- signature: a tampered manifest is refused (release pubkey configured) ----
_tampered = _signed_manifest(EXE)
_tampered["sig"] = base64.b64encode(b"\x00" * 64).decode()
ok("admin upload whose signature doesn't verify -> 400 (bad/unsigned build never served)",
   _upload(admin_h, EXE, _tampered).status_code == 400)

# still nothing served after the rejected uploads
ok("a rejected upload publishes nothing (/download/windows still not serving a file)",
   "early access" in c.get("/download/windows").text.lower())

# ---- happy path: a valid signed build publishes and is served immediately ----
_r = _upload(admin_h, EXE, _signed_manifest(EXE, version="1.4.0"))
ok("admin upload of a valid signed build -> 200 published", _r.status_code == 200)
ok("publish response reports the version + byte count",
   _r.json().get("version") == "1.4.0" and _r.json().get("bytes") == len(EXE))

_dl = c.get("/download/windows")
ok("/download/windows now serves the exact uploaded bytes (new installs get the app)",
   _dl.status_code == 200 and _dl.content == EXE)

_lat = c.get("/desktop/latest.json")
ok("/desktop/latest.json serves the release metadata (existing agents auto-update from here)",
   _lat.status_code == 200 and _lat.json().get("version") == "1.4.0"
   and _lat.json().get("manifest_url", "").endswith(".manifest.json"))

_man = c.get("/download/PetabyteAgent.exe.manifest.json")
ok("the signed manifest is served for the updater to verify before applying",
   _man.status_code == 200 and _man.json().get("sig") and _man.json().get("sha256")
   == hashlib.sha256(EXE).hexdigest())

# ---- a second publish replaces the current release (rollout of a new version) ----
EXE2 = b"MZ" + b"\x11" * 8190
_r2 = _upload(admin_h, EXE2, _signed_manifest(EXE2, version="1.5.0"))
ok("a newer signed build replaces the current release",
   _r2.status_code == 200 and c.get("/desktop/latest.json").json().get("version") == "1.5.0"
   and c.get("/download/windows").content == EXE2)

# ---- the admin upload page renders (the browser form) ----
_pg = c.get("/admin/desktop")
ok("the admin publish page renders a browser upload form",
   _pg.status_code == 200 and "/admin/desktop/release" in _pg.text and "Publish" in _pg.text)

shutil.rmtree(main._desktop_release_dir(), ignore_errors=True)   # leave no artifacts behind
print(f"\n=== desktop_release: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
