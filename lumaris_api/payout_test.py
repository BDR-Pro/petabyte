"""payout_test.py — provider-neutral global payout layer (offline, deterministic).

Covers: coverage-dataset honesty, unimplemented adapters don't count, sanctioned
exclusion, recipient/currency enforcement, obligation immutability + one-payment,
aggregation reconciliation, deterministic routing + fallback, stablecoin consent
gating, and compliance fail-closed.
Run: python payout_test.py
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./payout_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["REAPER_DISABLED"] = "true"

for f in ("payout_test.db", "payout_test.db-wal", "payout_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import datetime as _dt
import db as dbmod
import payout_capabilities as cap
import payout_routing as routing
from payout_rails import (get_rail, PayoutRailType, RecipientType, CapabilityStatus,
                          NotImplementedRail)
from stripe_gateway import FakeStripeGateway, set_gateway
import stripe_connect as sc

# Postgres persists between suites in CI (only the first suite drops the schema), and the
# FakeStripeGateway restarts its deterministic acct_/pi_ counters each process — so start
# from a clean schema to avoid colliding with a prior suite's connected accounts.
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")

GW = set_gateway(FakeStripeGateway())
dbmod.init_db()

PASSES = FAILS = 0
def ok(label, cond):
    global PASSES, FAILS
    print(("PASS " if cond else "FAIL ") + label)
    if cond: PASSES += 1
    else:
        FAILS += 1
        raise AssertionError(label)


# ---------------- capability dataset honesty ----------------
summ = cap.coverage_summary()
ok("coverage: ACTIVE count is honestly reported (0 without real approval)",
   summ["active_count"] == 0)
ok("coverage: Connect countries are pending_provider_approval, not active",
   len(summ["pending_provider_approval_countries"]) >= 40)
ok("coverage: unimplemented rails are separated out",
   len(summ["not_implemented_countries"]) >= 1)
ok("coverage: sanctioned countries are blocked",
   {"IR", "KP", "CU"}.issubset(set(summ["blocked_sanctioned_countries"])))

# a sanctioned country is never payable, regardless of any row
ok("sanctioned country returns no active rails", cap.active_rails_for("IR", "individual", "usd") == [])
ok("is_sanctioned enforced", cap.is_sanctioned("KP") and not cap.is_sanctioned("US"))

# recipient-type + currency filtering
ok("US supports individual + company", len(cap.capabilities_for("US", "individual", "usd")) >= 1)
ok("currency mismatch filters out a row",
   cap.capabilities_for("US", "individual", "jpy") == [])

# an unimplemented adapter reports NOT_IMPLEMENTED and refuses to pay
gp = get_rail(PayoutRailType.STRIPE_GLOBAL_PAYOUTS)
capd = gp.get_country_capability("NG", RecipientType.INDIVIDUAL, "ngn")
ok("Global Payouts adapter reports NOT_IMPLEMENTED", capd.status == CapabilityStatus.NOT_IMPLEMENTED)
_raised = False
try:
    gp.send_payout(dbmod.SessionLocal(), object(), "k")
except NotImplementedRail:
    _raised = True
ok("unimplemented rail refuses to send (no fake success)", _raised)


# ---------------- helpers ----------------
def mk_seller(name, country="US"):
    s = dbmod.SessionLocal()
    u = dbmod.create_user(s, name, "pw-correct-horse-xyz")
    dbmod.set_role(s, name, "seller")
    u.country = country
    ca = sc.get_or_create_connected_account(s, u, country=country, email=f"{name}@x.com")
    GW.complete_onboarding(ca.stripe_account_id, ok=True)
    sc.refresh_connected_account(s, ca)
    # approve the country row so an ACTIVE rail exists for routing tests (test-only:
    # simulates a granted provider approval; the shipped dataset stays honest at 0)
    s.close()
    return u.id

def approve_sanctions(seller_id):
    s = dbmod.SessionLocal()
    s.add(dbmod.ComplianceDecision(seller_id=seller_id, screening_type="sanctions",
          provider="test", decision="APPROVED",
          expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=30)))
    s.commit(); s.close()

def add_obligation(seller_id, net, currency="usd", country="US"):
    s = dbmod.SessionLocal()
    # a standalone obligation (not tied to a real compute tx) for aggregation tests
    o = dbmod.PayoutObligation(seller_id=seller_id, currency=currency,
        gross_amount_minor=net, net_amount_minor=net, country=country, state="available",
        available_at=_dt.datetime.now(_dt.timezone.utc))
    s.add(o); s.commit(); oid = o.id; s.close()
    return oid


def _seller(seller_id):
    s = dbmod.SessionLocal(); u = dbmod.get_user_by_id(s, seller_id); s.close(); return u


# ---------------- routing: compliance fail-closed ----------------
sid = mk_seller("payout_s1", "US")
dec = routing.select_rail(dbmod.SessionLocal(), _seller(sid), amount_minor=500, currency="usd")
ok("routing FAILS CLOSED without a compliance decision", dec["blocked"] and "Compliance" in dec["explanation"])
approve_sanctions(sid)

# make the US Connect row ACTIVE for THIS test run by marking the dataset row approved
# (in-memory override so we can exercise routing; the on-disk dataset is unchanged).
_ds = cap.load_dataset()
for row in _ds["countries"]:
    if row["country_code"] == "US" and row["provider"] == "stripe":
        row["approved"] = True; row["availability_status"] = "active"
cap._load.cache_clear() if hasattr(cap._load, "cache_clear") else None
# re-point the loader at our mutated dict
cap._MUT = _ds
_orig_load = cap.load_dataset
cap.load_dataset = lambda path=None: cap._MUT

dec2 = routing.select_rail(dbmod.SessionLocal(), _seller(sid), amount_minor=500, currency="usd")
ok("routing selects Stripe Connect when active + compliant",
   dec2["rail_type"] == PayoutRailType.STRIPE_CONNECT and not dec2["blocked"])
ok("routing decision carries an explanation", "Selected stripe_connect" in dec2["explanation"])

# deterministic: same inputs -> same rail
dec3 = routing.select_rail(dbmod.SessionLocal(), _seller(sid), amount_minor=500, currency="usd")
ok("routing is deterministic", dec3["rail_type"] == dec2["rail_type"])

# sanctioned seller is blocked even if compliant + active dataset
ssan = mk_seller("payout_sanc", "US"); approve_sanctions(ssan)
_bad = _seller(ssan); _bad.country = "IR"
decs = routing.select_rail(dbmod.SessionLocal(), _bad, amount_minor=500, currency="usd")
ok("sanctioned seller country is blocked in routing", decs["blocked"] and "sanctioned" in decs["explanation"])


# ---------------- stablecoin requires consent ----------------
# add an ACTIVE stablecoin row for a country, but no seller consent -> not selected
for row in cap._MUT["countries"]:
    if row["country_code"] == "KE":
        row["approved"] = True; row["availability_status"] = "active"
        row["implementation_status"] = "implemented"
# stablecoin rail is NOT implemented in code, so it still won't be selected — prove
# that consent gating + not-implemented both keep it out:
skenya = mk_seller("payout_ke", "KE"); approve_sanctions(skenya)
_ke = _seller(skenya); _ke.country = "KE"
dec_nc = routing.select_rail(dbmod.SessionLocal(), _ke, amount_minor=500, currency="usdc",
                             consent_stablecoin=False)
ok("stablecoin is never auto-selected without consent (and not implemented)",
   dec_nc["rail_type"] != PayoutRailType.CIRCLE_STABLECOIN)


# ---------------- obligation aggregation + one-payment ----------------
sid2 = mk_seller("payout_agg", "US"); approve_sanctions(sid2)
o1 = add_obligation(sid2, 300); o2 = add_obligation(sid2, 450); o3 = add_obligation(sid2, 250)
s = dbmod.SessionLocal()
bals = routing.seller_balances(s, sid2)
ok("seller balances show available earnings", bals["available_minor"] == 1000)
batch = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid2),
                                      currency="usd", min_threshold_minor=500)
ok("aggregation creates ONE batch covering many obligations",
   batch is not None and batch.state == "paid")   # Connect transfer settles synchronously
ok("batch total reconciles to the sum of its obligations", batch.total_amount_minor == 1000)
paid = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.batch_id == batch.id).all()
ok("all three obligations attached to the one batch and marked paid",
   len(paid) == 3 and all(o.state == "paid" for o in paid))
ok("exactly one Stripe transfer created for the batch",
   len([t for t in GW.transfers.values() if t.get("metadata", {}).get("seller_id") == str(sid2)]) == 1)
ok("batch + its obligations are stamped TEST mode",
   batch.mode == "TEST" and all(o.mode == "TEST" for o in paid))
# a re-run does not create a second batch or double-pay (no available obligations left)
again = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid2), currency="usd")
ok("re-running aggregation does not double-pay (nothing available)", again is None)
# TEST/LIVE mode is immutable — test and live money can never be reclassified/merged
_immut = False
try:
    batch.mode = "LIVE"; s.commit()
except Exception:
    s.rollback(); _immut = True
ok("financial-record mode is immutable (test/live cannot be reclassified)", _immut)
s.close()

# one obligation can never belong to two batches (claim guard)
sid3 = mk_seller("payout_two", "US"); approve_sanctions(sid3)
add_obligation(sid3, 700)
s = dbmod.SessionLocal()
u3 = dbmod.get_user_by_id(s, sid3)
b1 = routing.create_and_send_batch(s, u3, currency="usd")
b2 = routing.create_and_send_batch(s, u3, currency="usd")
ok("second batch finds no unclaimed obligations", b1 is not None and b2 is None)
s.close()


# ---------------- cross-path anti-double-pay ----------------
# If the aggregation/batch layer already paid an earning's obligation, the DIRECT
# per-transaction transfer must refuse — one earning is paid by exactly one path.
sid5 = mk_seller("payout_xpath", "US"); approve_sanctions(sid5)
s = dbmod.SessionLocal()
_buyer = dbmod.create_user(s, "payout_xbuyer", "pw-correct-horse-xyz")
_sellerU = dbmod.get_user_by_id(s, sid5)
_spec = dbmod.save_specs(s, _sellerU, {"cpu": 8, "ram": 32, "duration": 24,
    "price_per_hour": 1.0, "provider": "payout_xpath", "gpu_model": "H100",
    "gpu_count": 1, "vram_gb": 80, "units": 1})
_tx = dbmod.ComputeTransaction(buyer_id=_buyer.id, seller_id=sid5, spec_id=_spec.id,
    currency="usd", pricing_snapshot="{}", status="PAYMENT_CAPTURED",
    authorization_amount=1000, captured_amount=1000, seller_net_amount=900)
s.add(_tx); s.commit(); s.refresh(_tx)
# a batch already paid this earning's obligation
s.add(dbmod.PayoutObligation(seller_id=sid5, compute_tx_id=_tx.id, currency="usd",
    gross_amount_minor=900, net_amount_minor=900, state="paid"))
s.commit()
_refused = False
try:
    sc.transfer_to_seller(s, _tx)
except sc.TransactionError:
    _refused = True
ok("direct transfer refuses a batch-paid earning (never paid twice across paths)", _refused)
ok("no Stripe transfer was created for the batch-paid earning",
   not any(t.get("metadata", {}).get("petabyte_tx") == _tx.public_id for t in GW.transfers.values()))
s.close()


# ---------------- below-threshold aggregation holds ----------------
sid4 = mk_seller("payout_small", "US"); approve_sanctions(sid4)
add_obligation(sid4, 120)
s = dbmod.SessionLocal()
b = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid4),
                                  currency="usd", min_threshold_minor=1000)
ok("below the minimum threshold, no payout batch is created", b is None)
s.close()

# ---------------- CodeRabbit regression fixes ----------------
# (a) unknown seller country FAILS CLOSED (never defaults to US, never bypasses sanctions)
s = dbmod.SessionLocal()
_nocc = dbmod.create_user(s, "payout_nocountry", "pw-correct-horse-xyz")
dbmod.set_role(s, "payout_nocountry", "seller"); s.commit()
approve_sanctions(_nocc.id)
_ncid = _nocc.id; s.close()
dec_nc2 = routing.select_rail(dbmod.SessionLocal(), _seller(_ncid), amount_minor=500, currency="usd")
ok("unknown seller country fails closed (no default to US)",
   dec_nc2["blocked"] and "no recorded payout country" in dec_nc2["explanation"])

# (b) enum hardening: an invalid recipient_type yields UNSUPPORTED, never a crash
capbad = get_rail(PayoutRailType.STRIPE_CONNECT).get_country_capability("US", "not_a_type", "usd")
ok("invalid recipient_type -> UNSUPPORTED (no exception)",
   capbad.status == CapabilityStatus.UNSUPPORTED and not capbad.usable)

# (c) accrued obligations auto-promote to available after available_at
sid_h = mk_seller("payout_hold", "US"); approve_sanctions(sid_h)
s = dbmod.SessionLocal()
past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
s.add(dbmod.PayoutObligation(seller_id=sid_h, currency="usd", gross_amount_minor=600,
    net_amount_minor=600, state="accrued", available_at=past)); s.commit()
avail = dbmod.available_obligations(s, sid_h, "usd")
ok("accrued obligation past its hold auto-promotes to available",
   len(avail) == 1 and avail[0].state == "available")
s.close()

# (d) an UNKNOWN provider outcome (timeout) is preserved for reconciliation, NOT released
sid_u = mk_seller("payout_unknown", "US"); approve_sanctions(sid_u)
add_obligation(sid_u, 700)
s = dbmod.SessionLocal()
from stripe_gateway import StripeError as _SE
_orig_ct = GW.create_transfer
def _boom(*a, **k):
    raise _SE("simulated network timeout")
GW.create_transfer = _boom
try:
    bu = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_u), currency="usd")
finally:
    GW.create_transfer = _orig_ct
ok("unknown provider outcome marks batch needs_reconciliation (not failed/released)",
   bu is not None and bu.state == "needs_reconciliation")
held = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.seller_id == sid_u).all()
ok("obligations stay claimed (batched) on unknown outcome — never released to available",
   all(o.state == "batched" and o.batch_id == bu.id for o in held))
# a retry re-sends the SAME batch (same idempotency key), not a new one -> no double-pay
again_u = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_u), currency="usd")
ok("no new batch is created for obligations already claimed by a needs_reconciliation batch",
   again_u is None)
s.close()

# restore the real loader
cap.load_dataset = _orig_load

print(f"\n=== payout: {PASSES} passed, {FAILS} failed ===")
for f in ("payout_test.db", "payout_test.db-wal", "payout_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
