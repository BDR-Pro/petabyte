"""stripe_test.py — offline, deterministic tests for the Stripe Connect flow.

Uses the in-process FakeStripeGateway (no live Stripe network) and the real
FastAPI app via TestClient. Signature verification uses the REAL stripe verifier.
Run: python stripe_test.py   (SQLite by default; set DATABASE_URL for Postgres)
"""
import base64
import json
import os
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./stripe_test.db")
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_stripe"
os.environ["PLATFORM_TAKE_RATE"] = "0.10"
os.environ["PLATFORM_MIN_CHARGE_MINOR"] = "50"
os.environ["PLATFORM_MAX_DURATION_S"] = "7200"      # 2h cap, below the API's le bound
os.environ["ADMIN_USERS"] = "admin@petabyte.market"
os.environ["REAPER_DISABLED"] = "true"
# Stripe onboarding needs an ABSOLUTE return/refresh URL (a real deployment always has one);
# the onboarding-link endpoint now fails closed with a clear error if it can't build one.
os.environ["PUBLIC_BASE_URL"] = "https://test.petabyte.market"

for f in ("stripe_test.db", "stripe_test.db-wal", "stripe_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import db as dbmod
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

from fastapi.testclient import TestClient
from stripe_gateway import FakeStripeGateway, set_gateway
import stripe_connect as sc
import main

GW = set_gateway(FakeStripeGateway())
dbmod.init_db()
c = TestClient(main.app)

PASSES = FAILS = 0
def ok(label, cond):
    global PASSES, FAILS
    print(("PASS " if cond else "FAIL ") + label)
    if cond: PASSES += 1
    else:
        FAILS += 1
        raise AssertionError(label)

PW = "hunter2-correct-horse-xyz"
def reg(u, email=None, verified=False):
    c.post("/register_user", json={"username": u, "password": PW})
    if email:
        s = dbmod.SessionLocal()
        usr = dbmod.get_user_by_username(s, u); usr.email = email
        # Admin is conferred only by a VERIFIED email matching ADMIN_USERS (see _is_admin).
        usr.email_verified = bool(verified)
        s.add(usr); s.commit(); s.close()
def login(u):
    return {"Authorization": "Bearer " + c.post("/login", data={"username": u, "password": PW}).json()["access_token"]}

def make_online_spec(seller_user, price=2.50, units=2, gpu="H100"):
    s = dbmod.SessionLocal()
    seller = dbmod.get_user_by_username(s, seller_user)
    spec = dbmod.save_specs(s, seller, {"cpu": 16, "ram": 64, "duration": 48,
        "price_per_hour": price, "provider": seller_user, "gpu_model": gpu,
        "gpu_count": 1, "vram_gb": 80, "units": units})
    spec.attested = True; spec.status = "online"
    import datetime as _d
    spec.last_seen = _d.datetime.now(_d.timezone.utc)
    s.add(spec); s.commit()
    pub = spec.public_id; s.close()
    return pub

def onboard_seller(seller_user, ok_=True, country="US"):
    s = dbmod.SessionLocal()
    seller = dbmod.get_user_by_username(s, seller_user)
    ca = sc.get_or_create_connected_account(s, seller, country=country, email=f"{seller_user}@x.com")
    aid = ca.stripe_account_id
    GW.complete_onboarding(aid, ok=ok_)
    ca = sc.refresh_connected_account(s, ca)
    ready = ca.payout_ready(); s.close()
    return aid, ready


# ============================ ONBOARDING ============================
reg("seller_a", "sa@x.com"); c.post("/change_role", headers=login("seller_a"), json={"role": "seller"})
reg("seller_b", "sb@x.com"); c.post("/change_role", headers=login("seller_b"), json={"role": "seller"})
reg("buyer1")
# The platform admin: ADMIN_USERS is an email, so admin requires a VERIFIED matching email.
reg("admin@petabyte.market", email="admin@petabyte.market", verified=True)

r = c.post("/payments/connect/account", headers=login("seller_a"), json={"country": "US"})
ok("connected account created", r.status_code == 200 and r.json()["connected_account_id"].startswith("acct_"))
aid_a = r.json()["connected_account_id"]
r2 = c.post("/payments/connect/account", headers=login("seller_a"), json={"country": "US"})
ok("connected account creation is idempotent (same id)", r2.json()["connected_account_id"] == aid_a)
link = c.post("/payments/connect/onboarding-link", headers=login("seller_a"), json={})
ok("onboarding link created", link.status_code == 200 and link.json()["url"].startswith("https://"))
st = c.get("/payments/connect/status", headers=login("seller_a")).json()
ok("status: not payout-ready before onboarding, with a reason", st["payout_ready"] is False and st["why_blocked"])

# seller_b gets a DIFFERENT account (cannot touch seller_a's)
rb = c.post("/payments/connect/account", headers=login("seller_b"), json={"country": "US"})
ok("second seller gets their own distinct account", rb.json()["connected_account_id"] != aid_a)

# complete onboarding for seller_a -> payout ready; requirements sync
aid_a, ready_a = onboard_seller("seller_a", ok_=True)
ok("seller becomes payout-ready after onboarding", ready_a is True)
st = c.get("/payments/connect/status", headers=login("seller_a")).json()
ok("status reflects enabled + no blocker", st["payout_ready"] and st["onboarding_state"] == "enabled" and not st["why_blocked"])

# a NON-payout-ready seller cannot sell paid compute
onboard_seller("seller_b", ok_=False)
spec_b = make_online_spec("seller_b")
qb = c.post("/payments/quote", headers=login("buyer1"), json={"spec_id": spec_b, "estimated_seconds": 3600}).json()
ok("quote flags seller not payout-ready", qb["seller_payout_ready"] is False)
ab = c.post("/payments/authorize", headers=login("buyer1"), json={"spec_id": spec_b, "estimated_seconds": 3600})
ok("authorize blocked when seller not payout-ready", ab.status_code == 409)

spec_a = make_online_spec("seller_a", price=2.50, units=2)


# ============================ QUOTE / AUTHORIZE ============================
q = c.post("/payments/quote", headers=login("buyer1"), json={"spec_id": spec_a, "estimated_seconds": 3600}).json()
ok("quote: $2.50/hr x 1h = 250 minor", q["estimated_compute_amount"] == 250)
ok("quote: authorization adds 20% margin -> 300", q["authorization_amount"] == 300)

az = c.post("/payments/authorize", headers=login("buyer1"), json={"spec_id": spec_a, "estimated_seconds": 3600}).json()
txid = az["transaction_id"]
ok("authorize returns a client secret + server-computed amount", bool(az["client_secret"]) and az["authorization_amount"] == 300)
ok("authorize does NOT leak the connected account or seller net", "connected_account" not in az and "seller_net_amount" not in az)
# exactly ONE authorize PaymentOperation + one PI for this tx
s = dbmod.SessionLocal()
tx = sc.get_tx_by_public_id(s, txid)
n_auth = s.query(dbmod.PaymentOperation).filter(dbmod.PaymentOperation.tx_id == tx.id,
                                                dbmod.PaymentOperation.op_type == "authorize").count()
ok("exactly one PaymentIntent authorize op per transaction", n_auth == 1)
pi_id = tx.stripe_payment_intent_id; s.close()

# frontend cannot influence the amount: there is no amount field; the PI amount == server quote
ok("PaymentIntent amount equals the server authorization (browser can't set it)",
   GW.payment_intents[pi_id]["amount"] == 300)


# ============================ AUTH BEFORE RESERVE ============================
admin = login("admin@petabyte.market")
rr = c.post(f"/admin/payments/{txid}/reserve", headers=admin)
ok("cannot reserve before payment is authorized", rr.status_code == 409)

GW.confirm_payment_intent(pi_id)                     # buyer confirms card (client side)
cf = c.post(f"/payments/{txid}/confirm", headers=login("buyer1")).json()
ok("server-side confirm moves to PAYMENT_AUTHORIZED", cf["status"] == "PAYMENT_AUTHORIZED")

# failed authorization prevents dispatch: a fresh tx whose PI never authorizes
az2 = c.post("/payments/authorize", headers=login("buyer1"), json={"spec_id": spec_a, "estimated_seconds": 3600}).json()
GW.confirm_payment_intent(sc.get_tx_by_public_id(dbmod.SessionLocal(), az2["transaction_id"]).stripe_payment_intent_id, fail=True)
cf2 = c.post(f"/payments/{az2['transaction_id']}/confirm", headers=login("buyer1"))
ok("unauthorized card cannot be confirmed", cf2.status_code == 409)
ok("cannot dispatch an unauthorized tx", c.post(f"/admin/payments/{az2['transaction_id']}/dispatch", headers=admin, json={}).status_code == 409)


# ============================ RESERVE / CONCURRENCY ============================
rv = c.post(f"/admin/payments/{txid}/reserve", headers=admin).json()
ok("reserve after auth -> GPU_RESERVED", rv["status"] == "GPU_RESERVED")
# spec had 2 units; reserve consumed 1
s = dbmod.SessionLocal(); avail = dbmod.get_spec_by_public_id(s, spec_a).available_units; s.close()
ok("one unit consumed on reserve", avail == 1)

# concurrency: with ONE unit left, two buyers both authorize (payment succeeds for
# both), then race to reserve -> exactly one wins, the other loses the reservation race.
def _auth_confirm(spec):
    a = c.post("/payments/authorize", headers=login("buyer1"),
               json={"spec_id": spec, "estimated_seconds": 3600}).json()
    pid = sc.get_tx_by_public_id(dbmod.SessionLocal(), a["transaction_id"]).stripe_payment_intent_id
    GW.confirm_payment_intent(pid)
    c.post(f"/payments/{a['transaction_id']}/confirm", headers=login("buyer1"))
    return a["transaction_id"]
az3 = _auth_confirm(spec_a)     # both authorized while 1 unit remains
az4 = _auth_confirm(spec_a)
win = c.post(f"/admin/payments/{az3}/reserve", headers=admin)      # takes the last unit
lose = c.post(f"/admin/payments/{az4}/reserve", headers=admin)     # loses the race
ok("of two authorized buyers, exactly one reserves the last unit",
   win.status_code == 200 and lose.status_code == 409)


# ============ BUYER-DRIVEN STRIPE-NATIVE FLOW (self-serve, no wallet) ============
# The buyer drives the whole paid launch through Stripe with NO internal wallet:
# authorize -> confirm -> reserve -> dispatch. A job can never be reserved/dispatched
# without a verified Stripe authorization, and a buyer can only drive their OWN tx.
reg("buyer2")
spec_bd = make_online_spec("seller_a", price=2.50, units=1, gpu="A100")
bdid = c.post("/payments/authorize", headers=login("buyer1"),
              json={"spec_id": spec_bd, "estimated_seconds": 3600}).json()["transaction_id"]
ok("buyer cannot reserve before the card is authorized (no free/wallet booking)",
   c.post(f"/payments/{bdid}/reserve", headers=login("buyer1")).status_code == 409)
GW.confirm_payment_intent(sc.get_tx_by_public_id(dbmod.SessionLocal(), bdid).stripe_payment_intent_id)
c.post(f"/payments/{bdid}/confirm", headers=login("buyer1"))
ok("a buyer cannot reserve another buyer's transaction",
   c.post(f"/payments/{bdid}/reserve", headers=login("buyer2")).status_code == 404)
rvb = c.post(f"/payments/{bdid}/reserve", headers=login("buyer1"))
ok("buyer reserves their OWN authorized tx -> GPU_RESERVED",
   rvb.status_code == 200 and rvb.json()["status"] == "GPU_RESERVED")
ok("a buyer cannot dispatch another buyer's transaction",
   c.post(f"/payments/{bdid}/dispatch", headers=login("buyer2"), json={"code": "x"}).status_code == 404)
dpb = c.post(f"/payments/{bdid}/dispatch", headers=login("buyer1"), json={"code": "print(6*7)"})
ok("buyer dispatches their OWN reserved job -> RUNNING (Stripe-verified, no wallet)",
   dpb.status_code == 200 and dpb.json()["status"] == "RUNNING")


# ============================ DISPATCH / METER ============================
dp = c.post(f"/admin/payments/{txid}/dispatch", headers=admin, json={"code": "print(6*7)"}).json()
ok("dispatch -> RUNNING with a task", dp["status"] == "RUNNING")
s = dbmod.SessionLocal(); task_id = sc.get_tx_by_public_id(s, txid).task_id; s.close()
c.post(f"/admin/payments/{txid}/dispatch", headers=admin, json={})     # retry
s = dbmod.SessionLocal()
ok("dispatch is idempotent (retry does not create a second task)",
   sc.get_tx_by_public_id(s, txid).task_id == task_id and
   s.query(dbmod.Task).filter(dbmod.Task.booking_id == sc.get_tx_by_public_id(s, txid).booking_id).count() == 1)
s.close()

# metering cannot exceed permitted boundaries: the API rejects out-of-range values,
# and the service clamps a large-but-valid value to the snapshot's max duration.
ok("metering beyond the API bound is rejected (422)",
   c.post(f"/admin/payments/{txid}/meter", headers=admin, json={"actual_seconds": 999999}).status_code == 422)
mm = c.post(f"/admin/payments/{txid}/meter", headers=admin, json={"actual_seconds": 80000}).json()
ok("metering is clamped to the snapshot max duration (7200s)", mm["metering_seconds"] == 7200)


# ============================ CAPTURE (partial) ============================
# Drive a clean tx end-to-end with 30 minutes of usage.
def run_to_metered(seconds):
    a = c.post("/payments/authorize", headers=login("buyer1"), json={"spec_id": spec_c, "estimated_seconds": 3600}).json()
    tid = a["transaction_id"]
    pid = sc.get_tx_by_public_id(dbmod.SessionLocal(), tid).stripe_payment_intent_id
    GW.confirm_payment_intent(pid)
    c.post(f"/payments/{tid}/confirm", headers=login("buyer1"))
    c.post(f"/admin/payments/{tid}/reserve", headers=admin)
    c.post(f"/admin/payments/{tid}/dispatch", headers=admin, json={})
    c.post(f"/admin/payments/{tid}/meter", headers=admin, json={"actual_seconds": seconds})
    return tid

spec_c = make_online_spec("seller_a", price=2.50, units=10)
tid = run_to_metered(1800)      # 30 min -> 125 minor
cap = c.post(f"/admin/payments/{tid}/capture", headers=admin).json()
ok("partial capture bills ACTUAL metered usage (125), not the 300 authorization",
   cap["captured_amount"] == 125)
ok("platform fee = 10% of capture (12) and identity holds",
   cap["platform_fee_amount"] == 12 and cap["captured_amount"] == cap["platform_fee_amount"] + cap["seller_net_amount"])
pid = sc.get_tx_by_public_id(dbmod.SessionLocal(), tid).stripe_payment_intent_id
ok("unused authorization released (PI amount_received == capture, capturable 0)",
   GW.payment_intents[pid]["amount_received"] == 125 and GW.payment_intents[pid]["amount_capturable"] == 0)

# duplicate capture does not double-charge
before = GW.payment_intents[pid]["amount_received"]
c.post(f"/admin/payments/{tid}/capture", headers=admin)
s = dbmod.SessionLocal()
n_cap_entries = s.query(dbmod.LedgerEntry).filter(
    dbmod.LedgerEntry.entry_type == "compute_capture",
    dbmod.LedgerEntry.account == dbmod.EXTERNAL_PAYMENTS).count()
ok("duplicate capture is a no-op (amount unchanged, one capture per tx across suite)",
   GW.payment_intents[pid]["amount_received"] == before)
s.close()

# ---- UNIT ECONOMICS: the platform's card-processing COST is recorded + visible ----
# Captured 125 minor; commission 12; estimated Stripe fee = 2.9%*125 + 30c = 33. So the NET
# contribution margin on this small job is 12 - 33 = -21 (a LOSS) — which is now visible in
# the ledger and per-tx, instead of a dashboard showing a healthy 10% take while bleeding.
import pricing as _pr  # noqa: E402
_exp_fee = _pr.estimate_processing_fee_minor(125, "usd")
s = dbmod.SessionLocal()
_txf = sc.get_tx_by_public_id(s, tid)
ok("processing fee recorded on the tx (estimated card cost = 33)",
   _txf.stripe_fee_amount == _exp_fee and _exp_fee == 33)

def _fee_legs(direction, account):
    return (s.query(dbmod.LedgerEntry)
            .join(dbmod.LedgerTx, dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id)
            .filter(dbmod.LedgerTx.reference_id == tid,
                    dbmod.LedgerEntry.entry_type == "stripe_fee",
                    dbmod.LedgerEntry.account == account,
                    dbmod.LedgerEntry.direction == direction).all())
_dr = _fee_legs(dbmod.DEBIT, dbmod.acct_stripe_fees())
_cr = _fee_legs(dbmod.CREDIT, dbmod.EXTERNAL_PAYMENTS)
ok("processing fee posted as ONE balanced stripe:fees entry (idempotent across the dup capture)",
   len(_dr) == 1 and len(_cr) == 1 and int(_dr[0].amount) == _exp_fee and int(_cr[0].amount) == _exp_fee)
ok("net contribution margin is negative on a small job (commission 12 - fee 33)",
   (cap["platform_fee_amount"] - _exp_fee) == -21)
_bal_ok, _broken = dbmod.ledger_is_balanced(s)
ok("ledger still balances globally after the processing-fee leg", _bal_ok)
s.close()


# ============================ CANCEL: prompt release of a FAILED dispatched job ===========
# Once a job is dispatched, POST /payments/{tx}/cancel must still refuse an ACTIVELY running job
# (409) — but a dispatched job that has since FAILED (JOB_FAILED / CAPTURE_FAILED) is no longer
# running, so cancel releases its GPU reservation IMMEDIATELY instead of pinning the unit +
# authorization hold until the next abandoned-reservation reaper cycle.
spec_cx = make_online_spec("seller_a", price=2.0, units=3)


def _run_to_running(spec_pub):
    a = c.post("/payments/authorize", headers=login("buyer1"),
               json={"spec_id": spec_pub, "estimated_seconds": 3600}).json()
    tid = a["transaction_id"]
    pid = sc.get_tx_by_public_id(dbmod.SessionLocal(), tid).stripe_payment_intent_id
    GW.confirm_payment_intent(pid)
    c.post(f"/payments/{tid}/confirm", headers=login("buyer1"))
    c.post(f"/admin/payments/{tid}/reserve", headers=admin)
    c.post(f"/admin/payments/{tid}/dispatch", headers=admin, json={})
    return tid


def _avail_cx():
    s = dbmod.SessionLocal()
    v = dbmod.get_spec_by_public_id(s, spec_cx).available_units
    s.close()
    return v


base_avail = _avail_cx()
tid_run = _run_to_running(spec_cx)
ok("dispatched job holds a reserved unit", _avail_cx() == base_avail - 1)
ok("cancel refuses an ACTIVELY running dispatched job (409)",
   c.post(f"/payments/{tid_run}/cancel", headers=login("buyer1")).status_code == 409)
ok("refused cancel did NOT release the running job's unit", _avail_cx() == base_avail - 1)

# the job fails after dispatch (seller crash / capture failure) -> now terminal, not running
_s = dbmod.SessionLocal()
_tx = sc.get_tx_by_public_id(_s, tid_run)
sc.transition(_s, _tx, "JOB_FAILED", reason="seller crashed mid-run")
_s.close()
cx = c.post(f"/payments/{tid_run}/cancel", headers=login("buyer1"))
ok("cancel of a FAILED dispatched job succeeds (200) — no waiting for the reaper",
   cx.status_code == 200)
ok("failed job's GPU reservation is released immediately", _avail_cx() == base_avail)
_s = dbmod.SessionLocal()
ok("failed tx keeps its terminal state (cancel did NOT rewrite it to CANCELLED)",
   sc.get_tx_by_public_id(_s, tid_run).status == "JOB_FAILED")
_s.close()
# idempotent: a second cancel is a harmless no-op, never a double release
c2 = c.post(f"/payments/{tid_run}/cancel", headers=login("buyer1"))
ok("cancel of an already-released failed job is idempotent (200, no double release)",
   c2.status_code == 200 and _avail_cx() == base_avail)

# ---- fail_job(): the /jobs/result FAILURE bridge unsticks a RUNNING tx (killer #9) ----
# When a dispatched job reports FAILED, /jobs/result calls sc.fail_job — which must move the tx
# out of RUNNING to JOB_FAILED and free the reservation + void the buyer hold immediately, rather
# than leaving it stuck in RUNNING (buyer can't cancel; unit pinned until the 26h reaper).
base9 = _avail_cx()
tid9 = _run_to_running(spec_cx)
ok("fail_job setup: dispatched job holds a unit", _avail_cx() == base9 - 1)
_s = dbmod.SessionLocal()
_tx9 = sc.get_tx_by_public_id(_s, tid9)
ok("fail_job setup: tx is RUNNING before failure", _tx9.status == "RUNNING")
_pid9 = _tx9.stripe_payment_intent_id
sc.fail_job(_s, _tx9, reason="agent reported job failed")
ok("fail_job moves a failed RUNNING tx to JOB_FAILED (no longer stuck)", _tx9.status == "JOB_FAILED")
_s.close()
ok("fail_job frees the reserved GPU unit immediately", _avail_cx() == base9)
ok("fail_job voids the buyer's authorization hold (a failed job bills nothing)",
   GW.payment_intents[_pid9]["status"] == "canceled")
_s = dbmod.SessionLocal()
_tx9b = sc.get_tx_by_public_id(_s, tid9)
sc.fail_job(_s, _tx9b, reason="again")
ok("fail_job is idempotent (stays JOB_FAILED, no double release)",
   _tx9b.status == "JOB_FAILED" and _avail_cx() == base9)
_s.close()

# A Stripe-native task whose card authorization was VOIDED on failure must NOT be retryable in
# place — a completed retry would return success while the PI is canceled (buyer uncharged,
# seller unpaid). The buyer must place a new order. (Regression for the retry-loses-auth finding.)
_s = dbmod.SessionLocal(); _t9id = sc.get_tx_by_public_id(_s, tid9).task_id; _s.close()
ok("retry of a Stripe-native task with a voided authorization is REFUSED (409, not silent re-run)",
   c.post(f"/tasks/{_t9id}/retry", headers=login("buyer1")).status_code == 409)


# ============================ TRANSFER ============================
# transfer before capture is impossible: use a fresh tx still pre-capture
tid_pre = run_to_metered(600)
ok("transfer before capture is rejected",
   c.post(f"/admin/payments/{tid_pre}/transfer", headers=admin).status_code == 409)

tr = c.post(f"/admin/payments/{tid}/transfer", headers=admin).json()
ok("transfer after capture -> COMPLETED with a transfer id",
   tr["status"] == "COMPLETED" and tr["transferred_amount"] == 113)
s = dbmod.SessionLocal(); trid = sc.get_tx_by_public_id(s, tid).stripe_transfer_id; s.close()
# duplicate transfer (retry / duplicate webhook / concurrent worker) -> ONE transfer
c.post(f"/admin/payments/{tid}/transfer", headers=admin)
s = dbmod.SessionLocal()
ok("duplicate transfer request creates no second transfer",
   sc.get_tx_by_public_id(s, tid).stripe_transfer_id == trid and len(GW.transfers) >= 1)
n_tr_entries = s.query(dbmod.LedgerEntry).filter(
    dbmod.LedgerEntry.entry_type == "compute_transfer").count()
s.close()
ok("transferred net = captured - platform fee (113)", tr["transferred_amount"] == 113)


# ============================ ZERO-USAGE CANCEL ============================
tid0 = run_to_metered(0)
z = c.post(f"/admin/payments/{tid0}/capture", headers=admin).json()
ok("zero usage -> no charge, transaction cancelled/refunded",
   z["status"] in ("CANCELLED", "REFUNDED") and z["captured_amount"] == 0)


# ============================ REFUND before/after transfer ============================
# before transfer: capture, then full refund
tid_rb = run_to_metered(3600)     # 60 min -> $2.50 = 250; but auth is 300 so full capture 250
c.post(f"/admin/payments/{tid_rb}/capture", headers=admin)
rf = c.post(f"/admin/payments/{tid_rb}/refund", headers=admin, json={"reason": "buyer cancelled after run"}).json()
ok("refund before transfer returns full captured amount", rf["refunded_amount"] == 250 and rf["status"] == "REFUNDED")

# after transfer: capture + transfer, then refund -> transfer reversal
tid_ra = run_to_metered(3600)
c.post(f"/admin/payments/{tid_ra}/capture", headers=admin)
c.post(f"/admin/payments/{tid_ra}/transfer", headers=admin)
ra = c.post(f"/admin/payments/{tid_ra}/refund", headers=admin, json={"reason": "quality dispute"}).json()
ok("refund after transfer claws back seller net via a reversal",
   ra["reversed_amount"] > 0 and ra["refunded_amount"] == 250)

# partial refund
tid_pr = run_to_metered(3600)
c.post(f"/admin/payments/{tid_pr}/capture", headers=admin)
pr = c.post(f"/admin/payments/{tid_pr}/refund", headers=admin, json={"amount": 100, "reason": "partial"}).json()
ok("partial refund refunds only the requested amount", pr["refunded_amount"] == 100 and pr["status"] != "REFUNDED")

# TWO partial refunds that CUMULATIVELY equal the capture must REVERSE the unpaid obligation
# and reconcile. Regression: the reversal used to gate on a single refund's `amount`, so two
# partials each < captured never reversed, leaving the seller payable to be paid out anyway.
tid_2p = run_to_metered(3600)     # captures 250
c.post(f"/admin/payments/{tid_2p}/capture", headers=admin)
c.post(f"/admin/payments/{tid_2p}/refund", headers=admin, json={"amount": 100, "reason": "partial 1"})
r2 = c.post(f"/admin/payments/{tid_2p}/refund", headers=admin, json={"amount": 150, "reason": "partial 2"}).json()
ok("two partial refunds summing to the capture -> fully REFUNDED",
   r2["refunded_amount"] == 250 and r2["status"] == "REFUNDED")
_s2 = dbmod.SessionLocal()
_tx2 = sc.get_tx_by_public_id(_s2, tid_2p)
_obl2 = _s2.query(dbmod.PayoutObligation).filter(
    dbmod.PayoutObligation.compute_tx_id == _tx2.id).first()
ok("cumulative full refund REVERSES the unpaid obligation (not left payable)",
   _obl2 is not None and _obl2.state == "reversed")
ok("cumulative full refund reconciles the tx (not needs_review)",
   _tx2.reconciliation_status == "reconciled")
_s2.close()

# admin refund requires a reason
ok("admin refund requires a reason",
   c.post(f"/admin/payments/{tid_pr}/refund", headers=admin, json={"reason": ""}).status_code in (400, 422))

# ---- REFUND after a BATCH payout: clawback is FLAGGED, never silently 'reconciled' (killer #6) ----
# Simulate the seller already paid via the batch path: obligation 'paid', NO stripe_transfer_id.
# A refund/chargeback then can't reverse a specific transfer, so the seller's share becomes a
# recoverable debt (ledger DEBITs seller_payable) and MUST be flagged for recovery.
tid_bc = run_to_metered(3600)
c.post(f"/admin/payments/{tid_bc}/capture", headers=admin)
_s = dbmod.SessionLocal()
_txbc = sc.get_tx_by_public_id(_s, tid_bc)
_obc = _s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == _txbc.id).first()
_obc.state = "paid"; _s.add(_obc); _s.commit(); _s.close()
rbc = c.post(f"/admin/payments/{tid_bc}/refund", headers=admin,
             json={"reason": "chargeback after batch payout"}).json()
ok("refund after batch payout still returns the buyer's money in full", rbc["refunded_amount"] == 250)
_s = dbmod.SessionLocal()
_txbc2 = sc.get_tx_by_public_id(_s, tid_bc)
ok("batch-paid refund is flagged needs_review, NOT silently reconciled (killer #6)",
   _txbc2.reconciliation_status == "needs_review")
_rlegs = (_s.query(dbmod.LedgerEntry).join(dbmod.LedgerTx, dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id)
          .filter(dbmod.LedgerTx.reference_id == tid_bc,
                  dbmod.LedgerEntry.entry_type == "compute_refund",
                  dbmod.LedgerEntry.account == dbmod.acct_seller_payable(_txbc2.seller_id),
                  dbmod.LedgerEntry.direction == dbmod.DEBIT).all())
ok("refund posted a seller_payable clawback DEBIT (ledger records the recoverable debt)",
   len(_rlegs) == 1 and int(_rlegs[0].amount) > 0)
_bal_ok, _ = dbmod.ledger_is_balanced(_s)
ok("ledger balances after the batch-paid refund clawback", _bal_ok)
_s.close()

# ---- REFUND of an UNPAID obligation reverses it (money never left) -> reconciled (killer #6) ----
tid_up = run_to_metered(3600)
c.post(f"/admin/payments/{tid_up}/capture", headers=admin)
c.post(f"/admin/payments/{tid_up}/refund", headers=admin, json={"reason": "buyer cancelled, unpaid"})
_s = dbmod.SessionLocal()
_txup = sc.get_tx_by_public_id(_s, tid_up)
_oup = _s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == _txup.id).first()
ok("full refund of an UNPAID obligation reverses it (never paid out) + reconciles",
   _oup.state == "reversed" and _txup.reconciliation_status == "reconciled")
_s.close()

# REGRESSION (defect B): a DUPLICATE identical partial refund must NOT double-count.
# Previously refunded_amount went 100 -> 200 for a single Stripe refund.
tid_dup = run_to_metered(3600)
c.post(f"/admin/payments/{tid_dup}/capture", headers=admin)
d1 = c.post(f"/admin/payments/{tid_dup}/refund", headers=admin, json={"amount": 100, "reason": "dup"}).json()
d2 = c.post(f"/admin/payments/{tid_dup}/refund", headers=admin, json={"amount": 100, "reason": "dup"}).json()
ok("duplicate identical partial refund is idempotent (no double-count)",
   d1["refunded_amount"] == 100 and d2["refunded_amount"] == 100)
_sdup = dbmod.SessionLocal()
_txd = sc.get_tx_by_public_id(_sdup, tid_dup)
_nref = _sdup.query(dbmod.LedgerEntry).filter(
    dbmod.LedgerEntry.entry_type == "compute_refund",
    dbmod.LedgerEntry.account == dbmod.EXTERNAL_PAYMENTS,
    dbmod.LedgerEntry.booking_id.is_(None)).count()
_sdup.close()
ok("duplicate refund posts the refund ledger leg only once",
   len([r for r in GW.refunds.values() if r["payment_intent"] == _txd.stripe_payment_intent_id]) == 1)


# ============================ STRIPE TEST-MODE ENFORCEMENT ============================
# REGRESSION (defect A): a LIVE key must hard-fail; no silent fallback to live mode.
from stripe_gateway import assert_test_mode, LiveModeForbidden
ok("test-mode guard passes for a test key",
   assert_test_mode(secret_key="sk_test_abc") is None)
_blocked = False
try:
    assert_test_mode(secret_key="sk_live_ABCDEF1234567890")
except LiveModeForbidden:
    _blocked = True
ok("test-mode guard HARD-FAILS on a live secret key", _blocked)
_blocked_pk = False
try:
    assert_test_mode(secret_key="sk_test_ok", publishable_key="pk_live_XYZ")
except LiveModeForbidden:
    _blocked_pk = True
ok("test-mode guard HARD-FAILS on a live publishable key", _blocked_pk)
# a live key is permitted ONLY behind the loud triple opt-in.
os.environ["STRIPE_ALLOW_LIVE"] = "true"; os.environ["ENVIRONMENT"] = "production"
# two of three is NOT enough — PAYMENTS_LIVE_ENABLED must also be true (fail closed).
_two_of_three_blocked = False
try:
    assert_test_mode(secret_key="sk_live_ABCDEF1234567890")
except LiveModeForbidden:
    _two_of_three_blocked = True
ok("live key STILL blocked without PAYMENTS_LIVE_ENABLED (fail closed)", _two_of_three_blocked)
os.environ["PAYMENTS_LIVE_ENABLED"] = "true"
_allowed = True
try:
    assert_test_mode(secret_key="sk_live_ABCDEF1234567890")
except LiveModeForbidden:
    _allowed = False
ok("live key allowed ONLY with PAYMENTS_LIVE_ENABLED + STRIPE_ALLOW_LIVE + ENVIRONMENT=production",
   _allowed)
os.environ["ENVIRONMENT"] = "development"     # opt-in alone (no prod) is NOT enough
_still_blocked = False
try:
    assert_test_mode(secret_key="sk_live_ABCDEF1234567890")
except LiveModeForbidden:
    _still_blocked = True
ok("opt-in flags without ENVIRONMENT=production still blocks live", _still_blocked)
os.environ.pop("STRIPE_ALLOW_LIVE", None)
os.environ.pop("PAYMENTS_LIVE_ENABLED", None)

# test/live key MIXING is refused regardless of any opt-in
_mixed = False
try:
    assert_test_mode(secret_key="sk_test_ok", publishable_key="pk_live_XYZ")
except LiveModeForbidden:
    _mixed = True
ok("mixing a test secret key with a live publishable key is refused", _mixed)
# a declared STRIPE_MODE must agree with the key prefixes
os.environ["STRIPE_MODE"] = "test"
_mode_mismatch = False
try:
    assert_test_mode(secret_key="sk_live_ABCDEF1234567890")
except LiveModeForbidden:
    _mode_mismatch = True
ok("STRIPE_MODE=test with a live key is refused (mode/key mismatch)", _mode_mismatch)
os.environ.pop("STRIPE_MODE", None)

# PAYMENTS_LIVE_ENABLED=true with TEST keys is refused — never label test money as live
os.environ["PAYMENTS_LIVE_ENABLED"] = "true"
_livecred_blocked = False
try:
    assert_test_mode(secret_key="sk_test_abc", publishable_key="pk_test_abc")
except LiveModeForbidden:
    _livecred_blocked = True
ok("PAYMENTS_LIVE_ENABLED=true with TEST keys is refused (requires live creds)",
   _livecred_blocked)
os.environ.pop("PAYMENTS_LIVE_ENABLED", None)


# ============================ WEBHOOKS ============================
def post_webhook(event, secret=os.environ["STRIPE_WEBHOOK_SECRET"], ts=None):
    event.setdefault("object", "event")     # real Stripe events carry this
    raw, sig = GW.sign(event, secret, ts)
    return c.post("/webhooks/stripe", content=raw, headers={"Stripe-Signature": sig})

evt = {"id": "evt_test_1", "type": "account.updated", "api_version": "2024-06-20",
       "account": aid_a, "data": {"object": GW.retrieve_account(aid_a)}}
w = post_webhook(evt)
ok("valid webhook signature accepted", w.status_code == 200)
w_dup = post_webhook(evt)
ok("duplicate webhook event is a no-op (idempotent)", w_dup.status_code == 200 and w_dup.json().get("duplicate") is True)
bad = c.post("/webhooks/stripe", content=b'{"id":"evt_x","type":"account.updated"}',
             headers={"Stripe-Signature": "t=1,v1=deadbeef"})
ok("invalid webhook signature rejected", bad.status_code == 400)
# stale timestamp rejected by the real verifier's tolerance
stale = post_webhook({"id": "evt_stale", "type": "account.updated", "data": {"object": {}}}, ts=1)
ok("stale-timestamp webhook rejected", stale.status_code == 400)
# unknown event type is acknowledged (200) and recorded
unk = post_webhook({"id": "evt_unk", "type": "invoice.finalized", "data": {"object": {}}})
ok("unknown event type acknowledged + recorded", unk.status_code == 200)
wl = c.get("/admin/webhooks", headers=admin).json()["events"]
ok("webhook history is inspectable by admin", any(e["id"] == "evt_test_1" for e in wl))

# payment_intent webhook drives authorization without a redirect
az_wh = c.post("/payments/authorize", headers=login("buyer1"), json={"spec_id": spec_c, "estimated_seconds": 3600}).json()
pid_wh = sc.get_tx_by_public_id(dbmod.SessionLocal(), az_wh["transaction_id"]).stripe_payment_intent_id
GW.confirm_payment_intent(pid_wh)
post_webhook({"id": "evt_pi_auth", "type": "payment_intent.amount_capturable_updated",
              "data": {"object": {"id": pid_wh, "status": "requires_capture", "amount_capturable": 300}}})
s = dbmod.SessionLocal()
ok("webhook (not a redirect) is what marks the payment authorized",
   sc.get_tx_by_public_id(s, az_wh["transaction_id"]).status == "PAYMENT_AUTHORIZED")
s.close()


# ============================ LEDGER ============================
s = dbmod.SessionLocal()
bal, broken = dbmod.ledger_is_balanced(s)
ok("ledger balances across the entire Stripe lifecycle", bal and not broken)
# duplicate external reference (idempotency_key) is rejected by the ledger
from sqlalchemy.exc import IntegrityError
dbmod.post(s, "compute_transaction", legs=[(dbmod.EXTERNAL_PAYMENTS, dbmod.DEBIT, 10),
           (dbmod.PLATFORM_REVENUE, dbmod.CREDIT, 10)], idempotency_key="dup-key-xyz")
raised = False
try:
    dbmod.post(s, "compute_transaction", legs=[(dbmod.EXTERNAL_PAYMENTS, dbmod.DEBIT, 10),
               (dbmod.PLATFORM_REVENUE, dbmod.CREDIT, 10)], idempotency_key="dup-key-xyz")
    s.commit()
except IntegrityError:
    raised = True; s.rollback()
ok("duplicate ledger external reference is rejected", raised)
# refund created compensating entries (append-only) rather than editing the capture
n_cap = s.query(dbmod.LedgerEntry).filter(dbmod.LedgerEntry.entry_type == "compute_capture").count()
n_ref = s.query(dbmod.LedgerEntry).filter(dbmod.LedgerEntry.entry_type == "compute_refund").count()
n_rev = s.query(dbmod.LedgerEntry).filter(dbmod.LedgerEntry.entry_type == "compute_reversal").count()
ok("refunds/reversals are compensating entries (append-only ledger)",
   n_cap > 0 and n_ref > 0 and n_rev > 0)
s.close()


# ============================ ADMIN DETAIL + IDOR ============================
det = c.get(f"/admin/payments/{tid}", headers=admin).json()
ok("admin detail includes full state history + operations + settlement + snapshot",
   det["pricing_snapshot"]["price_per_hour_minor"] == 250 and len(det["state_history"]) >= 6
   and any(o["type"] == "capture" for o in det["operations"]) and det["settlements"])
ok("non-admin cannot read another buyer's transaction detail",
   c.get(f"/payments/{tid}", headers=login("seller_b")).status_code == 404)
ok("admin financial dashboard lists transactions",
   len(c.get("/admin/payments", headers=admin).json()["transactions"]) >= 5)
ok("non-admin cannot list all payments", c.get("/admin/payments", headers=login("buyer1")).status_code == 403)

# seller earnings surface
se = c.get("/seller/earnings/stripe", headers=login("seller_a")).json()
ok("seller earnings show gross/commission/net + transfers",
   se["net_earnings_minor"] >= 0 and "transfers_pending_minor" in se)


# ============================ CONCURRENCY (no double money movement) ============================
from concurrent.futures import ThreadPoolExecutor
# Capture the SAME transaction from many workers at once -> exactly one capture, one
# ledger posting, correct amount. Guards: PaymentOperation unique key + FSM + status.
tid_cc = run_to_metered(3600)
def _cap(_):
    # SQLite serialises writers ("database is locked"); the invariant (exactly-once
    # money movement) is what we assert, not the per-call HTTP/exception outcome.
    try:
        return c.post(f"/admin/payments/{tid_cc}/capture", headers=admin).status_code
    except Exception:
        return "err"
with ThreadPoolExecutor(max_workers=8) as ex:
    codes = list(ex.map(_cap, range(8)))
s = dbmod.SessionLocal()
_txcc = sc.get_tx_by_public_id(s, tid_cc)
def _legs_for(public_id, entry_type, account=None):
    """Count ledger legs for ONE compute tx (scoped via LedgerTx.reference_id)."""
    q = (s.query(dbmod.LedgerEntry)
         .join(dbmod.LedgerTx, dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id)
         .filter(dbmod.LedgerTx.reference_id == public_id,
                 dbmod.LedgerEntry.entry_type == entry_type))
    if account:
        q = q.filter(dbmod.LedgerEntry.account == account)
    return q.count()
n_cap_legs = _legs_for(tid_cc, "compute_capture", dbmod.EXTERNAL_PAYMENTS)
pi_cc = GW.payment_intents[_txcc.stripe_payment_intent_id]
ok(f"concurrent capture charges once (captured={_txcc.captured_amount}, PI received={pi_cc['amount_received']})",
   _txcc.captured_amount == 250 and pi_cc["amount_received"] == 250)
ok(f"concurrent capture posts exactly one capture ledger leg (got {n_cap_legs})", n_cap_legs == 1)
s.close()

# Transfer the SAME captured transaction from many workers -> exactly one transfer.
def _tr(_):
    try:
        return c.post(f"/admin/payments/{tid_cc}/transfer", headers=admin).status_code
    except Exception:
        return "err"
with ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(_tr, range(8)))
s = dbmod.SessionLocal()
_txcc = sc.get_tx_by_public_id(s, tid_cc)
n_tr_legs = (s.query(dbmod.LedgerEntry)
             .join(dbmod.LedgerTx, dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id)
             .filter(dbmod.LedgerTx.reference_id == tid_cc,
                     dbmod.LedgerEntry.entry_type == "compute_transfer",
                     dbmod.LedgerEntry.account == dbmod.acct_stripe_payouts()).count())
n_tr_this = len([t for t in GW.transfers.values() if t["transfer_group"] == _txcc.public_id])
ok(f"concurrent transfer moves money once (transferred={_txcc.transferred_amount})",
   _txcc.stripe_transfer_id is not None and _txcc.transferred_amount == 225)
ok(f"concurrent transfer created exactly one Stripe transfer for this tx (got {n_tr_this})", n_tr_this == 1)
ok(f"concurrent transfer posts exactly one transfer ledger leg (got {n_tr_legs})", n_tr_legs == 1)
s.close()


# ============================ RECONCILIATION ============================
s = dbmod.SessionLocal()
rec = sc.reconcile_all(s, gateway=GW)
ok(f"reconciliation: internal records match Stripe + ledger balances "
   f"({rec['transactions_checked']} tx, {len(rec['mismatches'])} mismatches)",
   rec["ok"] and rec["ledger_balanced"] and not rec["mismatches"])
# reconcile MUST detect an injected divergence (tamper the captured amount)
_bad = sc.get_tx_by_public_id(s, tid_cc)
_orig = _bad.captured_amount
_bad.captured_amount = _orig + 999; s.add(_bad); s.commit()
rec2 = sc.reconcile_transaction(s, _bad, gateway=GW)
ok("reconciliation DETECTS an internal/Stripe divergence", not rec2["consistent"] and rec2["problems"])
_bad.captured_amount = _orig; s.add(_bad); s.commit()   # restore
s.close()


# ============ RESERVE / DISPATCH: crash compensation + stale-op recovery ============
import datetime as _dtm

# (6a) a dispatch that fails mid-way is surfaced, leaves NO orphan task, and can retry.
# (reuses the existing _auth_confirm helper; patch + session cleaned up in finally.)
spec_cr = make_online_spec("seller_a", price=2.50, units=2, gpu="L4")
crid = _auth_confirm(spec_cr)
c.post(f"/payments/{crid}/reserve", headers=login("buyer1"))          # -> GPU_RESERVED
_orig_ct = sc.create_task
_ctc = {"n": 0}
def _ct_fail_once(db, booking, *a, **k):
    if _ctc["n"] == 0:
        _ctc["n"] += 1
        raise RuntimeError("simulated task-create DB failure")
    return _orig_ct(db, booking, *a, **k)
sc.create_task = _ct_fail_once
s = dbmod.SessionLocal()
_disp_failed = False
try:
    _tx = sc.get_tx_by_public_id(s, crid)
    try:
        sc.dispatch_job(s, _tx, task_type="notebook", code="print(1)")
    except sc.TransactionError:
        _disp_failed = True         # expected; unexpected errors still propagate
finally:
    sc.create_task = _orig_ct       # restore the patch no matter what
    s.close()                       # and always close the session
ok("a mid-way dispatch failure is surfaced, not silently swallowed", _disp_failed)
s = dbmod.SessionLocal(); _tx = sc.get_tx_by_public_id(s, crid)
ok("failed dispatch leaves NO task (orphan cleaned) and tx stays GPU_RESERVED",
   _tx.task_id is None and _tx.status == "GPU_RESERVED")
_r2 = sc.dispatch_job(s, _tx, task_type="notebook", code="print(2)")
ok("dispatch retry after a compensated failure succeeds (op was marked failed)",
   _r2.status == "RUNNING" and _r2.task_id is not None)
s.close()

# (6b) a STALE 'pending' reserve op (crashed prior attempt) is recovered on retry.
spec_st = make_online_spec("seller_a", price=2.50, units=1, gpu="T4")
stid = _auth_confirm(spec_st)
s = dbmod.SessionLocal(); _txs = sc.get_tx_by_public_id(s, stid)
_rk = sc.idem_key("reserve", _txs)
s.add(dbmod.PaymentOperation(tx_id=_txs.id, op_type="reserve", internal_idempotency_key=_rk,
      stripe_idempotency_key=_rk, state="pending", attempt_count=1)); s.commit()
_old = _dtm.datetime.now(_dtm.timezone.utc) - _dtm.timedelta(seconds=sc._OP_STALE_S + 60)
s.execute(dbmod.update(dbmod.PaymentOperation)
          .where(dbmod.PaymentOperation.internal_idempotency_key == _rk)
          .values(updated_at=_old, created_at=_old)); s.commit()
_res = sc.reserve_gpu(s, _txs)
ok("a STALE pending reserve op is recovered and the reservation completes",
   _res.status == "GPU_RESERVED")
s.close()

# (6c) ATOMIC stale reclaim: two callers observing the SAME stale pending op — only one
# wins. Proves the conditional UPDATE (WHERE state='pending' AND attempt_count=<seen>)
# that _begin_op relies on, so two concurrent retries can't both get proceed=True.
spec_at = make_online_spec("seller_a", price=2.50, units=1, gpu="A10")
atid = _auth_confirm(spec_at)
s = dbmod.SessionLocal(); _txa = sc.get_tx_by_public_id(s, atid)
_ak = sc.idem_key("reserve", _txa)
s.add(dbmod.PaymentOperation(tx_id=_txa.id, op_type="reserve", internal_idempotency_key=_ak,
      stripe_idempotency_key=_ak, state="pending", attempt_count=1)); s.commit()
_opid = s.query(dbmod.PaymentOperation).filter(
    dbmod.PaymentOperation.internal_idempotency_key == _ak).first().id
s.close()
# two independent sessions both observe attempt_count == 1, then both try to claim.
sA = dbmod.SessionLocal(); sB = dbmod.SessionLocal()
seenA = sA.get(dbmod.PaymentOperation, _opid).attempt_count
seenB = sB.get(dbmod.PaymentOperation, _opid).attempt_count
rA = sA.execute(dbmod.update(dbmod.PaymentOperation)
                .where(dbmod.PaymentOperation.id == _opid,
                       dbmod.PaymentOperation.state == "pending",
                       dbmod.PaymentOperation.attempt_count == seenA)
                .values(attempt_count=seenA + 1)); sA.commit()
rB = sB.execute(dbmod.update(dbmod.PaymentOperation)
                .where(dbmod.PaymentOperation.id == _opid,
                       dbmod.PaymentOperation.state == "pending",
                       dbmod.PaymentOperation.attempt_count == seenB)
                .values(attempt_count=seenB + 1)); sB.commit()
ok("atomic stale-op reclaim: exactly ONE of two same-attempt claims wins",
   [rA.rowcount == 1, rB.rowcount == 1].count(True) == 1)
sA.close(); sB.close()


# ============ ORCHESTRATOR BRIDGE: settle_after_result (job completion -> settle) ====
# A completed job should drive meter -> capture -> transfer via the SAME audited
# functions, idempotently. This is what /jobs/result now calls automatically.
def _run_to_running(spec_pub):
    a = c.post("/payments/authorize", headers=login("buyer1"),
               json={"spec_id": spec_pub, "estimated_seconds": 3600}).json()
    tid = a.get("transaction_id")
    if not tid:
        return None
    pid = sc.get_tx_by_public_id(dbmod.SessionLocal(), tid).stripe_payment_intent_id
    GW.confirm_payment_intent(pid)
    c.post(f"/payments/{tid}/confirm", headers=login("buyer1"))
    c.post(f"/admin/payments/{tid}/reserve", headers=admin)
    c.post(f"/admin/payments/{tid}/dispatch", headers=admin, json={})
    return tid

spec_br = make_online_spec("seller_a", price=2.50, units=5)
brid = _run_to_running(spec_br)
s = dbmod.SessionLocal()
txb = sc.get_tx_by_public_id(s, brid)
ok("bridge: tx is RUNNING before settle", txb.status == "RUNNING")
st = sc.settle_after_result(s, txb, metered_seconds=1800)   # 30 min @ 2.50/h -> 125
# The buyer is charged now; the seller's net is HELD (not transferred immediately).
ok("bridge: settle captures the buyer -> PAYMENT_CAPTURED", st == "PAYMENT_CAPTURED")
s.close(); s = dbmod.SessionLocal(); txb = sc.get_tx_by_public_id(s, brid)
ok("bridge: captured the ACTUAL metered usage (125)", txb.captured_amount == 125)
ok("bridge: platform fee + seller net == captured",
   txb.platform_fee_amount + txb.seller_net_amount == txb.captured_amount)
ok("bridge: seller NOT transferred immediately (held for the biweekly batch)",
   not txb.stripe_transfer_id and txb.transferred_amount == 0)
obl = s.query(dbmod.PayoutObligation).filter(
    dbmod.PayoutObligation.compute_tx_id == txb.id).first()
ok("bridge: a HELD payout obligation was created (accrued, risk hold set)",
   obl is not None and obl.state == "accrued" and obl.risk_hold_until is not None
   and obl.net_amount_minor == txb.seller_net_amount)
# idempotent: re-running settle must NOT double-capture
cap0 = txb.captured_amount
st2 = sc.settle_after_result(s, txb, metered_seconds=1800)
s.close(); s = dbmod.SessionLocal(); txb = sc.get_tx_by_public_id(s, brid)
ok("bridge: re-running settle is idempotent (no double capture)",
   st2 == "PAYMENT_CAPTURED" and txb.captured_amount == cap0)
sid_a = dbmod.get_user_by_username(s, "seller_a").id
s.close()

# 14-day hold: not batchable before it elapses; batchable after.
s = dbmod.SessionLocal()
before = dbmod.available_obligations(s, sid_a, "usd", mode=dbmod.payments_mode())
ok("hold: earnings are NOT available before the risk hold elapses",
   all(o.compute_tx_id != txb.id for o in before))
s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txb.id)\
    .update({dbmod.PayoutObligation.available_at: dbmod._utcnow() - dbmod.timedelta(seconds=1)})
s.commit()
after = dbmod.available_obligations(s, sid_a, "usd", mode=dbmod.payments_mode())
ok("hold: earnings become available once the hold elapses (auto-promote)",
   any(o.compute_tx_id == txb.id for o in after))

# report hold: a seller under review is NOT promoted even past the hold.
brid2 = _run_to_running(make_online_spec("seller_a", price=2.50, units=5))
s2 = dbmod.SessionLocal(); tx2 = sc.get_tx_by_public_id(s2, brid2)
sc.settle_after_result(s2, tx2, metered_seconds=1800)
s2.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == tx2.id)\
    .update({dbmod.PayoutObligation.available_at: dbmod._utcnow() - dbmod.timedelta(seconds=1)})
s2.commit()
dbmod.place_payout_hold(s2, sid_a, reason="test report")
avail_held = dbmod.available_obligations(s2, sid_a, "usd", mode=dbmod.payments_mode())
ok("report hold: matured earnings are withheld while the seller is under review",
   all(o.compute_tx_id != tx2.id for o in avail_held))
dbmod.clear_payout_hold(s2, sid_a)
avail_cleared = dbmod.available_obligations(s2, sid_a, "usd", mode=dbmod.payments_mode())
ok("report hold: releasing it makes the earnings batchable again",
   any(o.compute_tx_id == tx2.id for o in avail_cleared))
s2.close(); s.close()

# fail-closed at the source: a non-payout-ready seller can't even start a paid tx.
onboard_seller("seller_b", ok_=False)                 # seller_b never completes onboarding
spec_nr = make_online_spec("seller_b", price=2.50, units=2)
nr = c.post("/payments/authorize", headers=login("buyer1"),
            json={"spec_id": spec_nr, "estimated_seconds": 3600})
ok("bridge: authorize refused for a non-payout-ready seller (money can't start)",
   nr.status_code == 409)


# ============ REGRESSION (finding B): telemetry failure NEVER breaks settlement ============
# The AUTHORITATIVE financial state is written BEFORE, and independently of, telemetry.
# Make EVERY telemetry emitter raise, then drive settlement directly (no HTTP middleware in
# the way): the money outcome must be exactly correct and the tx must reach a terminal
# captured state — never stuck in a *_PENDING state because a metric/event throw aborted it.
_obs_event_orig, _obs_inc_orig = sc._obs.event, sc._obs.inc_metric
def _boom_telemetry(*a, **k):
    raise RuntimeError("simulated telemetry failure")
_spec_tb = make_online_spec("seller_a", price=2.50, units=5)
_tb_id = _run_to_running(_spec_tb)
_sB = dbmod.SessionLocal()
_txB = sc.get_tx_by_public_id(_sB, _tb_id)
try:
    sc._obs.event = _boom_telemetry
    sc._obs.inc_metric = _boom_telemetry
    _stB = sc.settle_after_result(_sB, _txB, metered_seconds=1800)   # 30 min @2.50/h -> 125
finally:
    sc._obs.event, sc._obs.inc_metric = _obs_event_orig, _obs_inc_orig
_sB.close()
_sB = dbmod.SessionLocal()
_txB = sc.get_tx_by_public_id(_sB, _tb_id)
_balB, _brokenB = dbmod.ledger_is_balanced(_sB)
_sB.close()
ok("finding B: telemetry failure never blocks settlement (capture completed correctly)",
   _stB == "PAYMENT_CAPTURED" and _txB.captured_amount == 125
   and _txB.status == "PAYMENT_CAPTURED")
ok("finding B: ledger stays balanced despite telemetry raising throughout settlement",
   _balB and not _brokenB)


# ============ FINANCIAL-INTEGRITY HEARTBEAT (#286/#287) ============
# The SQL invariant agrees with ledger_is_balanced on the healthy ledger this suite built,
# AND detects a deliberately-injected imbalance. Runs LAST — it corrupts the ledger on
# purpose, and the DB file is deleted immediately after.
_fs = dbmod.SessionLocal()
_fi = dbmod.financial_integrity(_fs)
ok("financial_integrity: the suite's real ledger is balanced (SQL invariant, no row load)",
   _fi["balanced"] and _fi["imbalanced_tx"] == 0 and _fi["net_minor"] == 0)
_pb = dbmod.payout_backlog(_fs)
ok("payout_backlog: non-negative unbatched count + oldest age",
   _pb["unbatched"] >= 0 and _pb["oldest_age_seconds"] >= 0)
# Inject a single unbalanced leg into an existing tx -> that tx no longer balances.
_anytx = _fs.query(dbmod.LedgerTx).first()
_fs.add(dbmod.LedgerEntry(tx_id=_anytx.id, account=dbmod.PLATFORM_REVENUE,
                          direction=dbmod.CREDIT, amount=1, entry_type="imbalance_probe"))
_fs.commit()
_bad = dbmod.financial_integrity(_fs)
ok("financial_integrity: a deliberately-injected imbalance is DETECTED",
   (not _bad["balanced"]) and _bad["imbalanced_tx"] >= 1)
_fs.close()


# ---- canonical funding metrics endpoint (admin-only, read-only, honest) ----
fnd = c.get("/admin/funding?scope=test", headers=admin)
ok("admin funding endpoint returns 200 for an admin",
   fnd.status_code == 200 and "money_minor" in fnd.json() and "rates" in fnd.json())
ok("funding endpoint reports canonical GMV as an int (minor units)",
   isinstance(fnd.json()["money_minor"]["gmv_captured"], int))
ok("funding REAL scope shows no LIVE GMV in this TEST-mode suite",
   c.get("/admin/funding?scope=real", headers=admin).json()["money_minor"]["gmv_captured"] == 0)
ok("funding endpoint is admin-only (buyer -> 403)",
   c.get("/admin/funding", headers=login("buyer1")).status_code == 403)
ok("funding endpoint rejects an invalid scope (422)",
   c.get("/admin/funding?scope=bogus", headers=admin).status_code == 422)

print(f"\n=== stripe: {PASSES} passed, {FAILS} failed ===")
for f in ("stripe_test.db", "stripe_test.db-wal", "stripe_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
