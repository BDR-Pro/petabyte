"""Offline tests for the self-service password reset, the login-form reset link,
the Cal.com booking webhook, and the demo-lead founder notification.

No network / no real email: NOTIFY_STUB stubs the notifier, and the Mailgun-backed
password-reset send is best-effort (it swallows EmailConfigError when Mailgun isn't
configured), so /password/forgot still returns its generic response.

Run: python account_test.py
"""
import os
import base64
import json

from cryptography.fernet import Fernet

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./account.db")
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "SERVERPUBLICKEYbase64example=="
os.environ["WG_ENDPOINT"] = "vpn.lumaris.example"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_test"
os.environ["NOTIFY_STUB"] = "true"                     # don't actually send
os.environ["ADMIN_USERS"] = "info@petabyte.market"     # founder inbox
os.environ["CAL_BOOKING_URL"] = "https://cal.com/petabyte/demo"

for f in ("account.db", "account.db-wal", "account.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient  # noqa: E402
import db as dbmod  # noqa: E402
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()
import main  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- login form shows the reset link, and /reset serves the form ----
login_html = c.get("/login").text
ok("login form has a 'Forgot password?' link", "Forgot password?" in login_html)
ok("login form calls /password/forgot", "/password/forgot" in login_html)
reset_page = c.get("/reset")
ok("/reset serves 200", reset_page.status_code == 200)
ok("/reset has a new-password form", "Update password" in reset_page.text and "/password/reset" in reset_page.text)

# ---- set up a user WITH an email ----
c.post("/register_user", json={"username": "resetme", "password": "old-password-123"})
s = dbmod.SessionLocal()
u = main.get_user_by_username(s, "resetme")
u.email = "resetme@example.com"
s.commit()

# baseline: the old password logs in
ok("baseline login with old password", c.post(
    "/login", data={"username": "resetme", "password": "old-password-123"}).status_code == 200)

# ---- forgot: generic response, no account enumeration ----
r1 = c.post("/password/forgot", json={"identifier": "resetme@example.com"})
r2 = c.post("/password/forgot", json={"identifier": "does-not-exist@nowhere.tld"})
ok("forgot (known) returns 200", r1.status_code == 200)
ok("forgot (unknown) returns 200 (no enumeration)", r2.status_code == 200)
ok("forgot responses are identical (no enumeration)", r1.json() == r2.json())

# ---- reset with a real token minted the same way the emailed link is ----
u = main.get_user_by_username(s, "resetme")   # refresh
token = main._pwreset_token(u)

ok("reset rejects a bogus token", c.post(
    "/password/reset", json={"token": "not-a-token", "new_password": "brand-new-123"}).status_code == 400)
ok("reset rejects a short password", c.post(
    "/password/reset", json={"token": token, "new_password": "short"}).status_code == 422)

good = c.post("/password/reset", json={"token": token, "new_password": "brand-new-456"})
ok("reset succeeds with a valid token + good password", good.status_code == 200)

# new password works; old password no longer works
ok("login with NEW password works", c.post(
    "/login", data={"username": "resetme", "password": "brand-new-456"}).status_code == 200)
ok("login with OLD password fails", c.post(
    "/login", data={"username": "resetme", "password": "old-password-123"}).status_code == 400)

# the used token is now stale (password fingerprint changed) -> single-use-ish
ok("used reset token is now rejected", c.post(
    "/password/reset", json={"token": token, "new_password": "another-one-789"}).status_code == 400)

# google-only style account with no email: forgot still returns generic, sends nothing
c.post("/register_user", json={"username": "noemail", "password": "whatever-123"})
ok("forgot for account without email still returns 200", c.post(
    "/password/forgot", json={"identifier": "noemail"}).status_code == 200)

# ---- Cal.com booking webhook notifies the founder inbox ----
booking = {"triggerEvent": "BOOKING_CREATED",
           "payload": {"title": "Petabyte demo", "startTime": "2026-08-10T15:00:00Z",
                       "uid": "bk_123", "attendees": [{"name": "Ada", "email": "ada@corp.com"}]}}
# fail-closed: without CAL_WEBHOOK_SECRET the endpoint is DISABLED (no accept-unsigned)
w = c.post("/webhooks/cal", json=booking)
ok("cal webhook without CAL_WEBHOOK_SECRET is disabled -> 503", w.status_code == 503)

# with a secret configured, an unsigned/bad-signature call is rejected
os.environ["CAL_WEBHOOK_SECRET"] = "cal-shhh"
bad = c.post("/webhooks/cal", json=booking)   # no X-Cal-Signature-256 header
ok("cal webhook rejects a bad signature when secret set -> 401", bad.status_code == 401)

# a correctly HMAC-signed booking is accepted
import hmac as _hmac, hashlib as _hashlib, json as _json
_raw = _json.dumps(booking).encode()
_sig = _hmac.new(b"cal-shhh", _raw, _hashlib.sha256).hexdigest()
good = c.post("/webhooks/cal", content=_raw,
              headers={"X-Cal-Signature-256": _sig, "Content-Type": "application/json"})
ok("cal webhook accepts a correctly-signed booking -> 200", good.status_code == 200)
os.environ.pop("CAL_WEBHOOK_SECRET", None)

# ---- demo request path notifies the founder without crashing ----
d = c.post("/demo/request", json={"name": "Grace Hopper", "email": "grace@navy.mil",
                                  "organization": "USN", "role": "buyer",
                                  "workload": "matmul"})
ok("demo request returns ok", d.status_code == 200 and d.json().get("ok") is True)
ok("demo request returns the booking url", d.json().get("booking_url") == os.environ["CAL_BOOKING_URL"])

# ---- provider wiring: EMAIL_PROVIDER=mailgun selects the Mailgun-backed provider ----
import notify_providers  # noqa: E402
_prev_stub = os.environ.get("NOTIFY_STUB")
os.environ["NOTIFY_STUB"] = "false"
os.environ["EMAIL_PROVIDER"] = "mailgun"
ok("EMAIL_PROVIDER=mailgun selects MailgunProvider",
   isinstance(notify_providers.get_email_provider(), notify_providers.MailgunProvider))
os.environ["NOTIFY_STUB"] = _prev_stub or "true"

# ---- SECURITY: admin privilege escalation via unverified email is impossible ----
# ADMIN_USERS is the founder email "info@petabyte.market" (set at the top of this file).
# A buyer must NOT be able to become admin by claiming that email (or a look-alike username);
# only a VERIFIED matching email — which requires the emailed-token flow — confers admin.

class _U:                                   # minimal stand-in for _is_admin unit checks
    def __init__(self, username="", email=None, email_verified=False):
        self.username = username; self.email = email; self.email_verified = email_verified


ADMIN_EMAIL = "info@petabyte.market"
ok("attacker: unverified email == admin address is NOT admin",
   main._is_admin(_U("attacker", ADMIN_EMAIL, email_verified=False)) is False)
ok("attacker: username == admin email (look-alike) is NOT admin",
   main._is_admin(_U(ADMIN_EMAIL, None, email_verified=False)) is False)
ok("attacker: verified but DIFFERENT email is NOT admin",
   main._is_admin(_U("attacker", "someoneelse@example.com", email_verified=True)) is False)
ok("legit: VERIFIED admin email IS admin (positive control)",
   main._is_admin(_U("founder", ADMIN_EMAIL, email_verified=True)) is True)
ok("no allowlist match -> not admin", main._is_admin(_U("nobody", "nobody@x.com", True)) is False)

# End-to-end through the real endpoint + auth: register a buyer, set their email to the admin
# address via POST /account/email, and confirm they are still NOT admin.
c.post("/register_user", json={"username": "escalate", "password": "escalate-pass-123"})
tok = c.post("/login", data={"username": "escalate", "password": "escalate-pass-123"}).json()["access_token"]
hdr = {"Authorization": f"Bearer {tok}"}
r = c.post("/account/email", json={"email": ADMIN_EMAIL, "notify_email": True}, headers=hdr)
ok("POST /account/email sets the address but does NOT verify it", r.status_code == 200
   and r.json().get("email") == ADMIN_EMAIL and r.json().get("email_verified") is False)
ok("buyer who claimed the admin email is refused by /admin/whoami (403)",
   c.get("/admin/whoami", headers=hdr).status_code == 403)

# The stale-verification path: verify the buyer's OWN email, then switch to the admin address.
# The switch must RESET email_verified, so they still cannot become admin.
_su = dbmod.SessionLocal()
_eu = main.get_user_by_username(_su, "escalate")
_eu.email = "escalate@example.com"; _eu.email_verified = True; _su.commit(); _su.close()
r2 = c.post("/account/email", json={"email": ADMIN_EMAIL, "notify_email": True}, headers=hdr)
ok("switching a VERIFIED email to the admin address resets verification",
   r2.status_code == 200 and r2.json().get("email_verified") is False)
ok("still refused by /admin/whoami after the verified->admin switch (403)",
   c.get("/admin/whoami", headers=hdr).status_code == 403)

s.close()
print(f"\n=== account: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
