"""security_test.py — regression tests for the offensive-hardening batch.

Covers, offline (no network, no GPU, SQLite):
  * _client_ip is spoof-resistant: forwarding headers are trusted ONLY from a declared
    proxy, X-Real-IP (which nginx sets to the true peer) wins, and X-Forwarded-For is read
    from the RIGHT — so a client cannot forge its IP by PREPENDing an entry.
  * the token-less Prometheus endpoint no longer authorizes a SPOOFED loopback IP.
  * cross-tenant object refs: a buyer may bind only their OWN inputs/<id>/ prefix, and a
    node can never presign another tenant's key (input_url tenant backstop).
  * stored-XSS at the source: gpu_model / region / provider / username / org name reject
    HTML metacharacters at write time (SpecModel / UserRegisterModel / OrgCreateModel).

Run: python security_test.py
"""
import os

from cryptography.fernet import Fernet

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
# Force the dedicated SQLite test DB UNCONDITIONALLY. Never inherit DATABASE_URL here — this
# file used to DROP SCHEMA public on a postgres URL, which would wipe staging/prod if the env
# happened to point there. This is an offline SQLite-only suite.
os.environ["DATABASE_URL"] = "sqlite:///./security.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "SERVERPUBLICKEYbase64example=="
os.environ["WG_ENDPOINT"] = "vpn.lumaris.example"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_test"
os.environ["NOTIFY_STUB"] = "true"
os.environ.pop("PROMETHEUS_METRICS_TOKEN", None)   # exercise the loopback gate, not the token path

for f in ("security.db", "security.db-wal", "security.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient   # noqa: E402
from pydantic import ValidationError        # noqa: E402
import db as dbmod                           # noqa: E402  (SQLite only — see DATABASE_URL above)
import main   # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


class _Hdrs(dict):
    def get(self, k, default=None):
        return dict.get(self, k, default)


class _Req:
    """Minimal stand-in for starlette Request (only what _client_ip touches)."""
    def __init__(self, peer, headers=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = _Hdrs(headers or {})


# ---------------------------------------------------------------- _client_ip spoofing
# A direct, UNTRUSTED peer is used verbatim — its forwarding headers are ignored.
ok("untrusted peer: X-Forwarded-For is ignored",
   main._client_ip(_Req("9.9.9.9", {"X-Forwarded-For": "1.1.1.1"})) == "9.9.9.9")

# Trusted proxy + X-Real-IP (what nginx sets to $remote_addr) wins over a spoofed XFF.
ok("trusted proxy: X-Real-IP wins over spoofed left-most XFF",
   main._client_ip(_Req("127.0.0.1",
                        {"X-Real-IP": "8.8.8.8",
                         "X-Forwarded-For": "1.1.1.1, 8.8.8.8"})) == "8.8.8.8")

# Trusted proxy, no X-Real-IP: the real client is the RIGHT-most non-proxy hop, NOT the
# attacker-prepended left-most entry.
ok("trusted proxy: XFF is read from the right (prepended spoof ignored)",
   main._client_ip(_Req("127.0.0.1",
                        {"X-Forwarded-For": "1.1.1.1, 8.8.8.8"})) == "8.8.8.8")

# A forged loopback in XFF must NOT resolve to loopback (this is the metrics-gate bypass).
ok("trusted proxy: forged loopback in XFF does NOT become the client IP",
   main._client_ip(_Req("127.0.0.1",
                        {"X-Real-IP": "8.8.8.8",
                         "X-Forwarded-For": "127.0.0.1, 8.8.8.8"})) == "8.8.8.8")

# Backwards-compatible single-hop XFF (GeoIP tests rely on this).
ok("trusted proxy: single-hop XFF still returns that client",
   main._client_ip(_Req("testclient", {"X-Forwarded-For": "10.1.1.1"})) == "10.1.1.1")


# ---------------------------------------------------------------- metrics loopback gate
# No token configured -> only genuine loopback/trusted callers may scrape. A caller that
# nginx tags with a real external X-Real-IP is rejected even though it forged XFF loopback.
r = c.get(main._PROM_PATH, headers={"X-Real-IP": "8.8.8.8", "X-Forwarded-For": "127.0.0.1"})
ok("token-less metrics: spoofed loopback (real X-Real-IP) is REJECTED", r.status_code == 403)
r = c.get(main._PROM_PATH, headers={"X-Forwarded-For": "127.0.0.1, 8.8.8.8"})
ok("token-less metrics: appended real client behind forged loopback is REJECTED",
   r.status_code == 403)
r = c.get(main._PROM_PATH, headers={"X-Real-IP": "127.0.0.1"})
ok("token-less metrics: genuine loopback is allowed", r.status_code == 200)


# ---------------------------------------------------------------- cross-tenant object refs
ok("_storage_key_from_ref strips s3://bucket/",
   main._storage_key_from_ref("s3://b/inputs/5/f.mp4") == "inputs/5/f.mp4")
ok("buyer's OWN input ref is accepted",
   main._ref_is_own_input("s3://b/inputs/5/f.mp4", 5) is True)
ok("another tenant's input ref is REJECTED",
   main._ref_is_own_input("s3://b/inputs/999/secret.mp4", 5) is False)
ok("a non-inputs key (e.g. another tenant's backups) is REJECTED",
   main._ref_is_own_input("s3://b/backups/999/1/x.tar", 5) is False)
ok("empty / None ref is REJECTED (fail closed)",
   main._ref_is_own_input("", 5) is False and main._ref_is_own_input(None, 5) is False)


# ---------------------------------------------------------------- stored-XSS at write time
def _rejects(factory, label):
    try:
        factory()
        ok(label, False)
    except ValidationError:
        ok(label, True)


_rejects(lambda: main.SpecModel(cpu=1, ram=1, duration=1, price_per_hour=1.0,
                                provider="ok", gpu_model="<img src=x onerror=alert(1)>"),
         "SpecModel rejects HTML in gpu_model")
_rejects(lambda: main.SpecModel(cpu=1, ram=1, duration=1, price_per_hour=1.0,
                                provider="ok", region="\"><script>alert(1)</script>"),
         "SpecModel rejects HTML in region")
_rejects(lambda: main.UserRegisterModel(username="<b>xss</b>", password="corrhorsebatt42"),
         "UserRegisterModel rejects HTML in username")
_rejects(lambda: main.OrgCreateModel(name="<svg onload=alert(1)>"),
         "OrgCreateModel rejects HTML in name")

# Real-world labels must still be accepted (no false positives).
ok("SpecModel accepts a real GPU label",
   main.SpecModel(cpu=8, ram=32, duration=24, price_per_hour=1.5, provider="self-hosted",
                  gpu_model="RTX 4090", region="us-east-1", country="US").gpu_model == "RTX 4090")
ok("UserRegisterModel accepts a normal username",
   main.UserRegisterModel(username="alice_2", password="corrhorsebatt42").username == "alice_2")

# End-to-end: the API returns 422 (not a 500) for an XSS username at /register_user.
r = c.post("/register_user", json={"username": "<script>1</script>", "password": "corrhorsebatt42"})
ok("/register_user returns 422 for an XSS username", r.status_code == 422)


# ---------------------------------------------------------------- DoS / input bounds
_rejects(lambda: main.TranscodeModel(input_ref="s3://b/inputs/1/v.mp4", nodes=100000),
         "TranscodeModel rejects an absurd node fan-out")
_rejects(lambda: main.TranscodeModel(input_ref="s3://b/inputs/1/v.mp4", hours=1_000_000),
         "TranscodeModel rejects an absurd hours value")
_rejects(lambda: main.TranscodeModel(input_ref="s3://b/inputs/1/v.mp4", crf=999),
         "TranscodeModel rejects an out-of-range CRF")
_rejects(lambda: main.RenderModel(blend_ref="s3://b/inputs/1/s.blend",
                                  frame_start=100, frame_end=1),
         "RenderModel rejects frame_end < frame_start")
_rejects(lambda: main.RenderModel(blend_ref="s3://b/inputs/1/s.blend",
                                  frame_start=0, frame_end=9_000_000),
         "RenderModel rejects an oversized frame range")
_rejects(lambda: main.RenderModel(blend_ref="s3://b/inputs/1/s.blend",
                                  frame_start=1, frame_end=10, samples=10_000_000),
         "RenderModel rejects an absurd sample count")
ok("TranscodeModel accepts a normal request",
   main.TranscodeModel(input_ref="s3://b/inputs/1/v.mp4", nodes=4, hours=2,
                       duration_seconds=120, crf=23).nodes == 4)
ok("RenderModel accepts a normal frame range",
   main.RenderModel(blend_ref="s3://b/inputs/1/s.blend", frame_start=1, frame_end=240,
                    nodes=8, samples=256).frame_end == 240)


# ---------------------------------------------------------------- cookie session + CSRF (WS2)
# The browser JWT now lives in an HttpOnly cookie (XSS can't read it), with a double-submit
# CSRF token for cookie-authenticated writes. Bearer auth (CLI/API) is unchanged and NOT
# CSRF-checked. Use a FRESH client so no ambient cookie leaks in from earlier tests.
_cc = TestClient(main.app)
_cc.post("/register_user", json={"username": "csrf_user", "password": "hunter2-correct-horse"})
_lg = _cc.post("/login", data={"username": "csrf_user", "password": "hunter2-correct-horse"})
_setck = " ".join(_lg.headers.get_list("set-cookie")) if hasattr(_lg.headers, "get_list") else _lg.headers.get("set-cookie", "")
ok("login sets an HttpOnly pb_session cookie (JWT not reachable from JS)",
   "pb_session=" in _setck and "httponly" in _setck.lower())
ok("login still returns the bearer token in the body (CLI/API unaffected)",
   isinstance(_lg.json().get("access_token"), str))
ok("login sets a readable pb_csrf double-submit cookie",
   "pb_csrf=" in _setck and bool(_cc.cookies.get("pb_csrf")))
_csrf = _cc.cookies.get("pb_csrf")

# the ambient cookie authenticates a safe GET (no header needed)
ok("cookie session authenticates a GET (/me)", _cc.get("/me").status_code == 200)

# a cookie-authenticated WRITE without the CSRF header is REJECTED (403)
ok("cookie-auth POST without X-CSRF-Token is blocked (403 CSRF)",
   _cc.post("/change_role", json={"role": "seller"}).status_code == 403)
# ...and ACCEPTED with the matching double-submit token
ok("cookie-auth POST with a matching X-CSRF-Token is accepted (not 403)",
   _cc.post("/change_role", json={"role": "seller"},
            headers={"X-CSRF-Token": _csrf}).status_code != 403)
# a forged/mismatched token is rejected
ok("cookie-auth POST with a WRONG X-CSRF-Token is blocked (403)",
   _cc.post("/change_role", json={"role": "buyer"},
            headers={"X-CSRF-Token": "not-the-token"}).status_code == 403)

# Bearer auth carries no ambient authority -> NOT CSRF-checked (a stray cookie must not force it)
_btok = _lg.json()["access_token"]
_bc = TestClient(main.app)
ok("Bearer POST needs no CSRF token (Bearer is not a CSRF target)",
   _bc.post("/change_role", json={"role": "seller"},
            headers={"Authorization": f"Bearer {_btok}"}).status_code != 403)

# logout clears the session server-side (HttpOnly -> JS can't), and auth then fails
_out = _cc.post("/logout")
_clear = " ".join(_out.headers.get_list("set-cookie")) if hasattr(_out.headers, "get_list") else _out.headers.get("set-cookie", "")
ok("logout deletes the session cookie", "pb_session=" in _clear)
_cc.cookies.clear()
ok("after logout (no cookie) a protected GET is unauthenticated", _cc.get("/me").status_code in (401, 403))

# a PUBLIC endpoint is never CSRF-blocked by a stray cookie (CSRF lives in the auth dep, not a
# blanket middleware): a fresh anonymous client can still POST a public webhook/route.
ok("public endpoints are not CSRF-gated (no session -> no CSRF)",
   TestClient(main.app).post("/newsletter/subscribe",
                             json={"email": "csrf-check@example.com"}).status_code in (200, 400, 409, 422, 429))

# money-in probing is rate-limited: repeated FAILED /payments/authorize attempts (here: no auth
# -> 401) eventually get 429 with a Retry-After. Legit SUCCESSFUL launches never consume budget
# (authorize is not in _RL_COUNT_ALL), so this cannot throttle a real buyer's valid job sweep.
_rl = TestClient(main.app)
_authz_codes = [_rl.post("/payments/authorize", json={"spec_id": "nope", "estimated_seconds": 60}).status_code
                for _ in range(35)]
ok("failed /payments/authorize probing is rate limited (429 after the cap)", 429 in _authz_codes)
ok("the authorize rate-limit response carries Retry-After",
   "Retry-After" in _rl.post("/payments/authorize", json={"spec_id": "nope", "estimated_seconds": 60}).headers)


print(f"\n=== security: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
