"""demo_payout_loop_test.py — the COMPLETE buyer->GPU->payout->proof loop, offline.

stripe_e2e_flow_test.py proves the buyer half up to a HELD payout obligation (payout pending
by design). THIS suite proves the other half and the unified proof artifact:

  * a seller is made payout-ready HEADLESSLY (sc.ensure_test_payout_ready — the one-command
    demo onboarding, fake-gateway path), with no manual hosted-onboarding click-through;
  * buyer authorize -> confirm -> reserve -> dispatch ONCE -> seller signs a real result ->
    auto meter+capture;
  * an admin drives the provider payout (transfer_to_seller) — the leg the E2E runner used to
    report "PENDING BY DESIGN" — and it settles EXACTLY ONCE;
  * GET /payments/{tx}/proof stitches payment + signed compute receipt + payout into ONE
    artifact, and it reflects the loop honestly BEFORE (held) and AFTER (released/paid) payout.

Offline: FakeStripeGateway + TestClient + the REAL Ed25519 agent signer. No network.
PAYOUT_HOLD_DAYS=0 so the demo pays in-session (the hold is exercised separately in
stripe_e2e_flow_test.py). Run: python demo_payout_loop_test.py
"""
import base64
import os
import sys
import tempfile
import time

os.environ["DATABASE_URL"] = "sqlite:///./demo_payout_loop_test.db"
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
os.environ["ADMIN_USERS"] = "demo_admin"
os.environ["REAPER_DISABLED"] = "true"
os.environ["PAYOUT_HOLD_DAYS"] = "0"       # demo pays in-session; the 14-day hold is tested elsewhere

for f in ("demo_payout_loop_test.db", "demo_payout_loop_test.db-wal", "demo_payout_loop_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

_keydir = tempfile.mkdtemp(prefix="pb-demo-loop-")
os.environ["PETABYTE_AGENT_KEY"] = os.path.join(_keydir, "agent.key")
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


def signed_proof(content_hash):
    # A real agent binds the result to the sha256 of the actual output bytes via `content_hash`
    # (the field the server persists + the receipt exposes as content_hash_sha256).
    proof = {"content_hash": content_hash, "output_hash": content_hash, "ts": int(time.time())}
    return {"proof": proof, "signature": agent_crypto.sign_proof(proof)}


# ---- admin (in ADMIN_USERS by username) drives the payout leg ----
reg("demo_admin"); ah = login("demo_admin")
ok("admin account is recognised", c.get("/admin/whoami", headers=ah).status_code == 200)

# ---- seller: HEADLESS payout-ready onboarding (the one-command demo path) ----
reg("demo_seller"); c.post("/change_role", headers=login("demo_seller"), json={"role": "seller"})
sh = login("demo_seller")
s = dbmod.SessionLocal()
seller = dbmod.get_user_by_username(s, "demo_seller")
ca = sc.ensure_test_payout_ready(s, seller, country="US", email="demo_seller@x.com")
ok("ensure_test_payout_ready makes the connected account payout-ready (no manual onboarding)",
   ca.payout_ready())
ok("readiness is authoritative: the seller can now accept paid jobs",
   dbmod.get_user_by_username(s, "demo_seller").can_accept_paid_jobs is True)
s.close()

api_key = c.post("/create_api_key?days=90&scopes=node,jobs", headers=sh).json()["api_key"]
sr = c.post("/register_specs", headers=sh, json={
    "cpu": 16, "ram": 64, "duration": 48, "price_per_hour": 2.50, "provider": "demo_seller",
    "gpu_model": "NVIDIA L4", "gpu_count": 1, "vram_gb": 24, "units": 1,
    "region": "us-east", "country": "US"})
sp_id = sr.json()["spec_id"]
att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
       "ts": int(time.time())}
c.post("/prove", headers=sh, json={"spec_id": sp_id, "attestation": att,
                                   "signature": agent_crypto.sign_proof(att),
                                   "pubkey": agent_crypto.public_key_b64()})
c.post("/heartbeat", headers={"X-API-KEY": api_key}, json={"spec_id": sp_id})
s = dbmod.SessionLocal(); spec_pub = dbmod.get_spec_by_id(s, sp_id).public_id; s.close()

# ---- buyer: authorize -> confirm -> reserve -> dispatch ONCE ----
reg("demo_buyer"); bh = login("demo_buyer")
az = c.post("/payments/authorize", headers=bh,
            json={"spec_id": spec_pub, "estimated_seconds": 120})
ok("authorize succeeds against a payout-ready seller", az.status_code == 200)
azj = az.json(); tx = azj["transaction_id"]
c.post(f"/payments/{tx}/simulate-card", headers=bh)
c.post(f"/payments/{tx}/confirm", headers=bh)
c.post(f"/payments/{tx}/reserve", headers=bh)
d1 = c.post(f"/payments/{tx}/dispatch", headers=bh,
            json={"task_type": "notebook", "code": "print('demo-loop')"})
ok("dispatch -> RUNNING", d1.json().get("status") == "RUNNING")

# ---- seller signs a real result; settlement (meter+capture) is automatic ----
_next = c.get("/jobs/next", headers={"X-API-KEY": api_key}).json() or {}
claimed = _next.get("task_id")
ok("the seller agent is handed the dispatched task", bool(claimed))
res = c.post("/jobs/result", headers={"X-API-KEY": api_key},
             json={"task_id": claimed, "status": "completed", "result": "ok",
                   **signed_proof(f"sha256:demo-{claimed}")})
ok("seller result accepted (signature verified)", res.status_code == 200)

final_status = None
for _ in range(200):                      # up to ~10s; capture is normally synchronous
    final_status = c.get(f"/payments/{tx}", headers=bh).json().get("status")
    if final_status in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED",
                        "CAPTURE_FAILED", "JOB_FAILED"):
        break
    time.sleep(0.05)
ok("settlement reaches PAYMENT_CAPTURED automatically", final_status == "PAYMENT_CAPTURED")

# ---- PROOF before payout: payment + signed compute receipt present, payout still HELD ----
pf1 = c.get(f"/payments/{tx}/proof", headers=bh)
ok("proof endpoint is buyer-scoped and returns 200", pf1.status_code == 200)
p1 = pf1.json()
ok("proof.payment shows a real captured Stripe payment",
   p1["payment"]["captured"] and p1["payment"]["captured_minor"] > 0
   and p1["payment"]["payment_intent_id"].startswith("pi_"))
ok("proof.compute carries the Ed25519 receipt and LIVE server re-verification passes",
   p1["compute"] and p1["compute"]["proof"]["server_reverified"] is True
   and p1["compute"]["proof"]["content_hash_sha256"])
ok("proof.accounting_identity_holds (captured == fee + seller_net)",
   p1["accounting_identity_holds"] is True)
ok("BEFORE payout: proof shows the seller payout HELD, not yet transferred",
   p1["payout"]["hold_status"] == "held" and not p1["payout"]["paid"]
   and p1["payout"]["stripe_transfer_id"] is None)

# ---- admin drives the provider payout (the leg the runner reported PENDING) ----
tr = c.post(f"/admin/payments/{tx}/transfer", headers=ah)
ok("admin transfer succeeds (provider payout to the connected account)", tr.status_code == 200)

# ---- PROOF after payout: released + paid + a real transfer id ----
p2 = c.get(f"/payments/{tx}/proof", headers=bh).json()
ok("AFTER payout: proof shows the payout RELEASED + PAID with a Stripe transfer id",
   p2["payout"]["paid"] is True and p2["payout"]["hold_status"] == "released"
   and str(p2["payout"]["stripe_transfer_id"]).startswith("tr_")
   and p2["payout"]["obligation_state"] == "paid")
ok("transferred amount equals the seller net (whole earning paid out)",
   p2["payout"]["transferred_minor"] == p2["payout"]["seller_net_minor"] > 0)

# exactly ONE Stripe transfer for this tx (idempotent; no double pay)
n_tr = len([t for t in GW.transfers.values()
            if t.get("metadata", {}).get("petabyte_tx") == tx])
ok("exactly one Stripe transfer created for the tx (no double payout)", n_tr == 1)
tr2 = c.post(f"/admin/payments/{tx}/transfer", headers=ah)     # idempotent repeat
n_tr2 = len([t for t in GW.transfers.values()
             if t.get("metadata", {}).get("petabyte_tx") == tx])
ok("a repeat transfer is idempotent (still exactly one transfer)",
   tr2.status_code == 200 and n_tr2 == 1)

# ---- proof access control: a stranger cannot read someone else's proof ----
reg("demo_stranger")
ok("a non-party is denied the proof (404, no cross-tenant leak)",
   c.get(f"/payments/{tx}/proof", headers=login("demo_stranger")).status_code == 404)

print(f"\n=== demo_payout_loop: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
for f in ("demo_payout_loop_test.db", "demo_payout_loop_test.db-wal", "demo_payout_loop_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
import shutil  # noqa: E402
shutil.rmtree(_keydir, ignore_errors=True)   # the throwaway agent-key dir must not accumulate
raise SystemExit(1 if _fail else 0)
