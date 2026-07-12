"""Adversarial money-path test: hammer launch / stop / extend / failover
concurrently and assert conservation of money — no double-charge, no
double-payout, no oversell — under race conditions.

Run:  python adversarial_test.py    (same env as smoke_test.py; uses sqlite)

The invariant checked at the end is total conservation:
    deposits == balances + escrow_in_flight + seller_earnings + platform_revenue
Every dollar deposited is exactly one of: still in a wallet, locked in escrow,
paid to a seller, or taken as platform fee. If any race double-charges or
double-pays, this equation breaks.
"""
import os, json, time, base64, threading
from decimal import Decimal as Dec
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("DATABASE_URL", "sqlite:///./adv.db")
os.environ.setdefault("SECRET_KEY", "t")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("GOOGLE_OAUTH_STUB", "true")
os.environ.setdefault("AWS_REFERENCE_PRICE", "12.29")
os.environ.setdefault("BASE_DOMAIN", "petabyte.market")
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for _f in ("adv.db",):
    try: os.remove(_f)
    except FileNotFoundError: pass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import db as _dbinit
if _dbinit.engine.dialect.name.startswith("postgres"):
    with _dbinit.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    _dbinit.init_db()

import main
import db as dbmod
from db import SessionLocal, User, Booking, SellerSpec, Platform

c = TestClient(main.app)
SK = Ed25519PrivateKey.generate()
PASS = FAIL = 0

def ok(label, cond):
    global PASS, FAIL
    cond = bool(cond)
    PASS += cond; FAIL += (not cond)
    print(("PASS " if cond else "FAIL ") + label)

def sign(payload):
    return base64.b64encode(SK.sign(json.dumps(payload, sort_keys=True,
                            separators=(",", ":")).encode())).decode()

def tok(u):
    return {"Authorization": "Bearer " + c.post("/login",
            data={"username": u, "password": "pw12345678"}).json()["access_token"]}

def mkseller(nm, price, units):
    c.post("/register_user", json={"username": nm, "password": "pw12345678"})
    h = tok(nm)
    c.post("/change_role", headers=h, json={"role": "seller"})
    sid = c.post("/register_specs", headers=h, json={
        "cpu": 8, "ram": 32, "gpu_model": "L4", "duration": 48,
        "price_per_hour": price, "provider": nm, "units": units}).json()["spec_id"]
    at = {"cpu": 8, "ram": 32, "gpu_model": "L4", "nonce": nm, "ts": int(time.time())}
    c.post("/prove", headers=h, json={"spec_id": sid, "attestation": at,
           "signature": sign(at),
           "pubkey": base64.b64encode(SK.public_key().public_bytes_raw()).decode()})
    k = c.post("/create_api_key", headers=h).json()["api_key"]
    c.post("/heartbeat", headers={"X-API-KEY": k}, json={"spec_id": sid})
    return h, sid

# ---------- setup: 2 sellers (A cheap w/ 3 units, B backup w/ 6), 6 buyers ----------
DEPOSIT = Dec("40.00")
ah, aspec = mkseller("advnodeA", 1.0, 3)
bh, bspec = mkseller("advnodeB", 2.0, 6)
buyers = []
for i in range(6):
    u = f"advbuyer{i}"
    c.post("/register_user", json={"username": u, "password": "pw12345678"})
    hh = tok(u)
    c.post("/deposit", headers=hh, json={"amount": float(DEPOSIT)})
    buyers.append(hh)
TOTAL_DEPOSITED = DEPOSIT * len(buyers)

# ---------- storm 1: 6 buyers race /launch for 3 cheap units ----------
def do_launch(h):
    r = c.post("/launch", headers=h, json={"template": "comfyui", "hours": 2})
    return r.status_code, (r.json() if r.status_code == 200 else None)

with ThreadPoolExecutor(max_workers=6) as ex:
    results = list(ex.map(do_launch, buyers))
launched = [(b, buyers[i]) for i, (s, b) in enumerate(results) if s == 200]
ok("concurrent launches all succeed or fail cleanly (200/402/409 only)",
   all(s in (200, 402, 409) for s, _ in results))
# capacity conservation: units on A never oversold
s = SessionLocal()
spa = s.query(SellerSpec).filter(SellerSpec.id == aspec).first()
spb = s.query(SellerSpec).filter(SellerSpec.id == bspec).first()
ok("no oversell on node A", spa.available_units >= 0)
ok("no oversell on node B", spb.available_units >= 0)
booked_units = (3 - spa.available_units) + (6 - spb.available_units)
ok("every successful launch holds exactly one unit", booked_units == len(launched))
s.close()

# ---------- storm 2: concurrent double-stop + stop-vs-extend races ----------
vm0, own0 = launched[0][0]["vm_id"], launched[0][1]
def stop0(_): return c.post(f"/vm/{vm0}/stop", headers=own0).status_code
with ThreadPoolExecutor(max_workers=8) as ex:
    list(ex.map(stop0, range(8)))          # 8 concurrent stops of the same VM
s = SessionLocal()
b0 = s.query(Booking).filter(Booking.id == launched[0][0]["booking_id"]).first()
ok("8 racing stops -> booking settled exactly once (terminal)", b0.status == "released")
s.close()

vm1, own1 = launched[1][0]["vm_id"], launched[1][1]
def race_ext(_): return c.post(f"/vm/{vm1}/extend", headers=own1, json={"hours": 1}).status_code
def race_stop(_): return c.post(f"/vm/{vm1}/stop", headers=own1).status_code
with ThreadPoolExecutor(max_workers=8) as ex:
    fs = [ex.submit(race_ext, i) for i in range(4)] + [ex.submit(race_stop, i) for i in range(4)]
    [f.result() for f in fs]
s = SessionLocal()
b1 = s.query(Booking).filter(Booking.id == launched[1][0]["booking_id"]).first()
ok("stop-vs-extend race -> booking terminal exactly once", b1.status == "released")
s.close()

# ---------- storm 3: failover while stopping (node A dies mid-flight) ----------
if len(launched) >= 3:
    from datetime import datetime, timezone, timedelta
    s = SessionLocal()
    spa = s.query(SellerSpec).filter(SellerSpec.id == aspec).first()
    spa.last_seen = datetime.now(timezone.utc) - timedelta(seconds=999)
    s.add(spa); s.commit(); s.close()
    def failover(_):
        d = SessionLocal(); dbmod.reap_and_failover(d); d.close(); return 1
    vm2, own2 = launched[2][0]["vm_id"], launched[2][1]
    def stop2(_): return c.post(f"/vm/{vm2}/stop", headers=own2).status_code
    with ThreadPoolExecutor(max_workers=6) as ex:
        fs = [ex.submit(failover, i) for i in range(3)] + [ex.submit(stop2, i) for i in range(3)]
        [f.result() for f in fs]
    s = SessionLocal()
    b2 = s.query(Booking).filter(Booking.id == launched[2][0]["booking_id"]).first()
    ok("failover-vs-stop race -> booking terminal at most once",
       b2.status in ("released", "refunded"))
    s.close()

# ---------- settle everything left, then audit conservation ----------
for body, own in launched:
    c.post(f"/vm/{body['vm_id']}/stop", headers=own)

s = SessionLocal()
def _D(x): return x if isinstance(x, Dec) else Dec(str(x or 0))
balances = sum((_D(u.balance) for u in s.query(User).filter(User.username.like("advbuyer%")).all()), Dec(0))
earnings = sum((_D(u.earnings) for u in s.query(User).filter(User.username.in_(["advnodeA", "advnodeB"])).all()), Dec(0))
plat = s.query(Platform).first()
platform_rev = _D(plat.revenue) if plat else Dec(0)
escrow = sum((_D(b.gross_amount) for b in s.query(Booking).filter(
    Booking.status.in_(["escrowed", "active"])).all()), Dec(0))
total_now = balances + earnings + platform_rev + escrow
# The LEDGER must also balance after all that concurrent abuse — and it must
# independently reconstruct the same balances the cached columns claim.
from db import ledger_is_balanced, account_balance, acct_buyer, acct_seller, PLATFORM_REVENUE
_ok_bal, _broken = ledger_is_balanced(s)
ok(f"ledger balances after concurrent abuse (debits == credits, {len(_broken)} broken)",
   _ok_bal and not _broken)
_mm = []
for _u in s.query(User).filter(User.username.like("advbuyer%")).all():
    if _D(_u.balance) != account_balance(s, acct_buyer(_u.id)):
        _mm.append(_u.username)
for _u in s.query(User).filter(User.username.in_(["advnodeA", "advnodeB"])).all():
    if _D(_u.earnings) != account_balance(s, acct_seller(_u.id)):
        _mm.append(_u.username)
ok(f"ledger independently reconstructs every balance after races ({len(_mm)} mismatches)",
   not _mm)
ok("platform revenue matches the ledger",
   _D(plat.revenue if plat else 0) == account_balance(s, PLATFORM_REVENUE))

# With Decimal money this is EXACT — not "within a cent". No tolerance.
ok(f"MONEY CONSERVED EXACTLY: deposits {TOTAL_DEPOSITED} == wallets {balances} + "
   f"earnings {earnings} + platform {platform_rev} + escrow {escrow}",
   total_now == _D(TOTAL_DEPOSITED))
# no negative balances anywhere
ok("no negative wallet", all(_D(u.balance) >= 0 for u in s.query(User).all()))
ok("no negative earnings", all(_D(u.earnings) >= 0 for u in s.query(User).all()))
# capacity fully returned after all stops
spa = s.query(SellerSpec).filter(SellerSpec.id == aspec).first()
spb = s.query(SellerSpec).filter(SellerSpec.id == bspec).first()
ok("all units returned after settlement",
   spa.available_units == 3 and spb.available_units == 6)
s.close()

print(f"\n=== adversarial: {PASS} passed, {FAIL} failed ===")
for _f in ("adv.db",):
    try: os.remove(_f)
    except FileNotFoundError: pass
import sys
sys.exit(1 if FAIL else 0)
