"""Offline tests for the marketplace-intelligence endpoints (all SQL-backed, real data):
health dashboard, NL health summary, explainable routing + predicted success, seller
trust score, and the immutable transaction timeline.

Run: python marketplace_test.py
"""
import atexit
import os
import json

from cryptography.fernet import Fernet

os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
os.environ.setdefault("DATABASE_URL", "sqlite:///./marketplace_test.db")
os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "w"
os.environ["REAPER_DISABLED"] = "true"
os.environ["NOTIFY_STUB"] = "true"

_DB_FILES = ("marketplace_test.db", "marketplace_test.db-wal", "marketplace_test.db-shm")


def _cleanup_db():
    for f in _DB_FILES:
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass


_cleanup_db()                  # clean start: never inherit a previous run's SQLite state
atexit.register(_cleanup_db)   # robust teardown even if an assertion raises or SystemExit fires

from fastapi.testclient import TestClient  # noqa: E402
import db as dbmod  # noqa: E402
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()
import main  # noqa: E402
import marketplace_insight as mi  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---- empty marketplace: honest zeros, no crash ----
h0 = c.get("/marketplace/health")
ok("health serves 200 on an empty marketplace", h0.status_code == 200)
hj = h0.json()
ok("empty health is honest zeros (no fake data)",
   hj["supply"]["gpus_online"] == 0 and hj["economics_minor"]["gmv_captured"] == 0
   and hj["quality"]["job_success_rate_pct"] is None)

# ---- build a real bookable seller + a settled transaction ----
mode = dbmod.payments_mode()
s = dbmod.SessionLocal()
seller = dbmod.create_user(s, "mk_seller", "pw-correct-horse-1"); dbmod.set_role(s, "mk_seller", "seller")
spec = dbmod.save_specs(s, seller, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.5,
    "provider": "mk_seller", "gpu_model": "NVIDIA L4", "gpu_count": 1, "vram_gb": 24, "units": 2})
spec.attested = True; spec.attest_pubkey = "k"; spec.status = "online"; spec.last_seen = dbmod._utcnow()
spec.available_units = 2; spec.total_units = 2
spec.jobs_completed = 95; spec.jobs_failed = 5; spec.heartbeats = 500
spec.latency_sum_s = 120.0; spec.latency_n = 100
s.add(spec); s.commit()
seller_id, spec_pub = seller.id, spec.public_id

# a buyer (for the timeline, which requires auth as a party to the tx)
c.post("/register_user", json={"username": "mk_buyer", "password": "pw-correct-horse-1"})
buyer_t = c.post("/login", data={"username": "mk_buyer", "password": "pw-correct-horse-1"}).json()["access_token"]
BT = {"Authorization": f"Bearer {buyer_t}"}
buyer_id = main.get_user_by_username(s, "mk_buyer").id

# a completed ComputeTransaction (real economics) + its immutable event history
tx = dbmod.ComputeTransaction(buyer_id=buyer_id, seller_id=seller_id, spec_id=spec.id,
    currency="usd", pricing_snapshot="{}", status="COMPLETED", mode=mode,
    authorization_amount=200, captured_amount=150, platform_fee_amount=15, seller_net_amount=135)
s.add(tx); s.commit(); s.refresh(tx)
for frm, to in [(None, "DRAFT"), ("DRAFT", "PAYMENT_AUTHORIZED"), ("PAYMENT_AUTHORIZED", "GPU_RESERVED"),
                ("GPU_RESERVED", "RUNNING"), ("RUNNING", "METERING_FINALIZED"),
                ("METERING_FINALIZED", "PAYMENT_CAPTURED"), ("PAYMENT_CAPTURED", "COMPLETED")]:
    s.add(dbmod.ComputeTxEvent(tx_id=tx.id, from_state=frm, to_state=to, reason="ok", actor="test"))
s.commit()
tx_pub_ok = tx.public_id

# a FAILED transaction with a reason (for the "why failed" line)
txf = dbmod.ComputeTransaction(buyer_id=buyer_id, seller_id=seller_id, spec_id=spec.id,
    currency="usd", pricing_snapshot="{}", status="JOB_FAILED", mode=mode,
    authorization_amount=200, captured_amount=0)
s.add(txf); s.commit(); s.refresh(txf)
s.add(dbmod.ComputeTxEvent(tx_id=txf.id, from_state="RUNNING", to_state="JOB_FAILED",
                           reason="GPU disconnected after 83% of execution", actor="reaper"))
s.commit()
tx_pub_fail = txf.public_id

# a tx that ended in AUTHORIZATION_EXPIRED (a real terminal state) carrying an operational
# reason — it must be sanitized in the buyer timeline exactly like the other failures.
txe = dbmod.ComputeTransaction(buyer_id=buyer_id, seller_id=seller_id, spec_id=spec.id,
    currency="usd", pricing_snapshot="{}", status="AUTHORIZATION_EXPIRED", mode=mode,
    authorization_amount=300, captured_amount=0)
s.add(txe); s.commit(); s.refresh(txe)
s.add(dbmod.ComputeTxEvent(tx_id=txe.id, from_state="PAYMENT_AUTHORIZED",
                           to_state="AUTHORIZATION_EXPIRED",
                           reason="stripe auth voided after 7 days uncaptured", actor="reaper"))
s.commit()
tx_pub_expired = txe.public_id
s.close()

# ---- health reflects the real data ----
hj = c.get("/marketplace/health").json()
ok("health: seller GPU counted online", hj["supply"]["gpus_online"] == 1)
ok("health: available GPU-hours computed (2 units x 24h)", hj["supply"]["available_gpu_hours"] == 48)
ok("health: GMV = captured amount (150 minor)", hj["economics_minor"]["gmv_captured"] == 150)
ok("health: platform revenue + seller earnings real", hj["economics_minor"]["platform_revenue"] == 15
   and hj["economics_minor"]["seller_earnings"] == 135)

sm = c.get("/marketplace/health/summary").json()
ok("health summary is generated from live numbers", "Marketplace status" in sm["summary"] and "GMV" in sm["summary"])

# ---- financial-integrity heartbeat gauges are emitted by the scrape-time collector (#286) ----
_gauges = {r["name"]: r["value"] for r in main._marketplace_metrics()}
for _g in ("petabyte_ledger_balanced", "petabyte_ledger_imbalanced_tx",
           "petabyte_ledger_net_minor", "petabyte_payout_obligations_unbatched",
           "petabyte_oldest_unbatched_payout_age_seconds"):
    ok(f"collector emits {_g}", _g in _gauges)
ok("ledger heartbeat reports balanced on this marketplace",
   _gauges.get("petabyte_ledger_balanced") == 1 and _gauges.get("petabyte_ledger_imbalanced_tx") == 0)

# ---- explainable routing + predicted success ----
r = c.post("/route", json={"min_vram": 8, "hours": 1}).json()
ok("route selects the bookable node", len(r.get("selected", [])) == 1)
ok("route returns a plain-language explanation", bool(r.get("explanation")))
ok("route returns a ✓ checklist", isinstance(r.get("checklist"), list) and len(r["checklist"]) >= 3)
ps = r["selected"][0].get("predicted_success", {})
ok("route predicts a success probability from real history (0<p<=1)",
   0 < ps.get("probability", 0) <= 1 and any("completion" in f for f in ps.get("factors", [])))

# ---- finding 4: /solve returns a PUBLIC plan with no internal ORM caches ----
# select_plan embeds request-scoped _specs/_reputation (ORM SellerSpec objects) only for
# /route (opt-in). Any other boundary — /solve here — must never serialize them.
sol = c.post("/solve", headers=BT, json={"min_vram": 8, "hours": 1, "redundancy": 1}).json()
ok("/solve returns a placement plan over verified inventory",
   isinstance(sol.get("selected"), list) and len(sol["selected"]) == 1)
ok("/solve never leaks the internal _specs / _reputation caches (ORM objects)",
   "_specs" not in sol and "_reputation" not in sol)

# ---- seller trust score ----
ts = c.get(f"/sellers/{spec_pub}/trust").json()
ok("trust: 0-100 score + stars", 0 <= ts["trust_score"] <= 100 and 0 <= ts["stars"] <= 5)
ok("trust: completion rate from real jobs (95%)", ts["components"]["completion_rate_pct"] == 95.0)
ok("trust: untracked dims are null (never faked)",
   ts["components"]["buyer_rating"] is None and ts["components"]["uptime_pct"] is None)

# ---- finding P: a missing country normalizes to 'unknown', never 'UN' ----
ok("missing country (all sources empty) -> 'unknown', not 'UN'",
   main._norm_country(None, "", "   ") == "unknown")
ok("a present country normalizes to a 2-letter upper code",
   main._norm_country("us") == "US" and main._norm_country(None, "de") == "DE")
ok("the FIRST non-empty source wins (country over detected_country)",
   main._norm_country("CA", "US") == "CA")

# ---- immutable transaction timeline ----
tl = c.get(f"/payments/{tx_pub_ok}/timeline", headers=BT).json()
ok("timeline: buyer sees the full state history", len(tl["timeline"]) == 7 and tl["status"] == "COMPLETED")
ok("timeline: a completed tx has no failure reason", tl["why_failed"] is None)

# A buyer (non-admin) gets a SAFE, mapped failure explanation — never the raw operational
# reason (which can embed str(StripeError): gateway/decline/account internals).
RAW_FAIL = "GPU disconnected after 83% of execution"
tlf = c.get(f"/payments/{tx_pub_fail}/timeline", headers=BT).json()
ok("timeline: a failed tx explains why (buyer sees the safe mapped message)",
   tlf["status"] == "JOB_FAILED"
   and tlf["why_failed"] == mi.explain_failure("JOB_FAILED"))
ok("timeline: the buyer NEVER sees the raw operational failure reason",
   RAW_FAIL not in json.dumps(tlf))

# finding 3: AUTHORIZATION_EXPIRED is a terminal failure too — it must be sanitized and
# get a why_failed line (it was missing from TX_FAILED, so why_failed was silently None).
RAW_EXPIRED = "stripe auth voided after 7 days uncaptured"
tle = c.get(f"/payments/{tx_pub_expired}/timeline", headers=BT).json()
ok("timeline: AUTHORIZATION_EXPIRED is explained for the buyer (why_failed populated)",
   tle["status"] == "AUTHORIZATION_EXPIRED"
   and tle["why_failed"] == mi.explain_failure("AUTHORIZATION_EXPIRED"))
ok("timeline: the buyer never sees the raw AUTHORIZATION_EXPIRED operational reason",
   RAW_EXPIRED not in json.dumps(tle))

# a stranger cannot read someone else's timeline
c.post("/register_user", json={"username": "mk_stranger", "password": "pw-correct-horse-1"})
st = c.post("/login", data={"username": "mk_stranger", "password": "pw-correct-horse-1"}).json()["access_token"]
ok("timeline: a non-party cannot read the timeline (404)",
   c.get(f"/payments/{tx_pub_ok}/timeline", headers={"Authorization": f"Bearer {st}"}).status_code == 404)

# An admin DOES get the raw reason (for troubleshooting). _is_admin() reads ADMIN_USERS
# live, so registering an admin user + naming it here is enough; an admin need not be a party.
c.post("/register_user", json={"username": "mk_admin", "password": "pw-correct-horse-1"})
os.environ["ADMIN_USERS"] = "mk_admin"
at = c.post("/login", data={"username": "mk_admin", "password": "pw-correct-horse-1"}).json()["access_token"]
AH = {"Authorization": f"Bearer {at}"}
tla = c.get(f"/payments/{tx_pub_fail}/timeline", headers=AH).json()
ok("timeline: an admin sees the RAW failure reason (why_failed) for troubleshooting",
   tla["status"] == "JOB_FAILED" and RAW_FAIL in (tla["why_failed"] or ""))
ok("timeline: an admin sees the RAW reason on the failure event too",
   any(RAW_FAIL in (ev.get("reason") or "") for ev in tla["timeline"]))
os.environ.pop("ADMIN_USERS", None)

print(f"\n=== marketplace: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
# DB files are removed by the atexit handler registered at startup (robust on any exit path).
raise SystemExit(1 if _fail else 0)
