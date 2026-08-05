"""email_test.py — offline unit tests for the Mailgun email integration.

No network: httpx.post is monkeypatched. Covers successful send, Mailgun API failure,
invalid API key, timeout, network error, template rendering (all six), the plain-text
fallback, and that the API key is never logged. Run: python email_test.py
"""
import io
import logging
import os

os.environ.setdefault("MAILGUN_API_KEY", "key-unit-test-fake")
os.environ.setdefault("MAILGUN_DOMAIN", "petabyte.market")

import httpx
import email_service as es
from email_service import (EmailService, MailgunBackend, EmailConfigError, EmailSendError,
                           render_email, html_to_text, DEFAULT_FROM)

PASSES = FAILS = 0
def ok(label, cond):
    global PASSES, FAILS
    print(("PASS " if cond else "FAIL ") + label)
    if cond:
        PASSES += 1
    else:
        FAILS += 1
        raise AssertionError(label)


class FakeResp:
    def __init__(self, status, text="", jid=None):
        self.status_code = status; self.text = text; self._jid = jid
    def json(self):
        if self._jid is None:
            raise ValueError("not json")
        return {"id": self._jid, "message": "Queued. Thank you."}


_orig_post = httpx.post
_calls = []
def _post_ok(url, **kw):
    _calls.append((url, kw))
    return FakeResp(200, '{"id":"<ok@petabyte.market>"}', "<20260805.ok@petabyte.market>")


svc = EmailService(MailgunBackend(api_key="key-unit-test-fake", domain="petabyte.market"))

# ---------------- 1) invalid configuration fails closed ----------------
try:
    MailgunBackend(api_key="", domain="").send(
        to="a@b.com", subject="x", html="<p>x</p>", text="x", from_addr=DEFAULT_FROM)
    ok("missing config raises EmailConfigError", False)
except EmailConfigError:
    ok("missing config raises EmailConfigError", True)

# ---------------- 2) successful send ----------------
es.httpx.post = _post_ok
try:
    res = svc.send_welcome("ada@example.com", name="Ada", dashboard_url="https://petabyte.market/app")
    ok("successful send returns ok + provider message id",
       res.ok and res.provider_message_id and res.status_code == 200)
    _url, _kw = _calls[-1]
    ok("posts to the Mailgun messages endpoint", _url.endswith("/v3/petabyte.market/messages"))
    ok("authenticates as api:<key> via basic auth", _kw["auth"] == ("api", "key-unit-test-fake"))
    _data = _kw["data"]
    ok("multipart carries BOTH html and text (plain-text fallback)",
       bool(_data.get("html")) and bool(_data.get("text")))
    ok("from is the hardcoded Petabyte sender", _data["from"] == DEFAULT_FROM)
    ok("html embeds the logo inline via cid", "cid:petabyte-logo.png" in _data["html"])
    ok("logo is attached as an inline file", any(f[0] == "inline" for f in (_kw.get("files") or [])))
    ok("send carries a Mailgun tag", _data.get("o:tag") == ["welcome"])
finally:
    es.httpx.post = _orig_post

# ---------------- 3) Mailgun API failure (5xx) ----------------
es.httpx.post = lambda url, **kw: FakeResp(502, "Bad Gateway")
try:
    try:
        svc.send_marketplace_notification("a@b.com", title="t", message="m",
                                          cta_label="Go", cta_url="https://x")
        ok("Mailgun API failure raises EmailSendError", False)
    except EmailSendError as e:
        ok("Mailgun API failure raises EmailSendError", "502" in str(e))
finally:
    es.httpx.post = _orig_post

# ---------------- 4) invalid API key (401) ----------------
es.httpx.post = lambda url, **kw: FakeResp(401, "Forbidden")
try:
    try:
        svc.send_login_otp("a@b.com", code="123456")
        ok("invalid API key raises EmailSendError", False)
    except EmailSendError as e:
        ok("invalid API key raises EmailSendError (401)", "401" in str(e))
finally:
    es.httpx.post = _orig_post

# ---------------- 5) timeout ----------------
def _timeout(url, **kw):
    raise httpx.TimeoutException("request timed out")
es.httpx.post = _timeout
try:
    try:
        svc.send_password_reset("a@b.com", reset_url="https://x")
        ok("timeout raises EmailSendError", False)
    except EmailSendError as e:
        ok("timeout raises EmailSendError", "tim" in str(e).lower())
finally:
    es.httpx.post = _orig_post

# ---------------- 6) network error ----------------
def _conn(url, **kw):
    raise httpx.ConnectError("name resolution failed")
es.httpx.post = _conn
try:
    try:
        svc.send_email_verification("a@b.com", verify_url="https://x")
        ok("network error raises EmailSendError", False)
    except EmailSendError:
        ok("network error raises EmailSendError", True)
finally:
    es.httpx.post = _orig_post

# ---------------- 7) template rendering (all six) ----------------
_templates = [
    ("welcome", {"name": "Ada", "cta_url": "https://petabyte.market/app"}),
    ("verification", {"cta_url": "https://petabyte.market/verify?t=abc", "ttl_minutes": 15}),
    ("password_reset", {"cta_url": "https://petabyte.market/reset?t=abc", "ttl_minutes": 30}),
    ("login_otp", {"code": "482913", "ttl_minutes": 10}),
    ("payment_receipt", {"amount": "$42.50", "description": "H100 · 1h",
                         "date": "2026-08-05", "reference": "ctx_abc123",
                         "cta_url": "https://petabyte.market/tx/ctx_abc123"}),
    ("marketplace_notification", {"title": "Your GPU sold", "message": "A buyer rented your H100.",
                                  "cta_label": "View booking", "cta_url": "https://petabyte.market/x"}),
]
for _name, _ctx in _templates:
    _html, _text = render_email(_name, subject="Test", preheader="pre", **_ctx)
    ok(f"{_name}: renders the inline logo (cid)", "cid:petabyte-logo.png" in _html)
    ok(f"{_name}: carries the petabyte cloud brand", "petabyte" in _html and "cloud" in _html)
    ok(f"{_name}: has a non-empty plain-text fallback", len(_text) > 60)
    ok(f"{_name}: footer + copyright present", "Petabyte Cloud" in _html and "support@petabyte.market" in _html)

# money amounts with '$' survive templating (no placeholder clash) in html AND text
_h, _t = render_email("payment_receipt", subject="R", amount="$42.50", description="GPU",
                      date="2026-08-05", reference="ctx_1", cta_url="https://x")
ok("payment receipt keeps the '$' amount in html and text", "$42.50" in _h and "$42.50" in _t)

# text fallback keeps actionable link URLs
_h, _t = render_email("verification", subject="V", cta_url="https://petabyte.market/verify?t=Z",
                      ttl_minutes=15)
ok("plain-text fallback preserves the verification URL",
   "https://petabyte.market/verify?t=Z" in _t)
ok("html_to_text strips tags", "<" not in html_to_text("<p>hi <b>there</b></p>"))

# ---------------- 8) the API key is NEVER logged; recipient is masked ----------------
_buf = io.StringIO()
_h_ = logging.StreamHandler(_buf)
_lg = logging.getLogger("petabyte.email"); _lg.addHandler(_h_); _lg.setLevel(logging.INFO)
es.httpx.post = _post_ok
try:
    svc.send_welcome("secretbox@example.com", name="X", dashboard_url="https://x")
finally:
    es.httpx.post = _orig_post
    _lg.removeHandler(_h_)
_logtext = _buf.getvalue()
ok("a successful send is logged (structured)", "email SENT" in _logtext)
ok("the API key never appears in logs", "key-unit-test-fake" not in _logtext)
ok("the recipient is masked in logs",
   "secretbox@example.com" not in _logtext and "s***@example.com" in _logtext)

print(f"\n=== email: {PASSES} passed, {FAILS} failed ===")
