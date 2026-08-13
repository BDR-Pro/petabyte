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
from fastapi import Depends, HTTPException, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from db import get_db, get_user_by_username, is_jti_revoked
from auth import verify_token
from utils import decode_api_key

# Re-exported so importers can do `from deps import get_db` alongside the auth deps.
__all__ = ["oauth2_scheme", "get_current_user", "_username", "api_key_user", "get_db"]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Resolve the JWT bearer token to its claims, or 401."""
    try:
        return verify_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


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
