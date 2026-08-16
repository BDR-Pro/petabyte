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
                          NotImplementedRail, PayoutRailError)
from stripe_gateway import FakeStripeGateway, set_gateway
import stripe_connect as sc

# Postgres persists between suites in CI (only the first suite drops the schema), and the
# FakeStripeGateway restarts its deterministic acct_/pi_ counters each process — so start
# from a clean schema to avoid colliding with a prior suite's connected accounts.
# GUARDED: only ever wipe a dedicated *petabyte_test database (or an explicit opt-in), so
# pointing DATABASE_URL at a real DB can never drop its public schema.
if dbmod.engine.dialect.name.startswith("postgres"):
    _dbname = (dbmod.engine.url.database or "")
    if _dbname.endswith("petabyte_test") or os.getenv("PAYOUT_TEST_ALLOW_DROP") == "true":
        with dbmod.engine.begin() as _c:
            _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    else:
        raise SystemExit(f"payout_test refuses to reset schema on non-test database "
                         f"{_dbname!r}; use a *petabyte_test DB or set "
                         f"PAYOUT_TEST_ALLOW_DROP=true")

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

def add_obligation(seller_id, net, currency="usd", country="US", mode=None, state="available",
                   compute_tx_id=None):
    s = dbmod.SessionLocal()
    o = dbmod.PayoutObligation(seller_id=seller_id, currency=currency, compute_tx_id=compute_tx_id,
        gross_amount_minor=net, net_amount_minor=net, country=country, state=state,
        available_at=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1))
    if mode:
        o.mode = mode
    s.add(o); s.commit(); oid = o.id; s.close()
    return oid


_TXN = [0]
def mk_captured_tx(seller_id, net=900):
    """A ComputeTransaction persisted in PAYMENT_CAPTURED with NO obligation (for
    direct-transfer + reconciliation tests). Connected-account id is wired for transfer."""
    _TXN[0] += 1
    s = dbmod.SessionLocal()
    buyer = dbmod.create_user(s, f"cr_buyer_{seller_id}_{_TXN[0]}", "pw-correct-horse-xyz")
    seller = dbmod.get_user_by_id(s, seller_id)
    spec = dbmod.save_specs(s, seller, {"cpu": 8, "ram": 32, "duration": 24,
        "price_per_hour": 1.0, "provider": seller.username, "gpu_model": "H100",
        "gpu_count": 1, "vram_gb": 80, "units": 1})
    ca = s.query(dbmod.ConnectedAccount).filter(dbmod.ConnectedAccount.user_id == seller_id).first()
    tx = dbmod.ComputeTransaction(buyer_id=buyer.id, seller_id=seller_id, spec_id=spec.id,
        currency="usd", pricing_snapshot="{}", status="PAYMENT_CAPTURED",
        authorization_amount=net + 100, captured_amount=net + 100, seller_net_amount=net,
        stripe_connected_account_id=(ca.stripe_account_id if ca else None))
    s.add(tx); s.commit(); tid = tx.id; s.close()
    return tid


def _seller(seller_id):
    s = dbmod.SessionLocal(); u = dbmod.get_user_by_id(s, seller_id); s.close(); return u


# ---------------- routing: compliance fail-closed ----------------
sid = mk_seller("payout_s1", "US")
dec = routing.select_rail(dbmod.SessionLocal(), _seller(sid), amount_minor=500, currency="usd")
ok("routing FAILS CLOSED without a compliance decision", dec["blocked"] and "Compliance" in dec["explanation"])
approve_sanctions(sid)

# make the US Connect row ACTIVE for THIS test run by marking the dataset row approved.
# DEEP-COPY first so we never mutate the lru_cached dataset object (that would corrupt
# the shared cache for every other caller); the on-disk dataset is untouched.
import copy as _copy
_ds = _copy.deepcopy(cap.load_dataset())
for row in _ds["countries"]:
    if row["country_code"] == "US" and row["provider"] == "stripe":
        row["approved"] = True; row["availability_status"] = "active"
# re-point the loader at our private, mutated copy
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

# SPLIT-BRAIN FIX: a settled batch DEBITS the seller's seller_payable in the double-entry ledger
# (mirroring the admin transfer path) so the ledger's seller-liability reconciles with the paid
# obligations instead of growing forever.
def _psettled(direction=None, account=None):
    q = (s.query(dbmod.LedgerEntry).join(dbmod.LedgerTx, dbmod.LedgerEntry.tx_id == dbmod.LedgerTx.id)
         .filter(dbmod.LedgerTx.reference_id == batch.public_id,
                 dbmod.LedgerEntry.entry_type == "payout_settled"))
    if direction:
        q = q.filter(dbmod.LedgerEntry.direction == direction)
    if account:
        q = q.filter(dbmod.LedgerEntry.account == account)
    return q.all()
_dr = _psettled(dbmod.DEBIT, dbmod.acct_seller_payable(sid2))
ok("settled batch posts a seller_payable DEBIT == batch total (split-brain fixed)",
   len(_dr) == 1 and int(_dr[0].amount) == 1000)
_readded = routing._add_batch_payout_ledger(s, batch)   # attempt a re-post (same batch key)
s.commit()
ok("batch payout ledger leg is idempotent (re-post adds nothing)",
   _readded is False and len(_psettled()) == 2)
_bal_ok, _ = dbmod.ledger_is_balanced(s)
ok("ledger balances after the batch-payout leg", _bal_ok)
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

# ================= CodeRabbit round 2: direct-transfer vs batch double-pay =================
# (1a) direct transfer claims the obligation -> a batch can never pay the same earning.
sid_d = mk_seller("cr_direct", "US"); approve_sanctions(sid_d)
txd = mk_captured_tx(sid_d, 900)
add_obligation(sid_d, 900, compute_tx_id=txd)          # available, linked to the tx
s = dbmod.SessionLocal()
sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txd))
od = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txd).first()
ok("direct transfer settles the obligation to paid", od.state == "paid")
ok("a batch cannot pay a directly-transferred earning",
   routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_d), currency="usd") is None)
s.close()

# (1b) batch claims first -> the direct transfer refuses (fail closed).
sid_b = mk_seller("cr_batch", "US"); approve_sanctions(sid_b)
txb = mk_captured_tx(sid_b, 800)
add_obligation(sid_b, 800, compute_tx_id=txb)
s = dbmod.SessionLocal()
bb = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_b), currency="usd")
ob = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txb).first()
ok("batch settles the obligation to paid", bb is not None and ob.state == "paid")
_refb = False
try:
    sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txb))
except sc.TransactionError:
    _refb = True
ok("direct transfer refuses a batch-paid earning (no double pay)", _refb)
s.close()

# (1c) crash window: an obligation left 'transferring' by a crashed direct transfer is
# NON-batchable, so no batch can pay it before reconciliation.
sid_cw = mk_seller("cr_crash", "US"); approve_sanctions(sid_cw)
add_obligation(sid_cw, 500, state="transferring")
s = dbmod.SessionLocal()
ok("a 'transferring' obligation is not batchable (crash-window safe)",
   dbmod.available_obligations(s, sid_cw, "usd") == [])
ok("no batch is created for a 'transferring' earning",
   routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_cw), currency="usd") is None)
s.close()

# (1d) unknown direct-transfer outcome -> obligation 'reconciling', never released.
sid_du = mk_seller("cr_direct_unknown", "US"); approve_sanctions(sid_du)
txu = mk_captured_tx(sid_du, 700)
add_obligation(sid_du, 700, compute_tx_id=txu)
s = dbmod.SessionLocal()
_octd = GW.create_transfer
def _boom_t(*a, **k):
    raise _SE("simulated network timeout")
GW.create_transfer = _boom_t
try:
    try:
        sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txu))
    except sc.TransactionError:
        pass
finally:
    GW.create_transfer = _octd
odu = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txu).first()
ok("unknown direct-transfer outcome leaves obligation 'reconciling' (not released)",
   odu.state == "reconciling")
ok("no batch pays a 'reconciling' earning",
   routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_du), currency="usd") is None)
s.close()

# ================= (2) TEST/LIVE obligation separation, both directions =================
sid_m = mk_seller("cr_mode", "US"); approve_sanctions(sid_m)
add_obligation(sid_m, 400, mode="TEST")
add_obligation(sid_m, 900, mode="LIVE")
s = dbmod.SessionLocal()
bt = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_m), currency="usd")   # mode=TEST
ok("TEST batch aggregates only TEST obligations",
   bt is not None and bt.mode == "TEST" and bt.total_amount_minor == 400)
live_ob = (s.query(dbmod.PayoutObligation)
           .filter(dbmod.PayoutObligation.seller_id == sid_m, dbmod.PayoutObligation.mode == "LIVE").first())
ok("a LIVE obligation is never swept into a TEST batch", live_ob.state == "available")
s.close()
_opm = dbmod.payments_mode
dbmod.payments_mode = lambda: "LIVE"     # simulate LIVE mode (no live keys, fake gateway)
try:
    s = dbmod.SessionLocal()
    bl = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_m), currency="usd")
    ok("LIVE batch aggregates only LIVE obligations",
       bl is not None and bl.mode == "LIVE" and bl.total_amount_minor == 900)
    s.close()
finally:
    dbmod.payments_mode = _opm

# ================= (3) obligation durable with capture — reconcile repair =================
sid_r = mk_seller("cr_recon", "US")
txr = mk_captured_tx(sid_r, 600)          # PAYMENT_CAPTURED, obligation creation "failed"
s = dbmod.SessionLocal()
ok("captured tx starts with no obligation (simulated creation failure)",
   s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txr).count() == 0)
sc.reconcile_captured_without_obligations(s)
ok("reconcile creates the missing obligation",
   s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txr).count() == 1)
sc.reconcile_captured_without_obligations(s)
ok("reconcile is idempotent — exactly one obligation, no duplicate",
   s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txr).count() == 1)
s.close()

# ================= (4) revalidate claimed_total below threshold -> abort =================
sid_p = mk_seller("cr_partial", "US"); approve_sanctions(sid_p)
oa = add_obligation(sid_p, 600)
obb = add_obligation(sid_p, 600)
s = dbmod.SessionLocal()
# simulate a concurrent batch winning obligation B after the read but before our claim:
s.execute(dbmod.update(dbmod.PayoutObligation).where(dbmod.PayoutObligation.id == obb)
          .values(state="batched")); s.commit()
_real_ao = dbmod.available_obligations
def _ao_both(db, seller_id, currency=None, mode=None):   # both looked available at read time
    return db.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.id.in_([oa, obb])).all()
dbmod.available_obligations = _ao_both
try:
    pb = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_p), currency="usd",
                                       min_threshold_minor=1000)
finally:
    dbmod.available_obligations = _real_ao
ok("batch below threshold after partial claim is ABORTED, not sent",
   pb is not None and pb.state == "aborted")
oa_row = s.get(dbmod.PayoutObligation, oa)
ok("aborted batch releases its claimed obligations back to available",
   oa_row.state == "available" and oa_row.batch_id is None)
# an ABORTED batch is TERMINAL: a later run must NOT replay it — it creates a NEW batch.
_aborted_id, _aborted_key = pb.id, pb.idempotency_key
s.execute(dbmod.update(dbmod.PayoutObligation).where(dbmod.PayoutObligation.id == obb)
          .values(state="available", batch_id=None)); s.commit()   # release B too
nb = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_p), currency="usd")
ok("an aborted batch is NOT replayed; a new payable batch is created with a different "
   "id + idempotency key",
   nb is not None and nb.id != _aborted_id and nb.idempotency_key != _aborted_key
   and nb.state == "paid")
s.close()

# ================= (5) failed batch is terminal; retry uses a NEW key =================
sid_f = mk_seller("cr_failed", "US"); approve_sanctions(sid_f)
add_obligation(sid_f, 500)
s = dbmod.SessionLocal()
_rail = get_rail(PayoutRailType.STRIPE_CONNECT)
_origsend = _rail.send_payout
_st = {"n": 0}
def _send_fail_once(db, obligation, key):
    if _st["n"] == 0:
        _st["n"] += 1
        raise PayoutRailError("simulated definite failure (no money moved)")
    return _origsend(db, obligation, key)
_rail.send_payout = _send_fail_once
try:
    b1 = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_f), currency="usd")
    of = (s.query(dbmod.PayoutObligation)
          .filter(dbmod.PayoutObligation.seller_id == sid_f).first())
    ok("definite rail failure -> batch 'failed' and obligation released",
       b1 is not None and b1.state == "failed" and of.state == "available" and of.batch_id is None)
    b2 = routing.create_and_send_batch(s, dbmod.get_user_by_id(s, sid_f), currency="usd")
    ok("retry creates a NEW batch with a NEW idempotency key (failed is not replayed)",
       b2 is not None and b2.id != b1.id and b2.idempotency_key != b1.idempotency_key)
    ok("the retry batch succeeds and is paid", b2.state == "paid")
finally:
    _rail.send_payout = _origsend
s.close()

# ================= (round 3 / fix 5) reconciled obligation keeps the tx's ORIGINAL mode ===
sid_tm = mk_seller("cr_txmode", "US")
txm = mk_captured_tx(sid_tm, 400)            # tx.mode defaults to TEST at creation
s = dbmod.SessionLocal()
_opm2 = dbmod.payments_mode
dbmod.payments_mode = lambda: "LIVE"         # app switched to LIVE AFTER the TEST tx
try:
    sc.reconcile_captured_without_obligations(s)
finally:
    dbmod.payments_mode = _opm2
om = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txm).first()
ok("a reconciled obligation keeps the tx's ORIGINAL mode (TEST), not the current LIVE mode",
   om is not None and om.mode == "TEST")
s.close()

# ================= (round 3 / fix 6) transfer requires OWNING the obligation ==============
# missing obligation (repair patched to a no-op) -> fail closed, no transfer.
sid_mo = mk_seller("cr_missing", "US")
txmo = mk_captured_tx(sid_mo, 500)
s = dbmod.SessionLocal()
_oe = sc._ensure_payout_obligation
sc._ensure_payout_obligation = lambda db, tx: None
_mo_refused = False
try:
    sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txmo))
except sc.TransactionError:
    _mo_refused = True
finally:
    sc._ensure_payout_obligation = _oe
ok("missing obligation -> transfer fails closed (no ownership)",
   _mo_refused and s.get(dbmod.ComputeTransaction, txmo).stripe_transfer_id is None)
s.close()

# incompatible obligation states -> fail closed, no transfer.
for _bad in ("failed", "reversed", "batched", "paid"):
    sid_bs = mk_seller(f"cr_bad_{_bad}", "US")
    txbs = mk_captured_tx(sid_bs, 500)
    add_obligation(sid_bs, 500, compute_tx_id=txbs, state=_bad)
    s = dbmod.SessionLocal()
    _ref = False
    try:
        sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txbs))
    except sc.TransactionError:
        _ref = True
    ok(f"transfer fails closed when the obligation is '{_bad}'",
       _ref and s.get(dbmod.ComputeTransaction, txbs).stripe_transfer_id is None)
    s.close()

# successful claim -> obligation 'paid', exactly ONE transfer.
sid_ok = mk_seller("cr_owned", "US")
txok = mk_captured_tx(sid_ok, 900)
add_obligation(sid_ok, 900, compute_tx_id=txok, state="available")
s = dbmod.SessionLocal()
sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, txok))
_ook = s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.compute_tx_id == txok).first()
_txok = s.get(dbmod.ComputeTransaction, txok)
ok("successful claim transitions the obligation to paid and records a transfer",
   _ook.state == "paid" and _txok.stripe_transfer_id is not None)
ok("exactly one Stripe transfer is created for the owned obligation",
   len([t for t in GW.transfers.values()
        if t.get("metadata", {}).get("petabyte_tx") == _txok.public_id]) == 1)
s.close()

# ============= H2: the DIRECT admin transfer enforces the same payout-time gates ==========
# as the batch path (audit HIGH: transfer_to_seller used to skip sanctions + fraud/review holds).
# (a) a seller under a fraud/manual-review payout hold is refused by the direct transfer.
sid_h2h = mk_seller("h2_hold", "US")
tx_h2h = mk_captured_tx(sid_h2h, 900)
add_obligation(sid_h2h, 900, compute_tx_id=tx_h2h, state="available")
s = dbmod.SessionLocal()
dbmod.place_payout_hold(s, sid_h2h, reason="fraud review")
_h2_held = False
try:
    sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, tx_h2h))
except sc.TransactionError:
    _h2_held = True
ok("direct transfer refuses a seller under a payout hold (parity with batch)",
   _h2_held and s.get(dbmod.ComputeTransaction, tx_h2h).stripe_transfer_id is None)
# it pays once the hold clears (proves the gate, not a permanent block)
dbmod.clear_payout_hold(s, sid_h2h)
sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, tx_h2h))
ok("direct transfer succeeds after the payout hold is cleared",
   s.get(dbmod.ComputeTransaction, tx_h2h).stripe_transfer_id is not None)
s.close()

# (b) a sanctioned payout country is refused by the direct transfer.
sid_h2s = mk_seller("h2_sanctioned", "IR")     # Iran — on the sanctioned block list
tx_h2s = mk_captured_tx(sid_h2s, 900)
add_obligation(sid_h2s, 900, compute_tx_id=tx_h2s, state="available")
s = dbmod.SessionLocal()
_h2_sanc = False
try:
    sc.transfer_to_seller(s, s.get(dbmod.ComputeTransaction, tx_h2s))
except sc.TransactionError:
    _h2_sanc = True
ok("direct transfer refuses a sanctioned seller country (fail closed)",
   _h2_sanc and s.get(dbmod.ComputeTransaction, tx_h2s).stripe_transfer_id is None)
s.close()


# ---------------- biweekly payout run: 14-day hold + report hold ----------------
sid_bw = mk_seller("payout_biweekly", "US"); approve_sanctions(sid_bw)
# two earnings, still WITHIN the 14-day risk hold (available_at in the future) -> accrued
s = dbmod.SessionLocal()
future = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=14)
for net in (400, 350):
    s.add(dbmod.PayoutObligation(seller_id=sid_bw, currency="usd", gross_amount_minor=net,
        net_amount_minor=net, country="US", state="accrued",
        risk_hold_until=future, available_at=future))
s.commit(); s.close()


def _my_batches(batches, sid):
    return [b for b in batches if b.seller_id == sid]


s = dbmod.SessionLocal()
ok("biweekly: earnings inside the 14-day hold are NOT paid",
   len(_my_batches(routing.run_scheduled_payouts(s), sid_bw)) == 0)
ok("biweekly: held earnings show as pending (in risk hold)",
   routing.seller_balances(s, sid_bw)["pending_minor"] == 750)

# the hold elapses -> mature the earnings
past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=1)
s.query(dbmod.PayoutObligation).filter(dbmod.PayoutObligation.seller_id == sid_bw)\
    .update({dbmod.PayoutObligation.available_at: past})
s.commit()

# a report puts the seller under review -> even matured earnings are withheld
dbmod.place_payout_hold(s, sid_bw, reason="reported")
ok("biweekly: a reported seller is NOT paid even after the hold elapses",
   len(_my_batches(routing.run_scheduled_payouts(s), sid_bw)) == 0)

# review clears -> the biweekly run pays the ACCUMULATED total in ONE payout
dbmod.clear_payout_hold(s, sid_bw)
paid_batches = _my_batches(routing.run_scheduled_payouts(s), sid_bw)
ok("biweekly: after review clears, ONE batch pays the accumulated 14-day total (750)",
   len(paid_batches) == 1 and paid_batches[0].total_amount_minor == 750
   and paid_batches[0].state == "paid")
ok("biweekly: re-running the same day does not double-pay",
   len(_my_batches(routing.run_scheduled_payouts(s), sid_bw)) == 0)
s.close()

# restore the real loader
cap.load_dataset = _orig_load

# ---------------- instant payout fee (a revenue line; scheduled stays free) ----------------
from db import LedgerTx, LedgerEntry, PLATFORM_REVENUE   # noqa: E402
s = dbmod.SessionLocal()
_u = dbmod.create_user(s, "instpayee", "pw-abcdefghij")
dbmod.credit_earnings(s, _u.id, 100.0)
_m = dbmod.add_payout_method(s, _u, "usdc", "0xfeed", label="w")
_m.verified = True; s.add(_m); s.commit()

ok("instant fee floors at the flat minimum for small amounts ($10 -> $0.50)",
   abs(float(dbmod.instant_payout_fee(10)) - 0.50) < 1e-9)
ok("instant fee scales by pct on larger amounts ($1000 -> $15.00 at 1.5%)",
   abs(float(dbmod.instant_payout_fee(1000)) - 15.0) < 1e-9)

# scheduled (free) payout: no fee, full amount sent
_pf = dbmod.request_payout(s, _u, _m, 20.0)
ok("scheduled payout charges NO fee and sends the full amount",
   float(_pf.fee_usd or 0) == 0.0 and float(_pf.amount_usd) == 20.0)

# instant payout: fee deducted, net = amount - fee, fee booked to PLATFORM_REVENUE
_fee = float(dbmod.instant_payout_fee(40))
_pi = dbmod.request_payout(s, _u, _m, 40.0, fee=_fee)
ok("instant payout: net sent = amount - fee, fee recorded on the payout",
   abs(float(_pi.amount_usd) - (40.0 - _fee)) < 1e-6 and abs(float(_pi.fee_usd) - _fee) < 1e-6)
ok("earnings drop by the GROSS (20 + 40 = 60), not the net — the fee comes out of the withdrawal",
   abs(float(dbmod.get_user_by_id(s, _u.id).earnings) - 40.0) < 1e-6)
_tx = (s.query(LedgerTx).filter(LedgerTx.reference_type == "payout",
                                LedgerTx.reference_id == str(_pi.id)).first())
_rev = sum(float(e.amount) for e in s.query(LedgerEntry).filter(LedgerEntry.tx_id == _tx.id).all()
           if e.account == PLATFORM_REVENUE and e.direction == "credit")
ok("the instant fee is booked to PLATFORM_REVENUE as a balanced ledger leg (real revenue)",
   abs(_rev - _fee) < 1e-6)

# a FAILED instant payout refunds the GROSS (net + fee) — seller is fully made whole
dbmod.set_payout_status(s, _pi, "failed")
ok("a FAILED instant payout refunds the GROSS (net + fee), not just the net",
   abs(float(dbmod.get_user_by_id(s, _u.id).earnings) - (40.0 + 40.0)) < 1e-6)

# guard: an amount at/under the fee is refused for instant (fee must be smaller than amount)
ok("instant is refused when the fee would meet/exceed the amount (no zero/negative payout)",
   dbmod.request_payout(s, _u, _m, 0.40, fee=float(dbmod.instant_payout_fee(0.40))) is None)
s.close()

# ---------------- anti-fraud payout holds (clearing window + instant maturity) ----------------
import datetime as _dt2  # noqa: E402
s = dbmod.SessionLocal()
_hu = dbmod.create_user(s, "holdseller", "pw-abcdefghij")
dbmod.credit_earnings(s, _hu.id, 100.0)
_buyer = dbmod.create_user(s, "holdbuyer", "pw-abcdefghij")


def _spec_for(uid):
    sp = dbmod.SellerSpec(user_id=uid, cpu=4, ram=16, price_per_hour=dbmod.q(1),
                          duration=24, gpu_model="RTX 4090")
    s.add(sp); s.commit(); return sp.id


def _released_booking(seller_id, buyer_id, spec_id, payout, released_at):
    b = dbmod.Booking(buyer_id=buyer_id, seller_id=seller_id, spec_id=spec_id, hours=1,
                      price_per_hour=dbmod.q(payout), gross_amount=dbmod.q(payout),
                      platform_fee=dbmod.q(0), seller_payout=dbmod.q(payout),
                      status="released", released_at=released_at)
    s.add(b); s.commit(); return b


_now = dbmod._utcnow().replace(tzinfo=None)
_hspec = _spec_for(_hu.id)
# a booking released JUST NOW -> its payout is still in the clearing window (held)
_released_booking(_hu.id, _buyer.id, _hspec, 30.0, _now)
ok("earnings from a just-completed job are HELD (not withdrawable during the clearing window)",
   float(dbmod.withdrawable_earnings(s, _hu)) == 70.0)          # 100 earnings - 30 held
# a booking released well before the window -> already cleared, not held
_released_booking(_hu.id, _buyer.id, _hspec, 20.0, _now - _dt2.timedelta(hours=dbmod.EARNINGS_HOLD_HOURS + 1))
ok("earnings that have passed the hold window ARE withdrawable (old completion adds no hold)",
   float(dbmod.withdrawable_earnings(s, _hu)) == 70.0)          # still 70 — only the recent one holds

# instant-payout maturity: a fresh seller must earn rep + N cleared jobs before fast cash-out
_newbie = dbmod.create_user(s, "newbieseller", "pw-abcdefghij")
_nspec = _spec_for(_newbie.id)
ok("a brand-new seller is NOT instant-eligible (fast cash-out locked)",
   dbmod.is_payout_matured(s, _newbie) is False)
for _i in range(dbmod.PAYOUT_MATURITY_MIN_JOBS):
    _released_booking(_newbie.id, _buyer.id, _nspec, 1.0,
                      _now - _dt2.timedelta(hours=dbmod.EARNINGS_HOLD_HOURS + 5))
_newbie.reputation = dbmod.MIN_REPUTATION; s.add(_newbie); s.commit()
ok("instant unlocks once the seller has cleared N jobs in good standing",
   dbmod.is_payout_matured(s, _newbie) is True)
s.close()

print(f"\n=== payout: {PASSES} passed, {FAILS} failed ===")
for f in ("payout_test.db", "payout_test.db-wal", "payout_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)
