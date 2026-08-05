"""Deterministic Stripe Connect demo (test mode, offline).

Runs the whole paid-compute money flow against the FAKE Stripe gateway using genuine
Stripe test-mode object shapes. GPU execution is SIMULATED and labelled as such; the
Stripe objects (PaymentIntent manual capture, Transfer, refund) are real in shape.

    python stripe_demo.py        # narrated end-to-end walkthrough + final ledger

Proves: seller onboards for payouts; a GPU becomes available; a buyer selects it;
payment is authorized before execution; the job is dispatched once; actual usage is
metered; only actual usage is captured; commission is computed; the seller net is
transferred once; buyer/seller/admin records agree; and the ledger balances.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./stripe_demo.db")
os.environ["SECRET_KEY"] = "demo-secret-not-for-production"
os.environ["SERVER_PRIVATE_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "whsec_demo")
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_demo_stripe")
os.environ.setdefault("PLATFORM_TAKE_RATE", "0.10")
os.environ.setdefault("PLATFORM_MIN_CHARGE_MINOR", "50")
os.environ["REAPER_DISABLED"] = "true"

for f in ("stripe_demo.db", "stripe_demo.db-wal", "stripe_demo.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import datetime as _dt
import db as dbmod
import stripe_connect as sc
from stripe_gateway import FakeStripeGateway, set_gateway

GW = set_gateway(FakeStripeGateway())
dbmod.init_db()
s = dbmod.SessionLocal()


def money(m):
    return f"${m/100:,.2f} ({m} minor)"


def line(t=""):
    print(t)


line("=" * 70)
line("  PETABYTE — Stripe Connect demo (TEST MODE, offline fake gateway)")
line("  GPU execution is SIMULATED; Stripe object shapes are genuine test-mode.")
line("=" * 70)

# 1) Seller onboards for payouts
seller = dbmod.create_user(s, "demo_seller", "pw-correct-horse-demo")
dbmod.set_role(s, "demo_seller", "seller")
ca = sc.get_or_create_connected_account(s, seller, country="US", email="demo_seller@example.com")
line("\n1. Seller onboarding")
line(f"   connected account: {ca.stripe_account_id}  (payout_ready={ca.payout_ready()})")
GW.complete_onboarding(ca.stripe_account_id, ok=True)
ca = sc.refresh_connected_account(s, ca)
line(f"   after Stripe onboarding: state={ca.onboarding_state}  payout_ready={ca.payout_ready()}")

# 2) A GPU becomes available
spec = dbmod.save_specs(s, seller, {"cpu": 16, "ram": 64, "duration": 48,
    "price_per_hour": 2.50, "provider": "demo_seller", "gpu_model": "H100",
    "gpu_count": 1, "vram_gb": 80, "units": 1})
spec.attested = True; spec.status = "online"
spec.last_seen = _dt.datetime.now(_dt.timezone.utc); s.add(spec); s.commit()
line(f"\n2. GPU listed: H100  ${float(spec.price_per_hour):.2f}/hr  ({spec.available_units} unit online, verified)")

# 3) Buyer selects it + 4) server quote
buyer = dbmod.create_user(s, "demo_buyer", "pw-correct-horse-demo")
q = sc.quote(s, spec, 3600)
line("\n3-4. Buyer requests a 1-hour job. SERVER quote:")
line(f"     estimated compute = {money(q['estimated_compute_amount'])}")
line(f"     authorization (est + 20% margin) = {money(q['authorization_amount'])}")

# 5) Buyer authorizes (manual-capture PaymentIntent)
tx = sc.authorize(s, buyer, spec, 3600)
line("\n5. Payment authorized BEFORE execution:")
line(f"     transaction {tx.public_id}  PaymentIntent {tx.stripe_payment_intent_id}")
line(f"     status={tx.status}  client_secret returned to browser only")
GW.confirm_payment_intent(tx.stripe_payment_intent_id)     # buyer confirms card
sc.mark_authorized(s, tx)
line(f"     card authorized (verified server-side) -> {tx.status}")

# 6) Reserve GPU  7) dispatch once
sc.reserve_gpu(s, tx)
line(f"\n6. GPU reserved atomically -> {tx.status}  (units left: {dbmod.get_spec_by_id(s, spec.id).available_units})")
sc.dispatch_job(s, tx, code="print('hello from a petabyte gpu')")
first_task = tx.task_id
sc.dispatch_job(s, tx)     # retry -> must NOT create a second task
line(f"7. Job dispatched once -> {tx.status}  (task {tx.task_id}; retry kept same task: {tx.task_id == first_task})")

# 8) Meter actual usage (30 minutes, not the full estimated hour)
sc.record_metering(s, tx, actual_seconds=1800, source="agent(simulated)")
line(f"\n8. Metered ACTUAL usage: {tx.metering_seconds}s (30m) from {tx.metering_source} -> {tx.status}")

# 9) Capture only actual usage  10) commission
sc.capture(s, tx)
line(f"\n9-10. Captured ACTUAL usage (not the {money(tx.authorization_amount)} hold):")
line(f"      captured      = {money(tx.captured_amount)}")
line(f"      platform fee  = {money(tx.platform_fee_amount)}  (10%)")
line(f"      seller net    = {money(tx.seller_net_amount)}")
line(f"      identity: captured == fee + net  -> {tx.captured_amount == tx.platform_fee_amount + tx.seller_net_amount}")
pi = GW.payment_intents[tx.stripe_payment_intent_id]
line(f"      unused authorization released (PI capturable now {money(pi['amount_capturable'])})")

# 11) Transfer seller net once
sc.transfer_to_seller(s, tx)
tid = tx.stripe_transfer_id
sc.transfer_to_seller(s, tx)   # retry -> must NOT create a second transfer
line(f"\n11. Seller transfer: {money(tx.transferred_amount)} -> {tx.stripe_connected_account_id}")
line(f"    transfer {tid}  (retry created no second transfer: {tx.stripe_transfer_id == tid})")
line(f"    final status -> {tx.status}")

# 12) Buyer receipt / 13) seller earnings / admin
line("\n12-13. Records agree:")
line(f"    BUYER receipt : authorized_max={money(tx.authorization_amount)}  final_charge={money(tx.captured_amount)}")
seller_net_total = sum(t.seller_net_amount for t in s.query(dbmod.ComputeTransaction).filter(
    dbmod.ComputeTransaction.seller_id == seller.id).all())
transferred_total = sum(t.transferred_amount for t in s.query(dbmod.ComputeTransaction).filter(
    dbmod.ComputeTransaction.seller_id == seller.id).all())
line(f"    SELLER earnings: net={money(seller_net_total)}  transferred={money(transferred_total)}")
plat = dbmod.get_or_create_platform(s)
line(f"    ADMIN: platform commission (ledger) = {dbmod.account_balance(s, dbmod.PLATFORM_REVENUE)} minor")

# Full ledger
line("\nADMIN — internal double-entry ledger for this transaction:")
for e in s.query(dbmod.LedgerEntry).filter(dbmod.LedgerEntry.entry_type.like("compute_%")).all():
    line(f"    {e.entry_type:18} {e.direction:6} {str(e.amount):>10}  {e.account}")
ok, broken = dbmod.ledger_is_balanced(s)
line(f"\n  ledger balanced: {ok}  (broken tx: {broken})")

line("\n" + "=" * 70)
line("  Proven: onboard -> available -> select -> AUTHORIZE-before-run -> dispatch")
line("  once -> meter -> capture ACTUAL only -> commission -> transfer once ->")
line("  buyer/seller/admin agree -> ledger balances. (Refund/dispute paths: stripe_test.py)")
line("=" * 70)

s.close()
for f in ("stripe_demo.db", "stripe_demo.db-wal", "stripe_demo.db-shm"):
    if os.path.exists(f):
        os.remove(f)
