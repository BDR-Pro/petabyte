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
import logging
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

load_dotenv()

_log = logging.getLogger("petabyte.utils")


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
    # TODO(stub): WG_APPLY no-op unless enabled — real WireGuard apply needs wg on PATH (stub.md #10)
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


def _tee_require_hardware() -> bool:
    """True where the SOFTWARE STUB verifier must be refused and a real vendor TEE
    verifier is required: production, or an explicit opt-in (TEE_REQUIRE_HARDWARE=true).

    This is the honesty gate for confidential computing. The stub proves possession of a
    signing key, NOT that a job runs in an enclave the host cannot inspect. Letting the stub
    mint `confidential=True` in production would tell buyers their workload is hidden from the
    seller when it is not. So in production, attestation FAILS CLOSED until a real verifier
    (NVIDIA NRAS / AMD SEV-SNP / Intel TDX) is configured — no fake confidential badges."""
    if os.getenv("TEE_REQUIRE_HARDWARE", "").strip().lower() == "true":
        return True
    return os.getenv("ENVIRONMENT", "").strip().lower() == "production"


def _resolve_tee_verifier():
    """Pick the configured TEE verifier (TEE_VERIFIER, default 'stub'). Real vendor verifiers
    register in the map below. Refuses the software stub wherever hardware is required."""
    verifiers = {"stub": _verify_stub}   # real verifiers plug in here: nvidia-nras/sev-snp/tdx
    name = os.getenv("TEE_VERIFIER", "stub").strip().lower()
    v = verifiers.get(name)
    if v is None:
        raise ValueError(f"unknown TEE verifier '{name}' (set TEE_VERIFIER)")
    if v is _verify_stub and _tee_require_hardware():
        raise ValueError(
            "hardware TEE verification is required here (production, or "
            "TEE_REQUIRE_HARDWARE=true) but only the software stub is configured — refusing "
            "to mint a confidential attestation. Configure a real vendor verifier "
            "(NVIDIA NRAS / AMD SEV-SNP / Intel TDX).")
    return v


def verify_tee_report(report: dict, signature_b64: str, expected_nonce: str,
                      max_age_s: int = 600) -> str:
    """Verify a TEE attestation report. Returns the attested measurement.

    Checks: a real-verifier requirement (fail closed in production on the stub), nonce
    binding (report must carry the server-issued nonce), freshness, measurement allowlist,
    and the enclave/vendor signature. Raises ValueError on any failure.
    """
    verifier = _resolve_tee_verifier()          # fail closed FIRST if hardware is required
    if report.get("nonce") != expected_nonce:
        raise ValueError("attestation nonce mismatch")
    ts = int(report.get("ts", 0))
    if abs(int(time.time()) - ts) > max_age_s:
        raise ValueError("attestation report expired")
    measurement = report.get("measurement", "")
    if not tee_measurement_allowed(measurement):
        raise ValueError("enclave measurement not in allowlist")
    verifier(report, signature_b64)
    return measurement


# TODO(stub): software (Ed25519) attestation only — replace with real TEE verification (SEV-SNP/TDX), stub.md #9
def _verify_stub(report: dict, signature_b64: str) -> None:
    """STUB vendor-root signature check (Ed25519). Replace with the real
    vendor verifier (NVIDIA NRAS JWT / AMD VCEK chain / Intel DCAP)."""
    root = os.getenv("TEE_TRUSTED_ROOT", "")
    if not root:
        raise ValueError("no TEE trusted root configured (TEE_TRUSTED_ROOT)")
    msg = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    _ed25519_verify(root, msg, signature_b64)


# ------------------ IP geolocation (region verification) ------------------

_GEOIP_READER = None            # cached MaxMind reader (opened once per db_path)
_GEOIP_READER_PATH = None
_GEOIP_IMPORT_WARNED = False


def _geoip_reader(db_path: str):
    """Open the MaxMind reader once and reuse it (opening the ~mmdb per lookup is wasteful).
    Reopens only if GEOIP_DB changes. Returns None (logged, once) if geoip2 isn't installed
    or the DB can't be opened — so a real misconfig is visible, not silently swallowed."""
    global _GEOIP_READER, _GEOIP_READER_PATH, _GEOIP_IMPORT_WARNED
    if _GEOIP_READER is not None and _GEOIP_READER_PATH == db_path:
        return _GEOIP_READER
    try:
        import geoip2.database
    except ImportError:
        if not _GEOIP_IMPORT_WARNED:
            _log.warning("GEOIP_DB is set but the 'geoip2' package is not installed — "
                         "residency verification is disabled. Add geoip2 to requirements.")
            _GEOIP_IMPORT_WARNED = True
        return None
    try:
        if _GEOIP_READER is not None:
            _GEOIP_READER.close()
        _GEOIP_READER = geoip2.database.Reader(db_path)
        _GEOIP_READER_PATH = db_path
        return _GEOIP_READER
    except Exception:
        _log.warning("could not open GEOIP_DB at %s — residency verification disabled", db_path)
        _GEOIP_READER = None
        _GEOIP_READER_PATH = None
        return None


def geolocate_country(ip: str):
    """Return the ISO country for an IP, or None if unknown.

    Resolution order:
      1. GEOIP_STUB env (JSON ip->country) — for tests / manual mapping.
      2. GEOIP_DB env -> MaxMind GeoLite2-Country.mmdb via the geoip2 package (reader cached).
      3. None (unknown) — caller treats region as unverified.

    Point GEOIP_DB at a MaxMind GeoLite2-Country.mmdb (free account) for real lookups. VPN/proxy
    IPs can still spoof this; hard residency needs provider/TEE-attested datacenter location.
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
        reader = _geoip_reader(db_path)
        if reader is None:
            return None
        try:
            return reader.country(ip).country.iso_code
        except Exception:
            return None            # address not in the DB / not a public IP
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
    # TODO(stub): S3 stub branch — real presign runs when S3_STUB unset + creds (stub.md #6)
    if os.getenv("S3_STUB", "").lower() == "true":
        return f"https://{bucket}.s3.stub.local/{key}?op=put&exp={expires}&sig=stub"
    params = {"Bucket": bucket, "Key": key}
    # AES256 works on AWS S3 AND DigitalOcean Spaces; "aws:kms" is AWS-only; "" disables.
    sse = os.getenv("S3_SSE", "AES256")
    if sse:
        params["ServerSideEncryption"] = sse
    return _s3_client().generate_presigned_url(
        "put_object", Params=params, ExpiresIn=expires)


def mint_presigned_get(key: str, expires: int = 900) -> str:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise ValueError("S3_BUCKET not configured")
    # TODO(stub): S3 stub branch — real presign runs when S3_STUB unset + creds (stub.md #6)
    if os.getenv("S3_STUB", "").lower() == "true":
        return f"https://{bucket}.s3.stub.local/{key}?op=get&exp={expires}&sig=stub"
    return _s3_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)


# ------------------ Direct object I/O (server-held creds) ------------------
#
# Presigned URLs above are for NODES (which hold no creds). These helpers are for the API
# itself, which DOES hold the object-storage credentials — used by the platform database
# backup subsystem (backup.py) to write/read/list/delete dump objects directly. The S3_STUB
# branch writes to a local directory so tests and offline development need no AWS.

def _s3_stub_root(bucket: str) -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "petabyte-s3-stub", bucket)


def _require_bucket() -> str:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        raise ValueError("S3_BUCKET not configured")
    return bucket


def _s3_stub() -> bool:
    return os.getenv("S3_STUB", "").lower() == "true"


def s3_put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload bytes to s3://<S3_BUCKET>/<key> (server-side encrypted) and return the s3:// URI.
    S3_STUB writes to a local directory instead."""
    bucket = _require_bucket()
    if _s3_stub():
        path = os.path.join(_s3_stub_root(bucket), key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return s3_uri(key)
    extra = {"ContentType": content_type}
    sse = os.getenv("S3_SSE", "AES256")   # AES256 works on AWS S3 + DO Spaces; "" disables
    if sse:
        extra["ServerSideEncryption"] = sse
    _s3_client().put_object(Bucket=bucket, Key=key, Body=data, **extra)
    return s3_uri(key)


def s3_get_bytes(key: str) -> bytes:
    """Download the object at s3://<S3_BUCKET>/<key>. S3_STUB reads the local directory."""
    bucket = _require_bucket()
    if _s3_stub():
        with open(os.path.join(_s3_stub_root(bucket), key), "rb") as f:
            return f.read()
    return _s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def s3_exists(key: str) -> bool:
    """True if an object exists at s3://<S3_BUCKET>/<key>, without downloading it. S3_STUB checks
    the local file; real S3 uses a HEAD."""
    bucket = _require_bucket()
    if _s3_stub():
        return os.path.exists(os.path.join(_s3_stub_root(bucket), key))
    try:
        _s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 — 404/NoSuchKey -> not present
        return False


def s3_list_keys(prefix: str) -> list:
    """List object keys under a prefix. S3_STUB walks the local directory."""
    bucket = _require_bucket()
    if _s3_stub():
        root = _s3_stub_root(bucket)
        base = os.path.join(root, prefix)
        base_dir = base if os.path.isdir(base) else os.path.dirname(base)
        out = []
        for dirpath, _dirs, files in os.walk(base_dir if os.path.isdir(base_dir) else root):
            for fn in files:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                key = rel.replace(os.sep, "/")
                if key.startswith(prefix):
                    out.append(key)
        return sorted(out)
    keys, token = [], None
    client = _s3_client()
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = client.list_objects_v2(**kw)
        keys += [o["Key"] for o in resp.get("Contents", [])]
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return sorted(keys)


def s3_delete(key: str) -> None:
    """Delete the object at s3://<S3_BUCKET>/<key>. S3_STUB removes the local file."""
    bucket = _require_bucket()
    if _s3_stub():
        path = os.path.join(_s3_stub_root(bucket), key)
        if os.path.exists(path):
            os.remove(path)
        return
    _s3_client().delete_object(Bucket=bucket, Key=key)


def seal_secret(plaintext: str) -> str:
    """Encrypt a secret at rest with the server key (e.g. a per-task data key)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def open_secret(blob: str) -> str:
    return _fernet().decrypt(blob.encode()).decode()
