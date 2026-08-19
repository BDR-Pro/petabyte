"""deps.py — shared FastAPI dependencies (authentication + DB session).

Lifted out of main.py so DOMAIN ROUTERS can depend on auth and the DB session without
importing main (which would be a circular import). This is the enabler for the staged
monolith split: web_routes.py (static pages) needed none of these; the trust, compute, and
payment routers do. None of the modules imported here import main, so there is no cycle:

    deps  ->  db (get_db, user lookup, key revocation) · auth (JWT) · utils (API-key decode)

Behaviour is identical to the definitions that used to live in main.py — main now imports
these same objects, so every `Depends(get_current_user)` / `Depends(api_key_user)` across the
app resolves to exactly the same callable.
"""
import secrets as _secrets

from fastapi import Depends, HTTPException, Header, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from db import get_db, get_user_by_username, is_jti_revoked
from auth import verify_token, csrf_token_valid, SESSION_COOKIE, CSRF_COOKIE
from utils import decode_api_key

# Re-exported so importers can do `from deps import get_db` alongside the auth deps.
__all__ = ["oauth2_scheme", "get_current_user", "_username", "api_key_user", "get_db",
           "enforce_csrf"]

# auto_error=False: a missing Authorization header is NOT an automatic 401 anymore — we fall
# back to the HttpOnly session cookie (browsers) before deciding. Bearer callers are unchanged.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def enforce_csrf(request: Request) -> None:
    """Double-submit CSRF check for a request authenticated by the AMBIENT session cookie.

    Call this ONLY when the caller was authenticated via the cookie (not a Bearer/API key) —
    Bearer/API-key callers carry no ambient authority the browser attaches automatically, so
    they are never CSRF targets. On an unsafe method the readable `pb_csrf` cookie must equal
    the `X-CSRF-Token` request header. Because this lives in the AUTH dependency, it applies
    exactly to session-protected endpoints and never to public/webhook routes."""
    if request.method not in _UNSAFE_METHODS:
        return
    sent = request.headers.get("X-CSRF-Token", "")
    tok = request.cookies.get(CSRF_COOKIE, "")
    # Double-submit: cookie must equal header; AND the token must carry a valid server HMAC
    # (signed double-submit) so an attacker who can only write the cookie can't forge a pair.
    # Compare BYTES: compare_digest raises TypeError on non-ASCII str (headers are
    # latin-1-decoded, so a client can send 0x80-0xFF bytes) — that must be a 403, not a 500.
    if not (sent and tok
            and _secrets.compare_digest(sent.encode("utf-8", "surrogateescape"),
                                        tok.encode("utf-8", "surrogateescape"))
            and csrf_token_valid(tok)):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


async def get_current_user(request: Request,
                           token: str = Depends(oauth2_scheme),
                           db: Session = Depends(get_db)) -> dict:
    """Resolve the caller's JWT to its claims, or 401. The token comes from EITHER the
    Authorization: Bearer header (CLI / API clients) OR the HttpOnly `pb_session` cookie
    (browsers — the token is never exposed to JS). When auth comes from the ambient cookie,
    an unsafe method is additionally CSRF-checked (double-submit); Bearer auth is not.

    A token whose `jti` is on the revocation denylist (logout / compromise) is rejected even
    if it's still within its expiry window — so logout is real, not just a cookie delete."""
    raw = token or request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = verify_token(raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    jti = claims.get("jti")
    if jti and is_jti_revoked(db, jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")
    if not token:                 # authenticated via the ambient cookie -> CSRF applies
        enforce_csrf(request)
    return claims


def _username(user: dict) -> str:
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Malformed token")
    return sub


def api_key_user(x_api_key: str = Header(..., alias="X-API-KEY"),
                 db: Session = Depends(get_db)):
    """Authenticate an unattended agent via X-API-KEY (honors revocation)."""
    try:
        data = decode_api_key(x_api_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if is_jti_revoked(db, data["jti"]):
        raise HTTPException(status_code=401, detail="Key revoked")
    user = get_user_by_username(db, data["u"])
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    user._scopes = data.get("scopes", []) or []
    user._is_api_key = True          # scopes are an API-KEY concept, not a session one
    return user
