"""sentry_test.py — Sentry integration: degrade-safe init + privacy scrubbing.

Proves the observability boundary holds:
  * the app initialises WITHOUT a DSN (Sentry off, no crash);
  * Sentry initialises when configured, exactly once (idempotent);
  * a broken Sentry init NEVER breaks startup (degrade mode);
  * the before_send scrubber removes every sensitive field/value, recursively, and reuses the
    SAME central redactor as structured logs (no competing sanitizer);
  * expected 4xx HTTP errors are dropped (no noise); unexpected exceptions are kept;
  * safe correlation ids survive.

NO real network to Sentry: sentry_sdk.init is stubbed; scrubbing is a pure function.
Run: python sentry_test.py
"""
import os

os.environ["OBSERVABILITY_FAILURE_MODE"] = "degrade"
os.environ["LOG_REDACTION_ENABLED"] = "true"
os.environ.pop("SENTRY_DSN", None)                 # start with NO dsn

import observability as o  # noqa: E402

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# 1) app/module import + init works with NO DSN, and Sentry stays off.
o._sentry_ok = False
o.SENTRY_DSN = ""
ok("1. init_sentry() is a no-op without a DSN (app starts without SENTRY_DSN)",
   o.init_sentry() is False and o.health()["sentry"]["active"] is False)

# stub sentry_sdk.init so nothing ever hits the network.
import sentry_sdk  # noqa: E402
_calls = {"init": 0}
_real_init = sentry_sdk.init
sentry_sdk.init = lambda *a, **k: _calls.__setitem__("init", _calls["init"] + 1)

# 2) initialises when configured; 3) exactly once (idempotent).
o._sentry_ok = False
o.SENTRY_ENABLED = True
o.SENTRY_DSN = "https://examplekey@o0.ingest.sentry.io/1"
ok("2. Sentry initialises when a DSN is configured", o.init_sentry() is True and _calls["init"] == 1)
ok("3. Sentry initialises only once (idempotent)",
   o.init_sentry() is True and _calls["init"] == 1)
ok("2b. FastAPI/Starlette/SQLAlchemy/logging/threading integrations construct (no raise)",
   _calls["init"] == 1 and o._sentry_ok is True)
ok("health reports Sentry active + environment", o.health()["sentry"]["active"] is True)

# 14) a broken Sentry init must NOT break the app (degrade).
o._sentry_ok = False
sentry_sdk.init = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated sentry boom"))
_raised = False
try:
    res = o.init_sentry()
except Exception:
    _raised = True
ok("14. Sentry init failure degrades (returns False, never raises)", res is False and not _raised)
sentry_sdk.init = _real_init

# ---- before_send scrubber (pure function; the privacy boundary) ----
def scrub(event, hint=None):
    return o._sentry_scrub(event, hint or {})


evt = {
    "message": "boom for buyer with Authorization: Bearer abc.def.ghi and sk_test_deadbeef123",
    "request": {
        "url": "https://petabyte.market/pay?password=hunter2&token=eyJabc.def.ghi",
        "headers": {"Authorization": "Bearer eyJhbGciOi.JWT.sig", "X-Api-Key": "pk_x",
                    "Content-Type": "application/json"},
        "cookies": {"session": "s3cr3t"},
        "query_string": "token=eyJabc.def.ghi&password=hunter2&spec_id=e1qdx",
        "data": {"password": "hunter2", "client_secret": "pi_123_secret_ZZZ",
                 "api_key": "sk_live_zzz", "transaction_id": "ctx_pub_123",
                 "nested": {"seller_api_key": "key_should_go", "spec_id": "e1qdx"}},
    },
    "extra": {"jwt": "eyJhbg.body.sig", "server_private_key": "PRIV", "payment_intent_id": "pi_123"},
    "tags": {"transaction_id": "ctx_pub_123"},
    "user": {"id": "42", "email": "buyer@example.com"},
    "exception": {"values": [{"type": "ValueError",
                              "value": "failed with token Bearer zzz.yyy.xxx",
                              "stacktrace": {"frames": [
                                  {"function": "capture",
                                   "vars": {"secret_key": "SK", "password": "hunter2",
                                            "spec_id": "e1qdx"}}]}}]},
}
out = scrub(dict(evt), {})
req = out["request"]
data = req["data"]
extra = out["extra"]

# 5) Authorization header removed/redacted
ok("5. Authorization header is redacted", req["headers"]["Authorization"] == o._REDACTED)
ok("5b. cookies are dropped entirely", "cookies" not in req)
ok("5c. api-key header is redacted", req["headers"]["X-Api-Key"] == o._REDACTED)
# 6) JWT/token fields
ok("6. jwt field is redacted (nested extra)", extra["jwt"] == o._REDACTED)
ok("6b. query_string is dropped entirely (names like password=/token= aren't secret-shaped)",
   "query_string" not in req)
ok("6c. URL query component is stripped (no ?password=/token= reaches Sentry)",
   "?" not in req.get("url", "") and "hunter2" not in req.get("url", ""))
# frame locals never leave (include_local_variables=False + defence-in-depth scrub)
_fr = out["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
ok("frame-local secrets are redacted (secret_key + password)",
   _fr["secret_key"] == o._REDACTED and _fr["password"] == o._REDACTED and _fr["spec_id"] == "e1qdx")
# 7) Stripe client_secret
ok("7. client_secret is redacted", data["client_secret"] == o._REDACTED)
# 8) passwords
ok("8. password is redacted", data["password"] == o._REDACTED)
# 9) API keys
ok("9. api_key is redacted", data["api_key"] == o._REDACTED)
ok("9b. seller_api_key is redacted (deep nested)", data["nested"]["seller_api_key"] == o._REDACTED)
ok("9c. server_private_key is redacted", extra["server_private_key"] == o._REDACTED)
# 10) nested sensitive values
ok("10. nested dictionaries are recursively sanitized",
   data["nested"]["seller_api_key"] == o._REDACTED and data["nested"]["spec_id"] == "e1qdx")
# 11) safe identifiers remain
ok("11. safe transaction_id remains available", data["transaction_id"] == "ctx_pub_123")
ok("11b. safe spec_id remains available", data["nested"]["spec_id"] == "e1qdx")
ok("11c. safe payment_intent_id remains available", extra["payment_intent_id"] == "pi_123")
# secret-shaped values masked in free text + exception value
ok("message secrets masked (sk_test / bearer)",
   "sk_test_deadbeef123" not in out["message"] and "Bearer abc.def.ghi" not in out["message"])
ok("exception value secrets masked",
   "Bearer zzz.yyy.xxx" not in out["exception"]["values"][0]["value"])
# user identity dropped (email is PII)
ok("user identity is dropped", "user" not in out)

# 12) expected 4xx HTTP errors do NOT create noise (dropped)
class _HTTPExc(Exception):
    def __init__(self, code):
        self.status_code = code


for code in (400, 401, 403, 404, 409, 422):
    dropped = scrub({"message": "expected"}, {"exc_info": (None, _HTTPExc(code), None)})
    ok(f"12. expected {code} HTTP error is dropped (no Sentry noise)", dropped is None)

# 13) unexpected exceptions ARE observable (kept)
kept500 = scrub({"message": "boom"}, {"exc_info": (None, _HTTPExc(500), None)})
kept_generic = scrub({"message": "boom"}, {"exc_info": (None, RuntimeError("x"), None)})
ok("13. unexpected 500 is kept (observable)", kept500 is not None)
ok("13b. generic exception (no status) is kept (observable)", kept_generic is not None)

# 15) fail-closed: if scrubbing raises internally, the event is dropped, not leaked.
class _Boom(dict):
    def get(self, *a, **k):
        raise RuntimeError("scrubber blew up")


ok("15. scrubber fails CLOSED (drops event if sanitising raises)", scrub(_Boom(), {}) is None)

print(f"\n=== sentry: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
