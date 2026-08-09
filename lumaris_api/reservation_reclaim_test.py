"""reservation_reclaim_test.py — abandoned reservations never hold GPU capacity indefinitely.

The buyer cancel path 409s once a job is dispatched, so a post-dispatch FAILURE would otherwise
leak its `stripe_reserved` booking + GPU unit forever. stripe_connect.reclaim_abandoned_
reservations (run by the maintenance loop) is the safety net. This proves it:

  * a TERMINAL-FAILED tx (JOB_FAILED) with a reserved unit -> reclaimed immediately;
  * a STUCK pre-capture tx (RUNNING, untouched past the timeout) -> reclaimed;
  * a FRESH pre-capture tx (RUNNING now) -> NOT reclaimed (job may be in flight);
  * a successful PAYMENT_CAPTURED rental -> NOT reclaimed;
and that the freed units return to the spec's available capacity.

Offline only: forced SQLite + FakeStripeGateway. Run: python reservation_reclaim_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./reservation_reclaim_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["REAPER_DISABLED"] = "true"

for f in ("reservation_reclaim_test.db", "reservation_reclaim_test.db-wal",
          "reservation_reclaim_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import datetime as _dt  # noqa: E402
from decimal import Decimal  # noqa: E402

import db as dbmod  # noqa: E402
from stripe_gateway import FakeStripeGateway, set_gateway  # noqa: E402
import stripe_connect as sc  # noqa: E402

set_gateway(FakeStripeGateway())
dbmod.init_db()
s = dbmod.SessionLocal()
PW = "hunter2-correct-horse-xyz"
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


seller = dbmod.create_user(s, "rr_seller", PW)
buyer = dbmod.create_user(s, "rr_buyer", PW)
spec = dbmod.save_specs(s, seller, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 2.0,
                                    "provider": "rr_seller", "gpu_model": "NVIDIA L4",
                                    "gpu_count": 1, "vram_gb": 24, "units": 5})
s.commit()
_OLD = _dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc)


def reserved_tx(status, updated_at):
    assert dbmod.try_reserve_unit(s, spec.id), "spec ran out of units in the fixture"
    b = dbmod.Booking(buyer_id=buyer.id, seller_id=seller.id, spec_id=spec.id, hours=1,
                      price_per_hour=Decimal("2"), gross_amount=Decimal("2"),
                      platform_fee=Decimal("0"), seller_payout=Decimal("2"),
                      status="stripe_reserved", test=True)
    s.add(b); s.commit()
    tx = dbmod.ComputeTransaction(buyer_id=buyer.id, seller_id=seller.id, spec_id=spec.id,
                                  booking_id=b.id, pricing_snapshot="{}", status=status,
                                  updated_at=updated_at)
    s.add(tx); s.commit()
    return tx, b


def avail():
    s.expire_all()
    return dbmod.get_spec_by_id(s, spec.id).available_units


txA, bA = reserved_tx("JOB_FAILED", _OLD)          # terminal failed -> reclaim now
txB, bB = reserved_tx("RUNNING", _OLD)             # stuck pre-capture -> reclaim
txC, bC = reserved_tx("RUNNING", _dt.datetime.now(_dt.timezone.utc))  # fresh -> keep
txD, bD = reserved_tx("PAYMENT_CAPTURED", _OLD)    # successful rental -> keep

ok("fixture reserved 4 units (available dropped from 5 to 1)", avail() == 1)

n = sc.reclaim_abandoned_reservations(s, stuck_after_s=3600)
ok("reclaim released exactly the 2 abandoned reservations (JOB_FAILED + stuck RUNNING)", n == 2)

s.expire_all()
ok("terminal-FAILED reservation booking is released", dbmod.get_booking_by_id(s, bA.id).status == "released_unused")
ok("stuck pre-capture reservation booking is released",
   dbmod.get_booking_by_id(s, bB.id).status == "released_unused")
ok("fresh RUNNING reservation is PRESERVED (job may be in flight)",
   dbmod.get_booking_by_id(s, bC.id).status == "stripe_reserved")
ok("successful PAYMENT_CAPTURED rental is PRESERVED",
   dbmod.get_booking_by_id(s, bD.id).status == "stripe_reserved")
ok("freed units returned to the spec (available back to 3)", avail() == 3)

# idempotent: a second pass reclaims nothing new
ok("reclaim is idempotent (second pass frees nothing)",
   sc.reclaim_abandoned_reservations(s, stuck_after_s=3600) == 0 and avail() == 3)

s.close()
for f in ("reservation_reclaim_test.db", "reservation_reclaim_test.db-wal",
          "reservation_reclaim_test.db-shm"):
    try:
        os.remove(f)
    except OSError:
        pass

print(f"\n=== reservation_reclaim: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
