"""Agent signing identity (Ed25519).

The SAME key is used to (a) attest the node at POST /prove and (b) sign every
job result. The API verifies result signatures against the pubkey registered at
attestation, binding results to this node's hardware.
"""
import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_PATH = os.getenv("PETABYTE_AGENT_KEY",
                     os.path.expanduser("~/.petabyte/agent_ed25519.key"))


def load_or_create_key() -> Ed25519PrivateKey:
    if os.path.exists(KEY_PATH):
        raw = base64.b64decode(open(KEY_PATH).read().strip())
        return Ed25519PrivateKey.from_private_bytes(raw)
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    key = Ed25519PrivateKey.generate()
    with open(KEY_PATH, "w") as f:
        f.write(base64.b64encode(key.private_bytes_raw()).decode())
    os.chmod(KEY_PATH, 0o600)
    return key


def public_key_b64() -> str:
    return base64.b64encode(load_or_create_key().public_key().public_bytes_raw()).decode()


def sign_proof(proof: dict) -> str:
    key = load_or_create_key()
    msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(key.sign(msg)).decode()


def sha256_hex(data) -> str:
    if not isinstance(data, (bytes, bytearray)):
        data = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def compute_test_hash(size: int, seed: int) -> str:
    """MUST match the server's db.compute_test_hash exactly (integer-deterministic)."""
    MOD = (1 << 61) - 1
    a = (seed % MOD) or 1
    acc = 0
    for i in range(size):
        a = (a * 6364136223846793005 + 1442695040888963407) % MOD
        acc = (acc + a * (i + 1)) % MOD
    return hashlib.sha256(str(acc).encode()).hexdigest()
