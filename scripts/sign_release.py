"""sign_release.py — sign a Petabyte agent release so the auto-updaters will accept it.

The updaters apply an update ONLY when it is signed by the pinned release key
(desktop-app/updater.py verify_update; lumaris_agent/update.sh verify_bundle). This is the
PRODUCER side: run it in the release pipeline with the offline release private key.

It produces, for one release:
  * Windows:  PetabyteAgent.exe.manifest.json  — {asset, version, sha256, sig} where sig is
              Ed25519 over the canonical {asset,version,sha256}. Matches updater.verify_update.
  * Linux:    agent.tar.gz.sig                  — raw Ed25519 over the tarball bytes. Matches
              `openssl pkeyutl -verify -pubin -rawin` in update.sh.

And prints the PUBLIC key in both encodings to pin:
  * base64 raw   -> desktop-app/updater.py _PINNED_RELEASE_PUBKEY (or PETABYTE_RELEASE_PUBKEY)
  * PEM          -> /etc/petabyte/release_ed25519.pub on seller nodes (shipped in the installer)

The PRIVATE key never leaves the signer. Usage:
  python scripts/sign_release.py --key release_ed25519.pem --version 1.2.3 \\
      --exe dist/PetabyteAgent.exe --tarball dist/agent.tar.gz --out-dir dist
  python scripts/sign_release.py --gen-key release_ed25519.pem   # one-time: create a key
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

MANIFEST_CORE = ("asset", "version", "sha256")
ASSET_NAME = "PetabyteAgent.exe"


def canonical(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_private_key(path: str) -> Ed25519PrivateKey:
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("release key must be Ed25519")
    return key


def gen_private_key(path: str) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return key


def pub_b64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()


def pub_pem(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def build_manifest(exe_path: str, version: str, key: Ed25519PrivateKey) -> dict:
    """The Windows signed manifest (verified by desktop-app/updater.verify_update)."""
    core = {"asset": ASSET_NAME, "version": str(version), "sha256": sha256_file(exe_path)}
    manifest = dict(core)
    manifest["sig"] = base64.b64encode(key.sign(canonical(core))).decode()
    return manifest


def sign_bundle_raw(tar_path: str, key: Ed25519PrivateKey) -> bytes:
    """Raw Ed25519 over the tarball bytes (verified by update.sh openssl -rawin)."""
    with open(tar_path, "rb") as f:
        return key.sign(f.read())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen-key", metavar="PATH", help="generate a new Ed25519 key (0600) and exit")
    ap.add_argument("--key", help="release private key (PEM)")
    ap.add_argument("--version", help="release version, e.g. 1.2.3")
    ap.add_argument("--exe", help="path to PetabyteAgent.exe (Windows)")
    ap.add_argument("--tarball", help="path to agent.tar.gz (Linux)")
    ap.add_argument("--out-dir", default=".", help="where to write manifest/sig")
    args = ap.parse_args(argv)

    if args.gen_key:
        key = gen_private_key(args.gen_key)
        print(f"wrote private key -> {args.gen_key} (0600) — keep it OFFLINE")
        print("pin this PUBLIC key:")
        print("  updater.py _PINNED_RELEASE_PUBKEY =", repr(pub_b64(key)))
        print("  /etc/petabyte/release_ed25519.pub (PEM):\n" + pub_pem(key))
        return 0

    if not args.key or not args.version:
        ap.error("--key and --version are required (or use --gen-key)")
    key = load_private_key(args.key)
    os.makedirs(args.out_dir, exist_ok=True)

    if args.exe:
        manifest = build_manifest(args.exe, args.version, key)
        out = os.path.join(args.out_dir, ASSET_NAME + ".manifest.json")
        with open(out, "w") as f:
            json.dump(manifest, f, sort_keys=True)
        print(f"wrote {out} (sha256={manifest['sha256'][:16]}…)")
    if args.tarball:
        sig = sign_bundle_raw(args.tarball, key)
        out = os.path.join(args.out_dir, os.path.basename(args.tarball) + ".sig")
        with open(out, "wb") as f:
            f.write(sig)
        print(f"wrote {out} ({len(sig)} bytes)")
    if not args.exe and not args.tarball:
        ap.error("nothing to sign — pass --exe and/or --tarball")

    print("\nPUBLIC key to pin (base64 raw):", pub_b64(key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
