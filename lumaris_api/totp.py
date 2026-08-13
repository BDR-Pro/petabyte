"""totp.py — RFC 6238 time-based one-time passwords, pure stdlib (no new dependency).

Authenticator-app 2FA (Google Authenticator, Authy, 1Password, …). We hand-roll TOTP for the
same reason the rest of the platform avoids optional deps: it is ~40 lines of hmac + base32, it
is trivially testable offline, and it adds nothing to the dependency-audit surface.

The shared secret is a base32 string; the authenticator app and the server both derive the same
6-digit code from it and the current 30-second time step. Verification allows a ±1 step window so
a small clock skew between phone and server does not lock a user out. All comparisons are
constant-time (hmac.compare_digest) to avoid leaking code-correctness via timing.
"""
import base64
import hashlib
import hmac
import os
import struct
import time

_B32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
DEFAULT_STEP = 30
DEFAULT_DIGITS = 6
DEFAULT_ISSUER = "Petabyte"


def random_base32(length: int = 32) -> str:
    """A fresh base32 secret (default 32 chars ≈ 160 bits of entropy, the RFC 4226 recommendation).
    Uses os.urandom, then maps into the base32 alphabet — no '=' padding, which authenticator apps
    dislike."""
    raw = os.urandom(length)
    return "".join(_B32_ALPHABET[b % 32] for b in raw)


def _decode_secret(secret_b32: str) -> bytes:
    s = (secret_b32 or "").strip().replace(" ", "").upper()
    s += "=" * ((8 - len(s) % 8) % 8)          # re-pad for the stdlib decoder
    return base64.b32decode(s, casefold=True)


def normalize(code) -> str:
    """Strip spaces/hyphens users copy in (e.g. '123 456')."""
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def hotp(secret_b32: str, counter: int, digits: int = DEFAULT_DIGITS) -> str:
    key = _decode_secret(secret_b32)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def totp(secret_b32: str, at: float = None, step: int = DEFAULT_STEP,
         digits: int = DEFAULT_DIGITS) -> str:
    """The current code for `secret_b32` (at unix time `at`, default now)."""
    at = time.time() if at is None else at
    return hotp(secret_b32, int(at // step), digits)


def verify(secret_b32: str, code, at: float = None, step: int = DEFAULT_STEP,
           digits: int = DEFAULT_DIGITS, window: int = 1) -> bool:
    """True iff `code` matches the secret within ±`window` time steps (clock-skew tolerance).
    Constant-time compare per candidate so a correct-prefix code can't be found by timing."""
    code = normalize(code)
    if len(code) != digits:
        return False
    at = time.time() if at is None else at
    counter = int(at // step)
    for drift in range(-window, window + 1):
        if hmac.compare_digest(code, hotp(secret_b32, counter + drift, digits)):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = DEFAULT_ISSUER,
                     digits: int = DEFAULT_DIGITS, step: int = DEFAULT_STEP) -> str:
    """The otpauth:// URI an authenticator app imports (scan as a QR, or paste). The label carries
    the issuer + account so the code shows up as 'Petabyte (alice)' in the app."""
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}")
    params = (f"secret={secret_b32}&issuer={quote(issuer)}"
              f"&algorithm=SHA1&digits={digits}&period={step}")
    return f"otpauth://totp/{label}?{params}"
