"""funding_metrics_test.py — the canonical funding-metrics layer is real, scope-separated,
and honest (never fabricates).

Seeds authoritative rows (ComputeTransaction / SellerSpec / RoutingDecision / PayoutObligation)
and asserts funding_snapshot() computes GMV, net margin, retention, utilization and unfulfilled
demand correctly — and that REAL (LIVE) traction is 0 while only TEST money exists.

Offline only: forced SQLite. Run: python funding_metrics_test.py
"""
import os
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./funding_metrics_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["STRIPE_GATEWAY"] = "fake"

for _f in ("funding_metrics_test.db", "funding_metrics_test.db-wal", "funding_metrics_test.db-shm"):
    if os.path.exists(_f):
        os.remove(_f)

import db as dbmod          # noqa: E402
import funding_metrics as fm  # noqa: E402

dbmod.init_db()
s = dbmod.SessionLocal()
NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)
PW = "hunter2-correct-horse-xyz"
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


buyerA = dbmod.create_user(s, "fm_buyerA", PW)
buyerB = dbmod.create_user(s, "fm_buyerB", PW)
sellerA = dbmod.create_user(s, "fm_sellerA", PW)
sellerB = dbmod.create_user(s, "fm_sellerB", PW)
specA = dbmod.save_specs(s, sellerA, {"cpu": 8, "ram": 32, "duration": 3600, "price_per_hour": 2.0,
                                      "provider": "fm_sellerA", "gpu_model": "NVIDIA L4",
                                      "gpu_count": 1, "vram_gb": 24, "units": 4})
specA.status = "online"; specA.available_units = 1; specA.total_units = 4    # busy 3 of 4
s.add(specA); s.commit()


def mk_tx(buyer, seller, *, captured, fee, net, sfee, status="COMPLETED", mode="TEST",
          refunded=0, is_demo=False, days_ago=1):
    tx = dbmod.ComputeTransaction(
        buyer_id=buyer.id, seller_id=seller.id, spec_id=specA.id, pricing_snapshot="{}",
        status=status, mode=mode, is_demo=is_demo, captured_amount=captured,
        platform_fee_amount=fee, seller_net_amount=net, stripe_fee_amount=sfee,
        refunded_amount=refunded, created_at=NOW - timedelta(days=days_ago))
    s.add(tx); s.commit()
    return tx


# TEST money: buyer A repeats (first 40d ago, again 20d ago); buyer B once (5d ago, part refunded);
# plus one failed job. Small jobs -> processing fee (115) exceeds gross commission (85): margin < 0.
mk_tx(buyerA, sellerA, captured=250, fee=25, net=225, sfee=37, days_ago=40)
mk_tx(buyerA, sellerA, captured=100, fee=10, net=90, sfee=33, days_ago=20)
mk_tx(buyerB, sellerB, captured=500, fee=50, net=450, sfee=45, refunded=100, days_ago=5)
mk_tx(buyerB, sellerB, captured=0, fee=0, net=0, sfee=0, status="JOB_FAILED", days_ago=3)
# DEMO + LIVE decoys that must NEVER count as TEST or REAL traction:
mk_tx(buyerA, sellerA, captured=9999, fee=999, net=9000, sfee=0, is_demo=True, days_ago=1)

# routing decisions (global demand signal): 3 fulfilled, 1 not.
for i in range(3):
    s.add(dbmod.RoutingDecision(source="test", intent="{}", candidates="[]",
                                selected_spec_ids="[1]", explanation="ok", fulfilled=True))
s.add(dbmod.RoutingDecision(source="test", intent="{}", candidates="[]",
                            selected_spec_ids="[]", explanation="no capacity", fulfilled=False))
s.commit()

# payout obligations (TEST): outstanding 315 (accrued 225 + available 90), paid 450.
for net, st in ((225, "accrued"), (90, "available"), (450, "paid")):
    _tx = mk_tx(buyerA, sellerA, captured=net, fee=0, net=net, sfee=0, days_ago=60)
    o = dbmod.create_payout_obligation(s, seller_id=sellerA.id, compute_tx_id=_tx.id,
                                       currency="usd", net_amount_minor=net, mode="TEST")
    o.state = st; s.add(o); s.commit()

snap = fm.funding_snapshot(s, scope="test", now=NOW)
m = snap["money_minor"]; mk = snap["marketplace"]; r = snap["rates"]
lq = snap["liquidity"]; rt = snap["retention"]

# ---- money (canonical, demo/LIVE excluded) ----
# GMV = 250+100+500 + (225+90+450 obligation txs) = 1615; demo 9999 excluded.
ok("GMV = captured TEST money only (demo excluded)", m["gmv_captured"] == 1615)
ok("refunds summed from authoritative rows", m["refunds"] == 100)
ok("net GMV = gmv - refunds", m["net_gmv"] == 1615 - 100)
ok("gross platform revenue (commission)", m["platform_revenue_gross"] == 85)
ok("processing fees (platform card cost) tracked", m["processing_fees_est"] == 115)
ok("NET platform revenue = commission - processing (NEGATIVE on small jobs)",
   m["net_platform_revenue"] == 85 - 115)
ok("seller earnings summed", m["seller_earnings"] == 225 + 90 + 450 + (225 + 90 + 450))
ok("outstanding seller liability = unpaid obligations (225+90)",
   m["seller_liability_outstanding"] == 315)
ok("payouts paid = paid obligations (450)", m["payouts_paid"] == 450)

# ---- marketplace ----
ok("active buyers = distinct buyers with captured money", mk["active_buyers"] == 2)
ok("active sellers = distinct sellers with captured money", mk["active_sellers"] == 2)
ok("take rate gross = commission / gmv (~10% on the priced jobs)",
   r["take_rate_gross"] == round(85 / 1615, 4))
ok("job success rate = settled / (settled+failed) excludes the failed job",
   r["job_success_rate"] is not None and 0 < r["job_success_rate"] < 1)
ok("refund rate computed from gmv", r["refund_rate"] == round(100 / 1615, 4))

# ---- liquidity ----
ok("utilization = busy/total units (3/4)", lq["utilization"] == 0.75)
# duration is HOURS (not seconds): 1 available unit * 3600 rentable hours = 3600 GPU-hours.
ok("gpu_hours_available treats duration as hours (1 unit x 3600h = 3600, not /3600)",
   lq["gpu_hours_available"] == 3600)
ok("unfulfilled demand counted from routing decisions", lq["unfulfilled_demand"] == 1)
ok("fill rate = fulfilled / total routing decisions (3/4)", lq["fill_rate"] == 0.75)

# ---- retention (activity cohorts) ----
ok("repeat-buyer rate = buyers with >=2 purchases / all (buyerA repeats)",
   rt["repeat_buyer_rate"] == round(1 / 2, 4))
ok("30-day retention: buyerA's 2nd purchase (20d after 1st) counts",
   rt["buyer_retention_30d"] == 1.0)
ok("7-day retention: buyerA's 2nd purchase (20d later) does NOT count within 7d",
   rt["buyer_retention_7d"] == 0.0)

# ---- honesty: REAL (LIVE) traction is zero while only TEST money exists ----
real = fm.funding_snapshot(s, scope="real", now=NOW)
ok("REAL scope shows ZERO GMV (no LIVE money — never shows TEST as real)",
   real["money_minor"]["gmv_captured"] == 0)
ok("REAL scope has no real paid buyers yet", real["marketplace"]["active_buyers"] == 0)
ok("snapshot flags that demo data exists in the system", snap["contains_demo_data"] is True)
ok("TEST scope has real (test) data", snap["has_real_data"] is True)

# ---- demo scope isolates the seeded decoy, never mixed into test/real ----
demo = fm.funding_snapshot(s, scope="demo", now=NOW)
ok("DEMO scope sees ONLY the demo tx (9999), isolated from test/real",
   demo["money_minor"]["gmv_captured"] == 9999)

s.close()
for _f in ("funding_metrics_test.db", "funding_metrics_test.db-wal", "funding_metrics_test.db-shm"):
    try:
        os.remove(_f)
    except OSError:
        pass

print(f"\n=== funding_metrics: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
