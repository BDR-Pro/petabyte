"""seller_payable_metric_test.py — the executive "Seller payable" metric is real and
mode-separated.

seller_payable_by_mode(db) powers the petabyte_seller_payable_minor scrape-time gauge. It must:
  * sum ONLY money that is owed-but-unpaid (states accrued/available/batched);
  * EXCLUDE paid / reversed / failed obligations;
  * key the result by lowercased money mode ('test'|'live') so a LIVE tile can never include
    TEST payable, and vice-versa.

Offline only: forced SQLite. Run: python seller_payable_metric_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./seller_payable_metric_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["STRIPE_GATEWAY"] = "fake"

for f in ("seller_payable_metric_test.db", "seller_payable_metric_test.db-wal",
          "seller_payable_metric_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import db as dbmod  # noqa: E402

dbmod.init_db()
s = dbmod.SessionLocal()
PW = "hunter2-correct-horse-xyz"
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


seller = dbmod.create_user(s, "sp_seller", PW)
buyer = dbmod.create_user(s, "sp_buyer", PW)
spec = dbmod.save_specs(s, seller, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 2.0,
                                    "provider": "sp_seller", "gpu_model": "NVIDIA L4",
                                    "gpu_count": 1, "vram_gb": 24, "units": 1})
s.commit()


def obligation(mode, net_minor, state):
    tx = dbmod.ComputeTransaction(buyer_id=buyer.id, seller_id=seller.id, spec_id=spec.id,
                                  pricing_snapshot="{}", status="PAYMENT_CAPTURED")
    s.add(tx); s.commit()
    o = dbmod.create_payout_obligation(
        s, seller_id=seller.id, compute_tx_id=tx.id, currency="usd",
        net_amount_minor=net_minor, mode=mode)
    o.state = state
    s.add(o); s.commit()
    return o


# LIVE owed = 250 + 150 + 100 = 500 ; a paid one is excluded.
obligation("live", 250, "accrued")
obligation("live", 150, "available")
obligation("live", 100, "batched")
obligation("live", 999, "paid")          # excluded (already paid out)
# TEST owed = 40 ; reversed/failed excluded.
obligation("test", 40, "accrued")
obligation("test", 7, "reversed")        # excluded
obligation("test", 3, "failed")          # excluded

payable = dbmod.seller_payable_by_mode(s)
ok("LIVE payable sums only owed states (250+150+100=500)", payable.get("live") == 500)
ok("TEST payable sums only owed states (40)", payable.get("test") == 40)
ok("paid/reversed/failed obligations are excluded from payable",
   payable.get("live") == 500 and payable.get("test") == 40)
ok("TEST and LIVE payable are reported as SEPARATE keys (never merged)",
   set(payable) == {"live", "test"} and payable["live"] != payable["test"])

s.close()
for f in ("seller_payable_metric_test.db", "seller_payable_metric_test.db-wal",
          "seller_payable_metric_test.db-shm"):
    try:
        os.remove(f)
    except OSError:
        pass

print(f"\n=== seller_payable_metric: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
