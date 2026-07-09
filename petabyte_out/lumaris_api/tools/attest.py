#!/usr/bin/env python3
"""Generate a signed hardware attestation body for POST /prove.

Usage:
  python tools/attest.py --spec-id 1 --cpu 16 --ram 64 --gpu H100

Keeps a stable Ed25519 key in tools/seller_ed25519.key so the same node
identity can re-attest. Prints a ready-to-send JSON body.
"""
import argparse, base64, json, os, time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_PATH = os.path.join(os.path.dirname(__file__), "seller_ed25519.key")


def load_or_create_key() -> Ed25519PrivateKey:
    if os.path.exists(KEY_PATH):
        raw = base64.b64decode(open(KEY_PATH).read().strip())
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes_raw()
    with open(KEY_PATH, "w") as f:
        f.write(base64.b64encode(raw).decode())
    os.chmod(KEY_PATH, 0o600)
    return key


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--spec-id", type=int, required=True)
    p.add_argument("--cpu", type=int, default=16)
    p.add_argument("--ram", type=int, default=64)
    p.add_argument("--gpu", default="H100")
    args = p.parse_args()

    key = load_or_create_key()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()

    attestation = {
        "cpu": args.cpu, "ram": args.ram, "gpu_model": args.gpu,
        "nonce": base64.b64encode(os.urandom(9)).decode(),
        "ts": int(time.time()),
    }
    msg = json.dumps(attestation, sort_keys=True, separators=(",", ":")).encode()
    sig = base64.b64encode(key.sign(msg)).decode()

    body = {"spec_id": args.spec_id, "attestation": attestation,
            "signature": sig, "pubkey": pub}
    print(json.dumps(body))


if __name__ == "__main__":
    main()
