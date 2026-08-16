"""stripe_e2e_flow_test.py — the buyer->reserve->dispatch->seller-result->capture path,
exercised through the REAL marketplace endpoints with the offline FakeStripeGateway.

This locks the highest-priority operator finding from the live run: it looked like POST
/dispatch had to be called TWICE to reach PAYMENT_CAPTURED. It does not. This test proves:

  * POST /payments/{tx}/dispatch is called EXACTLY ONCE;
  * the seller then completes the job via the real /jobs/result path;
  * settlement (meter -> capture -> held payout obligation) happens AUTOMATICALLY;
  * a plain GET /payments/{tx} reports PAYMENT_CAPTURED — no second POST needed;
  * repeated POST /dispatch is idempotent: no second task, no second capture, no duplicate
    reservation, no extra billing;
  * /payments/authorize returns the (non-secret) payment_intent_id;
  * the seller payout is a HELD obligation (14-day hold) — PENDING BY DESIGN, not transferred.

Offline: FakeStripeGateway + TestClient + the REAL Ed25519 agent signer. No network.
Run: python stripe_e2e_flow_test.py   (always uses its own isolated SQLite DB)
"""
import base64
import os
import sys
import tempfile
import time

# FORCE an isolated offline SQLite DB. This functional flow suite uses the FakeStripeGateway,
# whose deterministic account ids (acct_fake000001…) collide on a SHARED Postgres with rows
# other suites leave behind. It must own its DB, never inherit one — never `setdefault` here.
# (Concurrency/race correctness is proven separately in postgres_test.py, not here.)
os.environ["DATABASE_URL"] = "sqlite:///./stripe_e2e_flow_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_stripe"
os.environ["PLATFORM_TAKE_RATE"] = "0.10"
os.environ["PLATFORM_MIN_CHARGE_MINOR"] = "50"
os.environ["PLATFORM_MAX_DURATION_S"] = "7200"
os.environ["ADMIN_USERS"] = "admin@petabyte.market"
os.environ["REAPER_DISABLED"] = "true"
os.environ["PAYOUT_HOLD_DAYS"] = "14"

for f in ("stripe_e2e_flow_test.db", "stripe_e2e_flow_test.db-wal", "stripe_e2e_flow_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

# real Ed25519 agent signer (same code the seller node uses)
_keydir = tempfile.mkdtemp(prefix="pb-e2e-flow-")
os.environ["PETABYTE_AGENT_KEY"] = os.path.join(_keydir, "agent.key")
# APPEND (not insert-0) so lumaris_api's own modules — especially main.py — keep priority; only
# the unique `crypto` name resolves into lumaris_agent. Inserting at the front would shadow
# lumaris_api/main.py with lumaris_agent/main.py.
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "lumaris_agent"))
import crypto as agent_crypto  # noqa: E402

import db as dbmod  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from stripe_gateway import FakeStripeGateway, set_gateway  # noqa: E402
import stripe_connect as sc  # noqa: E402
import main  # noqa: E402

GW = set_gateway(FakeStripeGateway())
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
    return {"Authorization": "Bearer " + c.post(
        "/login", data={"username": u, "password": PW}).json()["access_token"]}


def signed_proof(output_hash):
    proof = {"output_hash": output_hash, "ts": int(time.time())}
    return {"proof": proof, "signature": agent_crypto.sign_proof(proof)}


# ---- seller: onboard payout-ready, register + attest a spec ----
reg("flow_seller"); c.post("/change_role", headers=login("flow_seller"), json={"role": "seller"})
sh = login("flow_seller")
# payout-ready connected account (fake gateway)
s = dbmod.SessionLocal()
seller = dbmod.get_user_by_username(s, "flow_seller")
ca = sc.get_or_create_connected_account(s, seller, country="US", email="flow_seller@x.com")
GW.complete_onboarding(ca.stripe_account_id, ok=True)
sc.refresh_connected_account(s, ca)
s.close()

api_key = c.post("/create_api_key?days=90&scopes=node,jobs", headers=sh).json()["api_key"]
sr = c.post("/register_specs", headers=sh, json={
    "cpu": 16, "ram": 64, "duration": 48, "price_per_hour": 2.50, "provider": "flow_seller",
    "gpu_model": "NVIDIA L4", "gpu_count": 1, "vram_gb": 24, "units": 2,
    "region": "us-east", "country": "US"})
sp_id = sr.json()["spec_id"]     # internal id (for /prove + /heartbeat)
att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
       "ts": int(time.time())}
c.post("/prove", headers=sh, json={"spec_id": sp_id, "attestation": att,
                                   "signature": agent_crypto.sign_proof(att),
                                   "pubkey": agent_crypto.public_key_b64()})
c.post("/heartbeat", headers={"X-API-KEY": api_key}, json={"spec_id": sp_id})

s = dbmod.SessionLocal()
spec_pub = dbmod.get_spec_by_id(s, sp_id).public_id
s.close()

# ---- buyer: authorize -> confirm -> reserve ----
reg("flow_buyer")
bh = login("flow_buyer")
az = c.post("/payments/authorize", headers=bh,
            json={"spec_id": spec_pub, "estimated_seconds": 120})
ok("authorize succeeds (payout-ready seller, fake gateway)", az.status_code == 200)
azj = az.json()
tx = azj["transaction_id"]
ok("authorize returns the non-secret payment_intent_id (pi_…) for the test runner",
   isinstance(azj.get("payment_intent_id"), str) and azj["payment_intent_id"].startswith("pi_"))
ok("authorize does NOT leak anything secret beyond client_secret",
   "secret_key" not in azj and "webhook" not in str(azj).lower())

c.post(f"/payments/{tx}/simulate-card", headers=bh)     # fake-gateway card confirmation
conf = c.post(f"/payments/{tx}/confirm", headers=bh)
ok("confirm verifies Stripe server-side -> PAYMENT_AUTHORIZED",
   conf.json().get("status") == "PAYMENT_AUTHORIZED")
rv = c.post(f"/payments/{tx}/reserve", headers=bh)
ok("reserve -> GPU_RESERVED", rv.json().get("status") == "GPU_RESERVED")


def _task_count():
    s = dbmod.SessionLocal()
    txr = sc.get_tx_by_public_id(s, tx)
    n = s.query(dbmod.Task).filter(dbmod.Task.booking_id == txr.booking_id).count()
    tid = txr.task_id
    s.close()
    return n, tid


# ---- dispatch EXACTLY ONCE ----
d1 = c.post(f"/payments/{tx}/dispatch", headers=bh, json={"task_type": "notebook",
                                                          "code": "print('flow')"})
ok("first dispatch -> RUNNING", d1.json().get("status") == "RUNNING")
n1, task_id1 = _task_count()
ok("exactly one task created by the first dispatch", n1 == 1 and task_id1 is not None)

# ---- duplicate dispatch is idempotent (BEFORE the seller completes) ----
d2 = c.post(f"/payments/{tx}/dispatch", headers=bh, json={"task_type": "notebook",
                                                          "code": "print('again')"})
ok("second dispatch is accepted idempotently (no error)", d2.status_code == 200)
n2, task_id2 = _task_count()
ok("duplicate dispatch does NOT create a second task", n2 == 1 and task_id2 == task_id1)

# ---- seller claims + completes via the REAL job path ----
nxt = c.get("/jobs/next", headers={"X-API-KEY": api_key})
ok("seller /jobs/next returns the dispatched task", nxt.status_code == 200)
claimed = nxt.json().get("task_id")
ok("claimed task id matches the dispatched task", claimed == task_id1)
res = c.post("/jobs/result", headers={"X-API-KEY": api_key},
             json={"task_id": claimed, "status": "completed", "result": "ok",
                   **signed_proof(f"sha256:flow-{claimed}")})
ok("seller result accepted (HTTP 200, signature verified)", res.status_code == 200)

# ---- settlement is AUTOMATIC — poll GET, no second dispatch ----
final_status = None
for _ in range(20):
    pv = c.get(f"/payments/{tx}", headers=bh)
    final_status = pv.json().get("status")
    if final_status in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED",
                        "CAPTURE_FAILED", "JOB_FAILED"):
        break
    time.sleep(0.05)
ok("transaction reaches PAYMENT_CAPTURED automatically via GET polling (NO 2nd dispatch)",
   final_status == "PAYMENT_CAPTURED")

s = dbmod.SessionLocal()
txr = sc.get_tx_by_public_id(s, tx)
# Coerce nullable money columns to 0: if capture never happened these stay None, and a bare
# `0 < None` would raise TypeError, aborting the harness before it can print a clean FAIL.
cap = txr.captured_amount or 0
fee = txr.platform_fee_amount or 0
net = txr.seller_net_amount or 0
transferred = txr.transferred_amount or 0
n_cap = s.query(dbmod.LedgerEntry).filter(
    dbmod.LedgerEntry.entry_type == "compute_capture",
    dbmod.LedgerEntry.account == dbmod.EXTERNAL_PAYMENTS_MINOR,
    dbmod.LedgerTx.reference_id == tx,
    dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id).count()
obl = s.query(dbmod.PayoutObligation).filter(
    dbmod.PayoutObligation.compute_tx_id == txr.id).first()
s.close()

ok("captured > 0 and never exceeds the authorization",
   0 < cap <= azj["authorization_amount"])
ok("accounting identity holds: captured == platform_fee + seller_net", cap == fee + net)
ok("exactly ONE capture ledger posting for this tx (no double charge)", n_cap == 1)

# ---- seller payout is HELD (pending by design), not transferred ----
ok("seller was NOT transferred immediately (transferred_amount == 0)", transferred == 0)
ok("a held payout obligation exists for the seller net (accrued)",
   obl is not None and obl.net_amount_minor == net and obl.state == "accrued")
ok("obligation carries the tx's TEST mode (never mixed with LIVE)",
   (obl.mode or "").upper() == (txr.mode or "").upper() if obl else False)
ok("obligation is still WITHIN the 14-day hold now (not yet payable)",
   obl is not None and not dbmod.payout_hold_elapsed(obl))
ok("obligation BECOMES payable once the hold elapses (injected future clock)",
   obl is not None and dbmod.payout_hold_elapsed(
       obl, now=(obl.available_at.replace(tzinfo=__import__('datetime').timezone.utc)
                 if obl.available_at.tzinfo is None else obl.available_at)))

# ---- dispatch AGAIN after capture: still idempotent, still captured, no new task/charge ----
d3 = c.post(f"/payments/{tx}/dispatch", headers=bh, json={"task_type": "notebook"})
n3, task_id3 = _task_count()
s = dbmod.SessionLocal()
n_cap_after = s.query(dbmod.LedgerEntry).filter(
    dbmod.LedgerEntry.entry_type == "compute_capture",
    dbmod.LedgerEntry.account == dbmod.EXTERNAL_PAYMENTS_MINOR,
    dbmod.LedgerTx.reference_id == tx,
    dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id).count()
txr2 = sc.get_tx_by_public_id(s, tx)
s.close()
ok("post-capture dispatch is idempotent: still one task, still PAYMENT_CAPTURED, one capture",
   n3 == 1 and task_id3 == task_id1 and txr2.status == "PAYMENT_CAPTURED" and n_cap_after == 1)

print(f"\n=== stripe_e2e_flow: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
