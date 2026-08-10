"""e2e_safety_test.py — safety + ergonomics regressions for the real-Stripe-TEST E2E path.

Reproduces (and locks fixes for) the exact pain hit during the live buyer -> GPU -> capture run:
  * a served process must NOT silently fall back to the fake gateway (STRIPE_GATEWAY explicit);
  * a fake ConnectedAccount can never be reused under the real gateway (and vice versa);
  * the Connect endpoints accept an EMPTY body (no more 422 on `{}` / no body);
  * onboarding-link fails CLOSED with a clear code when no absolute return URL is configured
    (instead of a raw 500), and works once PUBLIC_BASE_URL is set;
  * the 14-day payout hold is clock-injectable and correct at the EXACT day-14 boundary.

Offline only: FakeStripeGateway + a bare TestClient (no lifespan, no network).
Run: python e2e_safety_test.py
"""
import os

# FORCE an isolated offline SQLite DB. This is an offline safety suite (gateway guards,
# connect-account mode, payout-hold clock) and MUST NOT inherit a shared DATABASE_URL: on a
# shared Postgres the FakeStripeGateway's deterministic account ids (acct_fake000001…) collide
# with rows other suites leave behind. Never `setdefault` here.
os.environ["DATABASE_URL"] = "sqlite:///./e2e_safety_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_stripe"
os.environ["ADMIN_USERS"] = "admin@petabyte.market"
os.environ["REAPER_DISABLED"] = "true"

for f in ("e2e_safety_test.db", "e2e_safety_test.db-wal", "e2e_safety_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from datetime import datetime, timezone, timedelta  # noqa: E402

import db as dbmod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from stripe_gateway import FakeStripeGateway, set_gateway  # noqa: E402
import stripe_connect as sc  # noqa: E402
import main  # noqa: E402

set_gateway(FakeStripeGateway())
dbmod.init_db()
c = TestClient(main.app)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


PW = "hunter2-correct-horse-xyz"


def reg(u):
    c.post("/register_user", json={"username": u, "password": PW})


def login(u):
    tok = c.post("/login", data={"username": u, "password": PW}).json()["access_token"]
    return {"Authorization": "Bearer " + tok}


# ========== A. no silent fake-gateway fallback in a served process (#9) ==========
_saved = {k: os.environ.get(k) for k in ("STRIPE_GATEWAY", "PETABYTE_OFFLINE_TEST",
                                         "ENVIRONMENT")}
try:
    os.environ.pop("STRIPE_GATEWAY", None)
    os.environ.pop("PETABYTE_OFFLINE_TEST", None)
    _raised = False
    try:
        main._assert_gateway_explicit()
    except RuntimeError:
        _raised = True
    ok("served process REFUSES to start with STRIPE_GATEWAY unset (no silent fake money)",
       _raised)

    os.environ.pop("STRIPE_GATEWAY", None)
    os.environ["PETABYTE_OFFLINE_TEST"] = "1"
    main._assert_gateway_explicit()
    ok("PETABYTE_OFFLINE_TEST=1 pins the fake gateway explicitly (no raise)",
       os.environ.get("STRIPE_GATEWAY") == "fake")

    os.environ.pop("PETABYTE_OFFLINE_TEST", None)
    for g in ("real", "fake"):
        os.environ["STRIPE_GATEWAY"] = g
        main._assert_gateway_explicit()      # must not raise
    ok("explicit STRIPE_GATEWAY=real|fake is accepted", True)

    # an INVALID (non-empty) gateway value is a config error — even with offline set
    os.environ["STRIPE_GATEWAY"] = "typo"
    os.environ["PETABYTE_OFFLINE_TEST"] = "1"
    _raised = False
    try:
        main._assert_gateway_explicit()
    except RuntimeError:
        _raised = True
    ok("an invalid STRIPE_GATEWAY value is rejected (offline override cannot mask it)", _raised)

    # an INVALID PETABYTE_OFFLINE_TEST value (outside unset/0/1/true/false) is rejected
    os.environ.pop("STRIPE_GATEWAY", None)
    os.environ["PETABYTE_OFFLINE_TEST"] = "yes"
    _raised = False
    try:
        main._assert_gateway_explicit()
    except RuntimeError:
        _raised = True
    ok("an invalid PETABYTE_OFFLINE_TEST value is rejected", _raised)

    # offline test is NEVER allowed to pin fake in production
    os.environ.pop("STRIPE_GATEWAY", None)
    os.environ["PETABYTE_OFFLINE_TEST"] = "1"
    os.environ["ENVIRONMENT"] = "production"
    _raised = False
    try:
        main._assert_gateway_explicit()
    except RuntimeError:
        _raised = True
    ok("PETABYTE_OFFLINE_TEST is refused in production (no fake gateway in prod)", _raised)
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    set_gateway(FakeStripeGateway())         # keep the rest of the suite on the fake gateway


# ========== B. ConnectedAccount gateway_mode anti-contamination (#10) ==========
s = dbmod.SessionLocal()
u1 = dbmod.create_user(s, "safe_seller1", PW); s.commit()
ca = sc.get_or_create_connected_account(s, u1, country="US", email="s1@x.com")
ok("new account under the fake gateway is stamped gateway_mode='fake'",
   ca.gateway_mode == "fake" and ca.stripe_account_id.startswith("acct_fake"))
ca_again = sc.get_or_create_connected_account(s, u1)
ok("same-mode reuse returns the SAME account (idempotent)",
   ca_again.stripe_account_id == ca.stripe_account_id)

# fake account under a (simulated) real gateway -> refuse
_orig_mode = sc._current_gateway_mode
sc._current_gateway_mode = lambda: "real"
_raised = False
try:
    sc.get_or_create_connected_account(s, u1)
except sc.ConnectedAccountModeMismatch:
    _raised = True
finally:
    sc._current_gateway_mode = _orig_mode
ok("a FAKE account is refused under the REAL gateway (fail closed, no contamination)", _raised)

# a real account under the fake gateway -> refuse
u2 = dbmod.create_user(s, "safe_seller2", PW); s.commit()
s.add(dbmod.ConnectedAccount(user_id=u2.id, stripe_account_id="acct_1RealAbc",
                             gateway_mode="real", onboarding_state="created")); s.commit()
_raised = False
try:
    sc.get_or_create_connected_account(s, u2)     # current gateway = fake
except sc.ConnectedAccountModeMismatch:
    _raised = True
ok("a REAL account is refused under the FAKE gateway", _raised)

# legacy fake-looking row (no marker) -> reused + backfilled
u3 = dbmod.create_user(s, "safe_seller3", PW); s.commit()
s.add(dbmod.ConnectedAccount(user_id=u3.id, stripe_account_id="acct_fake000777",
                             gateway_mode=None, onboarding_state="created")); s.commit()
ca3 = sc.get_or_create_connected_account(s, u3)
ok("legacy fake row is reused and backfilled to gateway_mode='fake'", ca3.gateway_mode == "fake")

# legacy real-looking row (no marker) under fake -> refuse (inferred from acct id)
u4 = dbmod.create_user(s, "safe_seller4", PW); s.commit()
s.add(dbmod.ConnectedAccount(user_id=u4.id, stripe_account_id="acct_1RealLegacy",
                             gateway_mode=None, onboarding_state="created")); s.commit()
_raised = False
try:
    sc.get_or_create_connected_account(s, u4)
except sc.ConnectedAccountModeMismatch:
    _raised = True
ok("legacy REAL-looking row is refused under the FAKE gateway (id-prefix inference)", _raised)
s.close()


# ========== C. connect endpoint ergonomics + onboarding URL validation (#11, #12) ==========
reg("safe_conn_seller")
c.post("/change_role", headers=login("safe_conn_seller"), json={"role": "seller"})
r = c.post("/payments/connect/account", headers=login("safe_conn_seller"))   # NO json body
ok("connect/account accepts an EMPTY body (not 422)", r.status_code == 200)

for k in ("PUBLIC_BASE_URL", "CONNECT_RETURN_URL", "CONNECT_REFRESH_URL"):
    os.environ.pop(k, None)
r = c.post("/payments/connect/onboarding-link", headers=login("safe_conn_seller"))  # no body/base
ok("onboarding-link fails closed with a clear code when no return URL is configured",
   r.status_code == 503 and "CONNECT_RETURN_URL_MISSING" in r.text)

os.environ["PUBLIC_BASE_URL"] = "https://safe.petabyte.market"
r = c.post("/payments/connect/onboarding-link", headers=login("safe_conn_seller"))
ok("onboarding-link returns an https url once PUBLIC_BASE_URL is set",
   r.status_code == 200 and r.json()["url"].startswith("https://"))
os.environ.pop("PUBLIC_BASE_URL", None)


# ========== D. 14-day payout hold is clock-injectable + boundary-exact (#26/STEP13) ==========
class _Obl:
    def __init__(self, available_at, state="accrued"):
        self.available_at = available_at
        self.state = state


_cap = datetime(2026, 1, 1, tzinfo=timezone.utc)
_avail = _cap + timedelta(days=14)
_o = _Obl(_avail)
ok("day 0: held", not dbmod.payout_hold_elapsed(_o, now=_cap))
ok("day 13: held", not dbmod.payout_hold_elapsed(_o, now=_cap + timedelta(days=13)))
ok("1 second before the 14-day mark: held",
   not dbmod.payout_hold_elapsed(_o, now=_avail - timedelta(seconds=1)))
ok("exactly at the 14-day boundary: eligible", dbmod.payout_hold_elapsed(_o, now=_avail))
ok("day 15: eligible", dbmod.payout_hold_elapsed(_o, now=_cap + timedelta(days=15)))
ok("a PAID obligation is never re-eligible",
   not dbmod.payout_hold_elapsed(_Obl(_cap, state="paid"), now=_cap + timedelta(days=99)))
ok("no hold configured (available_at is None) -> eligible",
   dbmod.payout_hold_elapsed(_Obl(None), now=_cap))
ok("naive available_at is normalized to UTC (SQLite round-trip safety)",
   dbmod.payout_hold_elapsed(_Obl(datetime(2026, 1, 15)),
                             now=datetime(2026, 1, 16, tzinfo=timezone.utc)))

print(f"\n=== e2e_safety: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
