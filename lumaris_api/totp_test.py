"""totp_test.py — hermetic unit tests for the hand-rolled RFC 6238 TOTP module.

Proves correctness against the official RFC 4226 HOTP known-answer vectors (so the HMAC/dynamic-
truncation math is exactly right), plus the TOTP window/skew behavior, secret generation, and the
otpauth provisioning URI. Pure stdlib, no server needed.
"""
import sys
import base64
import totp

fail = 0


def ok(name, cond):
    global fail
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fail += 1


# --- RFC 4226 Appendix D known-answer vectors: secret = ASCII "12345678901234567890" ---
_RFC_SECRET_B32 = base64.b32encode(b"12345678901234567890").decode()
_RFC_HOTP = ["755224", "287082", "359152", "969429", "338314",
             "254676", "287922", "162583", "399871", "520489"]
ok("base32 of the RFC secret is the expected value",
   _RFC_SECRET_B32 == "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")
ok("HOTP matches all 10 RFC 4226 known-answer vectors",
   all(totp.hotp(_RFC_SECRET_B32, i) == _RFC_HOTP[i] for i in range(10)))

# --- TOTP is a HOTP over the time step: same secret + same step -> same code ---
sec = totp.random_base32()
ok("random_base32 has the requested length and a valid alphabet",
   len(totp.random_base32(32)) == 32 and set(totp.random_base32()) <= set(totp._B32_ALPHABET))
ok("two fresh secrets differ", totp.random_base32() != totp.random_base32())

t = 1_700_000_000  # fixed instant so the test never depends on the wall clock
code = totp.totp(sec, at=t)
ok("totp is deterministic for a fixed time", code == totp.totp(sec, at=t) and len(code) == 6)

# --- verify: accepts the current step and ±1 step (skew), rejects beyond the window ---
ok("verify accepts the current code", totp.verify(sec, code, at=t))
ok("verify accepts a code one step early (clock skew)", totp.verify(sec, totp.totp(sec, at=t - 30), at=t))
ok("verify accepts a code one step late (clock skew)", totp.verify(sec, totp.totp(sec, at=t + 30), at=t))
ok("verify rejects a code two steps away (outside the window)",
   not totp.verify(sec, totp.totp(sec, at=t - 90), at=t))
ok("verify rejects a wrong code", not totp.verify(sec, "000000", at=t) or code == "000000")
ok("verify rejects a non-6-digit code", not totp.verify(sec, "12345", at=t))
ok("verify tolerates spaces in the entered code",
   totp.verify(sec, code[:3] + " " + code[3:], at=t))

# --- provisioning URI (what the authenticator app imports) ---
uri = totp.provisioning_uri(sec, "alice@example.com", issuer="Petabyte")
ok("provisioning URI is a well-formed otpauth TOTP URI",
   uri.startswith("otpauth://totp/") and f"secret={sec}" in uri and "issuer=Petabyte" in uri)

print("\n=== totp: " + ("0 failures ===" if fail == 0 else f"{fail} FAILED ==="))
sys.exit(1 if fail else 0)
