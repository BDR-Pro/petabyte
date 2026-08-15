from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import os

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Browser session cookies (the JWT lives here, NOT in localStorage, so an XSS payload can't
# read the token). SESSION_COOKIE is HttpOnly; CSRF_COOKIE is readable by JS and doubles as
# the client-side "am I signed in?" hint. Bearer auth (CLI/API) is unaffected by all of this.
SESSION_COOKIE = "pb_session"
CSRF_COOKIE = "pb_csrf"
SESSION_MAX_AGE = ACCESS_TOKEN_EXPIRE_MINUTES * 60   # cookie lifetime == token lifetime

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Generate a JWT with a UTC-aware expiry claim."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and verify a JWT. Raises ValueError on any failure."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise ValueError("Invalid token") from e
