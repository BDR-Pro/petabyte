"""Offline tests for 'Add funds' wallet top-ups via Stripe Checkout (fake gateway).

Covers: starting a top-up returns a hosted-checkout URL + the money mode; amount bounds;
the sandbox simulate-pay credits the wallet exactly once (idempotent); the
checkout.session.completed webhook credits the wallet; and a duplicate webhook does not
double-credit.

Run: python wallet_test.py
"""
import os
import json
import time
import hmac
import hashlib

from cryptography.fernet import Fernet

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./wallet_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_pay"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_wallet"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["STRIPE_MODE"] = "test"
os.environ["PAYMENTS_MODE"] = "sandbox"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_x"
os.environ["STRIPE_PUBLISHABLE_KEY"] = "pk_test_x"
os.environ["NOTIFY_STUB"] = "true"

for f in ("wallet_test.db", "wallet_test.db-wal", "wallet_test.db-shm"):
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


def stripe_webhook(event):
    event.setdefault("object", "event")
    payload = json.dumps(event, separators=(",", ":")).encode()
    ts = int(time.time())
    sig = hmac.new(b"whsec_wallet", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return c.post("/webhooks/stripe", content=payload,
                  headers={"Stripe-Signature": f"t={ts},v1={sig}",
                           "Content-Type": "application/json"})


def balance(bt):
    return c.get("/wallet", headers=bt).json()["balance"]


c.post("/register_user", json={"username": "buyerw", "password": "pw-correct-horse-1"})
tok = c.post("/login", data={"username": "buyerw", "password": "pw-correct-horse-1"}).json()["access_token"]
BT = {"Authorization": f"Bearer {tok}"}

# ---- start a top-up: opens Stripe checkout, returns URL + mode ----
r = c.post("/wallet/topup", headers=BT, json={"amount_minor": 2500})
ok("start top-up returns 200", r.status_code == 200)
j = r.json()
ok("top-up returns a Stripe checkout URL", str(j.get("checkout_url", "")).startswith("http"))
ok("top-up is stamped TEST (demo) mode", j.get("mode") == "TEST" and j.get("test_mode") is True)
ok("top-up echoes the amount", j.get("amount_minor") == 2500)
tid = j["topup_id"]

# amount bounds
ok("amount below the minimum is rejected (400)",
   c.post("/wallet/topup", headers=BT, json={"amount_minor": 100}).status_code == 400)

# ---- sandbox simulate-pay credits the wallet once ----
bal0 = balance(BT)
sp = c.post(f"/wallet/topup/{tid}/simulate-pay", headers=BT)
ok("simulate-pay succeeds and reports credited", sp.status_code == 200 and sp.json().get("credited") is True)
bal1 = balance(BT)
ok("wallet credited by the top-up amount ($25.00)", round(bal1 - bal0, 2) == 25.00)
ok("top-up status is paid", c.get(f"/wallet/topup/{tid}", headers=BT).json()["status"] == "paid")

# idempotent: paying again does not double-credit
c.post(f"/wallet/topup/{tid}/simulate-pay", headers=BT)
ok("re-paying the same top-up does NOT double-credit", balance(BT) == bal1)

# ---- webhook path credits the wallet ----
r2 = c.post("/wallet/topup", headers=BT, json={"amount_minor": 1000}).json()
sid2, tid2 = r2["session_id"], r2["topup_id"]
bal2 = balance(BT)
evt = {"id": "evt_w1", "type": "checkout.session.completed",
       "data": {"object": {"id": sid2, "payment_status": "paid",
                           "payment_intent": "pi_web_1",
                           "metadata": {"purpose": "wallet_topup", "topup_id": tid2}}}}
wr = stripe_webhook(evt)
ok("checkout.session.completed webhook accepted", wr.status_code == 200)
bal3 = balance(BT)
ok("webhook credited the wallet ($10.00)", round(bal3 - bal2, 2) == 10.00)

# duplicate webhook (new event id, same session) must not double-credit
evt2 = json.loads(json.dumps(evt)); evt2["id"] = "evt_w2"
stripe_webhook(evt2)
ok("a duplicate webhook does not double-credit", balance(BT) == bal3)

# an unpaid session credits nothing
r3 = c.post("/wallet/topup", headers=BT, json={"amount_minor": 700}).json()
bal4 = balance(BT)
evt3 = {"id": "evt_w3", "type": "checkout.session.completed",
        "data": {"object": {"id": r3["session_id"], "payment_status": "unpaid",
                            "metadata": {"purpose": "wallet_topup", "topup_id": r3["topup_id"]}}}}
stripe_webhook(evt3)
ok("an UNPAID session credits nothing", balance(BT) == bal4)

print(f"\n=== wallet: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
for f in ("wallet_test.db", "wallet_test.db-wal", "wallet_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
raise SystemExit(1 if _fail else 0)
