from dotenv import load_dotenv
import os
import time
import json
import base64
import uuid
import hashlib
import hmac
import shutil
import subprocess
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

load_dotenv()


def _fernet() -> Fernet:
    secret = os.getenv("SERVER_PRIVATE_KEY")
    if not secret:
        raise ValueError("SERVER_PRIVATE_KEY environment variable is not set")
    return Fernet(secret.encode())


# ------------------ WireGuard ------------------

def gen_wg_keypair() -> tuple[str, str]:
    """Generate a fresh Curve25519 keypair (base64), WireGuard-compatible."""
    priv = X25519PrivateKey.generate()
    priv_b = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_b = priv.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return base64.b64encode(priv_b).decode(), base64.b64encode(pub_b).decode()


def build_client_wg_config(client_private_key: str, address: str) -> str:
    """Build the *client* config. The server's private key is never referenced.

    The [Interface] PrivateKey belongs to the client (generated per-session and
    discarded server-side). The [Peer] PublicKey is the server's PUBLIC key.
    """
    server_pub = os.environ["WG_PUBLIC_KEY"]   # public, safe to share
    endpoint = os.environ["WG_ENDPOINT"]
    return (
        "[Interface]\n"
        f"PrivateKey = {client_private_key}\n"
        f"Address = {address}\n"
        "DNS = 1.1.1.1\n\n"
        "[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"Endpoint = {endpoint}:51820\n"
        "AllowedIPs = 0.0.0.0/0\n"
        "PersistentKeepalive = 25\n"
    )


def apply_peer_to_interface(public_key: str, address: str) -> bool:
    """Best-effort: register the client's pubkey on the live interface.

    No-op unless WG_APPLY=true and `wg` is on PATH with privileges. Returns
    True only if the peer was applied. Production should run the API with the
    capability to manage the interface, or push peers via a privileged helper.
    """
    if os.getenv("WG_APPLY", "false").lower() != "true" or not shutil.which("wg"):
        return False
    iface = os.getenv("WG_INTERFACE", "wg0")
    try:
        subprocess.run(
            ["wg", "set", iface, "peer", public_key, "allowed-ips", address],
            check=True, capture_output=True,
        )
        return True
    except Exception:
        return False


# ------------------ Encrypted API keys (with jti for revocation) ------------------

def gen_secure_api_key(username: str, days_to_expire: int,
                       scopes: list = None) -> tuple[str, str]:
    """Return (api_key, jti). Encrypted, authenticated, with optional permission
    scopes (e.g. ["node","jobs"]). Empty scopes == full access (back-compat)."""
    fernet = _fernet()
    jti = uuid.uuid4().hex
    expiry = int(time.time()) + 86400 * days_to_expire
    payload = json.dumps({"u": username, "exp": expiry, "jti": jti,
                          "scopes": scopes or []}).encode()
    return fernet.encrypt(payload).decode(), jti


def decode_api_key(api_key: str) -> dict:
    """Decrypt, authenticate, and check expiry. Returns {u, exp, jti}.

    Revocation (jti denylist) is checked by the caller against the DB.
    """
    fernet = _fernet()
    try:
        raw = fernet.decrypt(api_key.encode())
    except InvalidToken:
        raise ValueError("Invalid or tampered token")
    try:
        data = json.loads(raw.decode())
        username, expiry, jti = data["u"], int(data["exp"]), data["jti"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("Malformed token")
    if int(time.time()) > expiry:
        raise ValueError("Token expired")
    return {"u": username, "exp": expiry, "jti": jti, "scopes": data.get("scopes", [])}


# ------------------ Hardware attestation (Ed25519) ------------------

def verify_attestation(attestation: dict, signature_b64: str, pubkey_b64: str,
                       max_age_s: int = 300) -> bool:
    """Verify a seller's signed hardware attestation.

    `attestation` is a dict that must include a 'ts' (unix seconds) and a
    'nonce'. The seller's machine signs the canonical JSON with an Ed25519 key;
    we verify the signature against the supplied public key and check freshness.

    This is a real cryptographic check (proves possession of the signing key on
    a machine that reports these specs); SEV/SGX remote attestation is the next
    layer that binds the key to genuine secure hardware.
    """
    ts = int(attestation.get("ts", 0))
    if abs(int(time.time()) - ts) > max_age_s:
        raise ValueError("attestation expired or clock skew too large")
    if not attestation.get("nonce"):
        raise ValueError("attestation missing nonce")
    message = json.dumps(attestation, sort_keys=True, separators=(",", ":")).encode()
    try:
        _ed25519_verify(pubkey_b64, message, signature_b64)
    except ValueError:
        raise ValueError("attestation signature invalid")
    return True

# ------------------ Ed25519 verification (attestation + signed results) ------------------

def _ed25519_verify(pubkey_b64: str, message: bytes, signature_b64: str) -> None:
    """Raise ValueError if the signature is invalid."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        pub.verify(base64.b64decode(signature_b64), message)
    except Exception:
        raise ValueError("signature invalid")


def verify_signed_proof(pubkey_b64: str, proof: dict, signature_b64: str,
                        max_age_s: int = 600) -> bool:
    """Verify a signed proof-of-work for a job result.

    `proof` must include a unix 'ts' (replay protection) and 'output_hash'.
    Signature is checked against the node's registered attestation pubkey, which
    cryptographically binds the result to the attested hardware.
    """
    ts = int(proof.get("ts", 0))
    if abs(int(time.time()) - ts) > max_age_s:
        raise ValueError("proof expired or clock skew too large")
    if "output_hash" not in proof:
        raise ValueError("proof missing output_hash")
    msg = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    _ed25519_verify(pubkey_b64, msg, signature_b64)
    return True



# ------------------ Payment webhook signature ------------------

def verify_webhook_signature(secret: str, raw_body: bytes, signature: str) -> bool:
    """HMAC-SHA256 over the raw request body (constant-time compare).

    This is the generic pattern; for Stripe specifically, replace the call site
    with stripe.Webhook.construct_event(payload, sig_header, endpoint_secret).
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


# ------------------ TEE / confidential-computing attestation ------------------
#
# Pluggable verifier. The STUB below verifies an Ed25519-signed report against a
# configured vendor root + a measurement allowlist + a server-issued nonce. This
# is structurally identical to real remote attestation (signature chain ->
# measurement check -> nonce freshness). Swap _verify_stub for the real verifier:
#
#   NVIDIA H100 CC : verify the NRAS JWT against NVIDIA's JWKS, check GPU claims
#                    (https://nras.attestation.nvidia.com) via the nvtrust SDK.
#   AMD SEV-SNP    : verify the report's VCEK cert chain to AMD ARK/ASK, then the
#                    report signature + measurement.
#   Intel TDX      : verify the quote via Intel DCAP / a quote-verification service.

def tee_measurement_allowed(measurement: str) -> bool:
    allow = [m.strip() for m in os.getenv("TEE_MEASUREMENT_ALLOWLIST", "").split(",") if m.strip()]
    return measurement in allow if allow else False


def verify_tee_report(report: dict, signature_b64: str, expected_nonce: str,
                      max_age_s: int = 600) -> str:
    """Verify a TEE attestation report. Returns the attested measurement.

    Checks: nonce binding (report must carry the server-issued nonce), freshness,
    measurement allowlist, and the enclave/vendor signature. Raises ValueError on
    any failure.
    """
    if report.get("nonce") != expected_nonce:
        raise ValueError("attestation nonce mismatch")
    ts = int(report.get("ts", 0))
    if abs(int(time.time()) - ts) > max_age_s:
        raise ValueError("attestation report expired")
    measurement = report.get("measurement", "")
    if not tee_measurement_allowed(measurement):
        raise ValueError("enclave measurement not in allowlist")
    _verify_stub(report, signature_b64)
    return measurement


def _verify_stub(report: dict, signature_b64: str) -> None:
    """STUB vendor-root signature check (Ed25519). Replace with the real
    vendor verifier (NVIDIA NRAS JWT / AMD VCEK chain / Intel DCAP)."""
    root = os.getenv("TEE_TRUSTED_ROOT", "")
    if not root:
        raise ValueError("no TEE trusted root configured (TEE_TRUSTED_ROOT)")
    msg = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    _ed25519_verify(root, msg, signature_b64)


# ------------------ IP geolocation (region verification) ------------------

def geolocate_country(ip: str):
    """Return the ISO country for an IP, or None if unknown.

    Resolution order:
      1. GEOIP_STUB env (JSON ip->country) — for tests / manual mapping.
      2. GEOIP_DB env -> MaxMind GeoLite2-Country.mmdb via the geoip2 package.
      3. None (unknown) — caller treats region as unverified.

    For production, point GEOIP_DB at a MaxMind DB (or swap in an ipinfo/IPregistry
    API call). VPN/proxy IPs can still spoof this; hard residency needs
    provider/TEE-attested datacenter location (roadmap).
    """
    if not ip:
        return None
    stub = os.getenv("GEOIP_STUB")
    if stub:
        try:
            return json.loads(stub).get(ip)
        except Exception:
            return None
    db_path = os.getenv("GEOIP_DB")
    if db_path:
        try:
            import geoip2.database
            with geoip2.database.Reader(db_path) as reader:
                return reader.country(ip).country.iso_code
        except Exception:
            return None
    return None


# ------------------ Secure backup uploads (pre-signed URLs) ------------------
#
# The API holds the real object-storage credentials; seller nodes never do. For
# each backup the API mints a per-object, time-limited pre-signed PUT URL (and a
# GET URL for restore). The node can write/read exactly ONE key and nothing else.
# Set S3_STUB=true for tests; production uses boto3 against S3/R2/MinIO.

def s3_key_for(buyer_id: int, task_id: int, filename: str) -> str:
    base = os.path.basename(filename or "snapshot.tar")    # no path traversal
    return f"backups/{buyer_id}/{task_id}/{base}"           # per-tenant prefix isolation


def s3_uri(key: str) -> str:
    return f"s3://{os.getenv('S3_BUCKET', '')}/{key}"


def _s3_client():
    import boto3
    return boto3.client("s3", region_name=os.getenv("S3_REGION") or None,
                        endpoint_url=os.getenv("S3_ENDPOINT") or None)


def mint_presigned_put(key: str, expires: int = 900) -> str:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise ValueError("S3_BUCKET not configured")
    if os.getenv("S3_STUB", "").lower() == "true":
        return f"https://{bucket}.s3.stub.local/{key}?op=put&exp={expires}&sig=stub"
    return _s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key,
                "ServerSideEncryption": "aws:kms"},   # encrypt at rest
        ExpiresIn=expires)


def mint_presigned_get(key: str, expires: int = 900) -> str:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise ValueError("S3_BUCKET not configured")
    if os.getenv("S3_STUB", "").lower() == "true":
        return f"https://{bucket}.s3.stub.local/{key}?op=get&exp={expires}&sig=stub"
    return _s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


def seal_secret(plaintext: str) -> str:
    """Encrypt a secret at rest with the server key (e.g. a per-task data key)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def open_secret(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()
