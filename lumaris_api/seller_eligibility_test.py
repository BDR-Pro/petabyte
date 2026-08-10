"""seller_eligibility_test.py — the authoritative, LIVE paid-job eligibility gate.

Proves financial authorization re-checks ALL independent conditions (payout readiness with
bounded freshness, reputation, fraud/risk, availability, mode) through the centralized service —
never the cached users.can_accept_paid_jobs boolean. Covers the required matrix:

  1  cached can_accept_paid_jobs=TRUE  + live payout NOT ready  -> REJECTED
  2  cached can_accept_paid_jobs=FALSE + live payout ready + good rep/risk -> ALLOWED
  3  payout ready + reputation below threshold -> REJECTED (REPUTATION_TOO_LOW)
  4  payout ready + fraud/risk hold -> REJECTED (FRAUD_HOLD)
  5  rail status unknown/stale -> FAIL CLOSED (PAYOUT_READINESS_STALE)
  6  no implemented rail (NOT_IMPLEMENTED only) -> REJECTED (NO_PAYOUT_RAIL)
  7  Connect ready -> ACCEPTED
  8  Connect becomes restricted between listing and authorization -> REJECTED
  9  gateway/mode mismatch (TEST/LIVE isolation) -> REJECTED (MODE_MISMATCH)
 10  an already-authorized tx is NOT corrupted when readiness changes afterward

Offline only: forced SQLite + FakeStripeGateway. Run: python seller_eligibility_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./seller_eligibility_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["REAPER_DISABLED"] = "true"
os.environ["MIN_REPUTATION"] = "50"

for f in ("seller_eligibility_test.db", "seller_eligibility_test.db-wal",
          "seller_eligibility_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import datetime as _dt  # noqa: E402

import db as dbmod  # noqa: E402
from stripe_gateway import FakeStripeGateway, set_gateway  # noqa: E402
import stripe_connect as sc  # noqa: E402
import seller_eligibility as se  # noqa: E402

set_gateway(FakeStripeGateway())
dbmod.init_db()
s = dbmod.SessionLocal()
PW = "hunter2-correct-horse-xyz"
_n = [0]
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _now():
    return _dt.datetime.now(_dt.timezone.utc)


def seller(**user_fields):
    _n[0] += 1
    u = dbmod.create_user(s, f"elig_seller{_n[0]}", PW)
    for k, v in user_fields.items():
        setattr(u, k, v)
    s.add(u); s.commit()
    return u


def ready_ca(seller_id, **overrides):
    fields = dict(details_submitted=True, charges_enabled=True, payouts_enabled=True,
                  transfers_capability="active", country="US", gateway_mode="fake",
                  onboarding_state="enabled", last_synced_at=_now())
    fields.update(overrides)
    ca = dbmod.ConnectedAccount(user_id=seller_id,
                                stripe_account_id=f"acct_fake_el{seller_id}", **fields)
    s.add(ca); s.commit()
    return ca


def spec_for(seller_id):
    owner = dbmod.get_user_by_id(s, seller_id)
    sp = dbmod.save_specs(s, owner, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 2.0,
                                     "provider": owner.username, "gpu_model": "NVIDIA L4",
                                     "gpu_count": 1, "vram_gb": 24, "units": 2})
    sp.attested = True; sp.attest_pubkey = "x"; sp.status = "online"
    sp.last_seen = _now()
    s.add(sp); s.commit()
    return sp


# ---- 7. Connect ready -> ACCEPTED (and the structured result shape) ----
s7 = seller()
ready_ca(s7.id)
e = se.get_seller_job_eligibility(s, s7)
ok("7. Connect ready -> eligible, reason OK, rail=stripe_connect",
   e["eligible"] is True and e["reason_code"] == "OK" and e["rail"] == "stripe_connect")
ok("structured result exposes all independent conditions",
   all(k in e for k in ("eligible", "payout_ready", "reputation_ok", "fraud_ok",
                        "availability_ok", "mode_ok", "reason_code", "rail", "provider")))

# ---- 1. cached can_accept_paid_jobs=TRUE but live payout NOT ready -> REJECTED ----
s1 = seller(can_accept_paid_jobs=True)
ready_ca(s1.id, charges_enabled=False, payouts_enabled=False, transfers_capability="pending",
         onboarding_state="verifying")
e = se.get_seller_job_eligibility(s, s1)
ok("1. cached=TRUE but live payout not ready -> NOT eligible (cache is not the gate)",
   dbmod.get_user_by_id(s, s1.id).can_accept_paid_jobs is True
   and e["eligible"] is False and e["payout_ready"] is False
   and e["reason_code"] == "PAYOUT_NOT_READY")

# ---- 2. cached can_accept_paid_jobs=FALSE but live payout ready + good rep/risk -> ALLOWED ----
s2 = seller(can_accept_paid_jobs=False, reputation=100)
ready_ca(s2.id)
e = se.get_seller_job_eligibility(s, s2)
ok("2. cached=FALSE but live conditions pass -> ELIGIBLE (stale-false cache does not block)",
   dbmod.get_user_by_id(s, s2.id).can_accept_paid_jobs is False and e["eligible"] is True)

# ---- 3. payout ready + reputation below threshold -> REJECTED ----
s3 = seller(reputation=10)
ready_ca(s3.id)
e = se.get_seller_job_eligibility(s, s3)
ok("3. reputation below threshold -> REJECTED (REPUTATION_TOO_LOW), payout still ready",
   e["eligible"] is False and e["reason_code"] == "REPUTATION_TOO_LOW"
   and e["payout_ready"] is True and e["reputation_ok"] is False)

# ---- 4. payout ready + fraud/risk hold -> REJECTED ----
s4 = seller(reputation=100)
ready_ca(s4.id)
dbmod.place_payout_hold(s, s4.id, reason="under review")
e = se.get_seller_job_eligibility(s, s4)
ok("4. active fraud/risk hold -> REJECTED (FRAUD_HOLD)",
   e["eligible"] is False and e["reason_code"] == "FRAUD_HOLD" and e["fraud_ok"] is False)

# ---- 5. stale/unknown rail status -> FAIL CLOSED ----
s5 = seller(reputation=100)
ready_ca(s5.id, last_synced_at=_dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc))
e = se.get_seller_job_eligibility(s, s5)
ok("5. stale provider state -> FAIL CLOSED (PAYOUT_READINESS_STALE)",
   e["eligible"] is False and e["reason_code"] == "PAYOUT_READINESS_STALE")

# ---- 6. no implemented rail (NOT_IMPLEMENTED only / none configured) -> REJECTED ----
s6 = seller(reputation=100)   # no ConnectedAccount; Global Payouts rail is NOT_IMPLEMENTED
e = se.get_seller_job_eligibility(s, s6)
ok("6. no implemented payout rail -> REJECTED (NO_PAYOUT_RAIL)",
   e["eligible"] is False and e["reason_code"] == "NO_PAYOUT_RAIL")

# ---- 9. gateway/mode mismatch (TEST/LIVE isolation) -> REJECTED ----
s9 = seller(reputation=100)
ready_ca(s9.id, gateway_mode="real")     # 'real' rail while the process runs the FAKE gateway
e = se.get_seller_job_eligibility(s, s9)
ok("9. rail/mode mismatch -> REJECTED (MODE_MISMATCH), payout capability itself is fine",
   e["eligible"] is False and e["reason_code"] == "MODE_MISMATCH"
   and e["payout_ready"] is True and e["mode_ok"] is False)

# ---- 7/1/8/10 through the REAL authorize() money entry point ----
buyer = dbmod.create_user(s, "elig_buyer", PW)

# 7 (authorize accepts a fully-eligible seller)
sa = seller(reputation=100)
ready_ca(sa.id)
spec_a = spec_for(sa.id)
tx = sc.authorize(s, buyer, spec_a, 60)
ok("7b. authorize ACCEPTS a fully-eligible seller", tx is not None and tx.status)

# 10 (an already-authorized tx is not corrupted when readiness changes afterward)
tx_pub, tx_status_before, tx_auth_before = tx.public_id, tx.status, tx.authorization_amount
ca_a = s.query(dbmod.ConnectedAccount).filter(dbmod.ConnectedAccount.user_id == sa.id).first()
ca_a.charges_enabled = False; ca_a.payouts_enabled = False
ca_a.transfers_capability = "inactive"; ca_a.disabled_reason = "requirements.past_due"
s.add(ca_a); s.commit()
txr = sc.get_tx_by_public_id(s, tx_pub)
ok("10. readiness dropping afterward does NOT corrupt the already-authorized tx",
   txr is not None and txr.status == tx_status_before
   and txr.authorization_amount == tx_auth_before)
# ...and a NEW authorization for the now-restricted seller is refused (case 8)
spec_a2 = spec_for(sa.id)
_refused8 = False
try:
    sc.authorize(s, buyer, spec_a2, 60)
except sc.TransactionError as ex:
    _refused8 = "payout-ready" in str(ex)
ok("8. Connect restricted after listing -> a NEW authorization is REJECTED", _refused8)

# 1b (authorize refuses when cached=TRUE but live payout not ready)
s1b = seller(can_accept_paid_jobs=True, reputation=100)
ready_ca(s1b.id, charges_enabled=False, payouts_enabled=False, transfers_capability="pending")
spec_1b = spec_for(s1b.id)
_refused1 = False
try:
    sc.authorize(s, buyer, spec_1b, 60)
except sc.TransactionError as ex:
    _refused1 = "payout-ready" in str(ex)
ok("1b. authorize REJECTS despite cached can_accept_paid_jobs=TRUE (live re-check wins)",
   _refused1)

s.close()
for f in ("seller_eligibility_test.db", "seller_eligibility_test.db-wal",
          "seller_eligibility_test.db-shm"):
    try:
        os.remove(f)
    except OSError:
        pass

print(f"\n=== seller_eligibility: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
