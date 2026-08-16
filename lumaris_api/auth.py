from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import hashlib
import hmac
import os
import secrets
import uuid

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
# Session lifetime is configurable (shorter = smaller stolen-token window); default 7 days.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))

# Browser session cookies (the JWT lives here, NOT in localStorage, so an XSS payload can't
# read the token). SESSION_COOKIE is HttpOnly; CSRF_COOKIE is readable by JS and doubles as
# the client-side "am I signed in?" hint. Bearer auth (CLI/API) is unaffected by all of this.
SESSION_COOKIE = "pb_session"
CSRF_COOKIE = "pb_csrf"
SESSION_MAX_AGE = ACCESS_TOKEN_EXPIRE_MINUTES * 60   # cookie lifetime == token lifetime

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")
# HS256 is symmetric: a weak secret means forgeable tokens. Enforce real entropy in production;
# dev/test may use short throwaway keys.
if len(SECRET_KEY) < 32 and os.getenv("ENVIRONMENT", "").strip().lower() == "production":
    raise RuntimeError("SECRET_KEY must be at least 32 characters in production "
                       "(HS256 is symmetric — a weak secret is forgeable)")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Generate a JWT with standard, revocation-ready claims: `exp` (expiry), `iat` (issued-at),
    and a unique `jti` so a specific token can be revoked (logout / compromise) via the jti
    denylist — mirroring the API-key model."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now, "jti": uuid.uuid4().hex})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and verify a JWT (signature + expiry; HS256 pinned so no alg-confusion).
    Raises ValueError on any failure. Revocation (jti denylist) is checked by the caller
    against the DB, mirroring the API-key path."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise ValueError("Invalid token") from e


# ------------------ Signed double-submit CSRF token ------------------
# OWASP "signed double-submit": the CSRF value is HMAC-bound to the server secret, so an attacker
# who can only WRITE the victim's cookie (subdomain/MITM) still can't mint a token that verifies —
# strictly stronger than the naive random double-submit.
def make_csrf_token() -> str:
    raw = secrets.token_urlsafe(32)
    sig = hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def csrf_token_valid(token: str) -> bool:
    if not token or "." not in token:
        return False
    raw, _, sig = token.rpartition(".")
    expected = hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)
