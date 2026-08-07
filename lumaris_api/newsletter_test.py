"""Offline tests for the homepage newsletter signup (Mailgun mailing list + Postgres SoT).

Mailgun is ALWAYS mocked here — CI never makes a real Mailgun request. Covers: valid signup,
malformed/empty email, duplicate idempotency, Mailgun success/already/4xx/5xx/timeout,
DB failure, rate limiting, and a regression that the homepage is wired to the real handler
and no longer shows the "isn't wired up" placeholder.

Run: python newsletter_test.py
"""
import atexit
import os

from cryptography.fernet import Fernet

# Configure BEFORE importing main: NEWSLETTER_LIST_ADDRESS is captured at import time.
os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./newsletter_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"
os.environ["WG_ENDPOINT"] = "y"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "w"
os.environ["REAPER_DISABLED"] = "true"
os.environ["NOTIFY_STUB"] = "true"
os.environ["NEWSLETTER_PROVIDER"] = "mailgun"
os.environ["NEWSLETTER_LIST_ADDRESS"] = "newsletter@petabyte.market"
os.environ["MAILGUN_API_KEY"] = "key-test-not-real"

_DB_FILES = ("newsletter_test.db", "newsletter_test.db-wal", "newsletter_test.db-shm")


def _cleanup():
    for f in _DB_FILES:
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass


_cleanup()
atexit.register(_cleanup)

import httpx  # noqa: E402
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


# ---- Mailgun mock plumbing (module-level httpx.post; TestClient uses its own client) ----
_orig_post = httpx.post


class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def mock_mailgun(resp=None, raise_exc=None):
    def fake(*a, **k):
        if raise_exc is not None:
            raise raise_exc
        return resp
    httpx.post = fake


def reset_mailgun():
    httpx.post = _orig_post


def sub(email):
    return c.post("/newsletter/subscribe", json={"email": email})


def db_row(email):
    s = dbmod.SessionLocal()
    try:
        return s.query(dbmod.NewsletterSubscriber).filter(
            dbmod.NewsletterSubscriber.email == email).first()
    finally:
        s.close()


# ---- valid signup: Mailgun 200 -> DB row subscribed + synced ----
mock_mailgun(_FakeResp(200))
r = sub("  Alice@Example.COM ")
ok("valid signup returns 200 + friendly message",
   r.status_code == 200 and "subscrib" in r.json().get("message", "").lower())
row = db_row("alice@example.com")
ok("email is normalized (trim+lowercase) and persisted as subscribed",
   row is not None and row.status == "subscribed" and row.source == "homepage")
ok("successful Mailgun add marks the row synced", row is not None and row.mailgun_synced is True)

# ---- malformed + empty email are rejected server-side (422) ----
ok("malformed email rejected (422)", sub("not-an-email").status_code == 422)
ok("empty email rejected (422)", sub("").status_code == 422)
ok("whitespace-only email rejected (422)", sub("   ").status_code == 422)

# ---- duplicate signup is idempotent: one row, still a friendly success ----
r2 = sub("alice@example.com")
ok("duplicate signup still returns 200 (neutral)", r2.status_code == 200)
s = dbmod.SessionLocal()
n = s.query(dbmod.NewsletterSubscriber).filter(
    dbmod.NewsletterSubscriber.email == "alice@example.com").count()
s.close()
ok("duplicate signup does NOT create a second row", n == 1)

# ---- Mailgun 'already exists' 400 -> treated as success/synced ----
mock_mailgun(_FakeResp(400, "Address already exists"))
ok("Mailgun 'already exists' still returns 200", sub("bob@example.com").status_code == 200)
ok("'already exists' counts as synced", db_row("bob@example.com").mailgun_synced is True)

# ---- Mailgun failures are best-effort: DB persists, user still gets a clean success ----
mock_mailgun(_FakeResp(400, "some 4xx error"))
ok("Mailgun 4xx: signup still 200 (DB is authoritative)", sub("c4@example.com").status_code == 200)
ok("Mailgun 4xx: row persisted but not synced (reconcile later)",
   db_row("c4@example.com") is not None and db_row("c4@example.com").mailgun_synced is False)

mock_mailgun(_FakeResp(500, "mailgun down"))
ok("Mailgun 5xx: signup still 200", sub("c5@example.com").status_code == 200)
ok("Mailgun 5xx: row persisted, not synced", db_row("c5@example.com").mailgun_synced is False)

mock_mailgun(raise_exc=httpx.TimeoutException("timeout"))
ok("Mailgun timeout: signup still 200 (no leak, DB persisted)",
   sub("ct@example.com").status_code == 200)
ok("Mailgun timeout: row persisted, not synced", db_row("ct@example.com").mailgun_synced is False)

# provider internals never reach the browser
mock_mailgun(_FakeResp(500, "SECRET-mailgun-internal-xyz"))
_body = sub("leak@example.com").text
ok("provider error text is never exposed to the browser",
   "SECRET-mailgun-internal-xyz" not in _body and "mailgun" not in _body.lower())
mock_mailgun(_FakeResp(200))

# ---- DB failure -> safe 503, no crash, no leak ----
main._RL_BUCKETS.clear()   # isolate from the rate-limit budget consumed by earlier requests
_orig_record = dbmod.record_newsletter_signup
def _boom(*a, **k):
    raise RuntimeError("db down")
dbmod.record_newsletter_signup = _boom
_rdb = sub("dbfail@example.com")
dbmod.record_newsletter_signup = _orig_record
ok("DB failure returns a safe 503 (not a 500 / stack trace)", _rdb.status_code == 503)
ok("DB failure body is a safe message (no stack trace)",
   "traceback" not in _rdb.text.lower() and "RuntimeError" not in _rdb.text)

# ---- rate limiting: the public endpoint caps volume (anti email-bombing) ----
main._RL_BUCKETS.clear()
codes = [sub(f"rl{i}@example.com").status_code for i in range(13)]
ok("newsletter signup is rate-limited (a 429 appears under burst)", 429 in codes)
ok("rate limit allows a reasonable number before blocking", codes.count(200) >= 5)
main._RL_BUCKETS.clear()

# ---- regression (#24): homepage is wired to the real handler; placeholder is gone ----
home = c.get("/")
ok("homepage renders", home.status_code == 200)
html = home.text
ok("homepage subscribe button is wired to subscribeNewsletter",
   'data-act="subscribeNewsletter"' in html)
ok("homepage posts to the real /newsletter/subscribe endpoint", "/newsletter/subscribe" in html)
ok("homepage no longer shows the 'isn't wired up' placeholder",
   "isn't wired up" not in html.lower() and "wired up yet" not in html.lower())
ok("the subscribe handler is connected (POST is not 404)",
   sub("connected@example.com").status_code in (200, 429))

reset_mailgun()
print(f"\n=== newsletter: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
