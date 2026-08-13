"""data_api_test.py — the paid, metered data API. Hermetic (TestClient), offline.

Proves the pay-as-you-go model the product promises:
  * a `data`-scoped API key is required (node/jobs keys are refused);
  * calls within the free monthly quota are served free and not billed;
  * past the quota, each call is billed per-call from the WALLET BALANCE and booked to
    platform revenue — and a call that the balance can't cover is REFUSED (402), not given away;
  * /usage is free to check and never itself billed;
  * price HISTORY is served from recorded snapshots.

Run: python data_api_test.py
"""
import os

os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///./data_api_test.db"
os.environ["DATA_API_FREE_CALLS_MONTH"] = "2"     # tiny quota so we cross it in the test
os.environ["DATA_API_PRICE_PER_1K"] = "1000"      # -> $1.00 per billable call (easy to assert)
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["REAPER_DISABLED"] = "true"

for f in ("data_api_test.db", "data_api_test.db-wal", "data_api_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import db as dbm  # noqa: E402

c = TestClient(main.app)
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _code(r):
    try:
        return (r.json().get("error") or {}).get("code") or (r.json().get("detail") or {})
    except Exception:
        return None


c.post("/register_user", json={"username": "dataco", "password": "hunter2-correct-horse"})
_tok = c.post("/login", data={"username": "dataco", "password": "hunter2-correct-horse"}).json()["access_token"]
_h = {"Authorization": "Bearer " + _tok}
_key = c.post("/create_api_key?scopes=data&days=30", headers=_h).json()["api_key"]
_kh = {"X-API-KEY": _key}

# a data-scoped key is required — a node/jobs key is refused (403)
_nkey = c.post("/create_api_key?scopes=node,jobs&days=30", headers=_h).json()["api_key"]
ok("a node/jobs key cannot use the data API (scope enforced)",
   c.get("/api/v1/data/usage", headers={"X-API-KEY": _nkey}).status_code == 403)

# populate price history so the history endpoint has something to serve
_s = dbm.SessionLocal(); _rows = dbm.record_price_snapshot(_s); _s.close()
ok("a price snapshot records one row per GPU model (history's raw material)", _rows > 0)

# free quota = 2 -> first two calls are free and not billed
r1 = c.get("/api/v1/data/gpu-prices", headers=_kh)
r2 = c.get("/api/v1/data/market", headers=_kh)
ok("calls within the free quota are served (200) and not billed",
   r1.status_code == 200 and r2.status_code == 200
   and r1.json()["usage"]["billed"] is False and r2.json()["usage"]["billed"] is False)
ok("the price index carries reference + live market data per GPU",
   any("reference_price" in g and "avg_price" in g for g in r1.json()["gpus"]))

# 3rd call is billable but the wallet is empty -> 402, and it is NOT counted/served
r3 = c.get("/api/v1/data/gpu-prices", headers=_kh)
ok("a billable call with no balance is REFUSED (402 quota exceeded), not given away",
   r3.status_code == 402 and _code(r3) == "DATA_API_QUOTA_EXCEEDED")

# fund the wallet, then billable calls succeed and each costs $1
_s = dbm.SessionLocal(); _u = dbm.get_user_by_username(_s, "dataco"); dbm.deposit(_s, _u, 5.0); _s.commit(); _s.close()
# both are commodity (weight 1) -> each costs the $1 base rate exactly
r4 = c.get("/api/v1/data/gpu-prices", headers=_kh)
ok("after funding, a billable call succeeds and is marked billed + charged $1.00 (weight 1)",
   r4.status_code == 200 and r4.json()["usage"]["billed"] is True
   and abs(r4.json()["usage"]["charged"] - 1.0) < 1e-9)
r5 = c.get("/api/v1/data/market", headers=_kh)
ok("market summary is served (billable, weight 1 -> $1)",
   r5.status_code == 200 and abs(r5.json()["usage"]["charged"] - 1.0) < 1e-9)

# /usage is free to check and does not itself count as a billed call
_u1 = c.get("/api/v1/data/usage", headers=_kh).json()
ok("/usage reports the month's calls/spend and is itself free (2 billed calls, $2 spent)",
   _u1["billed_calls"] == 2 and abs(_u1["amount_usd"] - 2.0) < 1e-9)

# the money really moved: wallet down $2, and it's booked to platform revenue
_s = dbm.SessionLocal()
_bal = float(dbm.get_user_by_username(_s, "dataco").balance)
from db import LedgerEntry, PLATFORM_REVENUE  # noqa: E402
_rev = sum(float(e.amount) for e in _s.query(LedgerEntry)
           .filter(LedgerEntry.entry_type == "data_api").all()
           if e.account == PLATFORM_REVENUE and e.direction == "credit")
_s.close()
ok("the wallet balance dropped by exactly the fees charged ($5 - $2 = $3)", abs(_bal - 3.0) < 1e-9)
ok("data-API fees are booked to PLATFORM_REVENUE (real revenue, double-entry)", abs(_rev - 2.0) < 1e-9)

# ---- more monetized datasets (all metered, aggregate/anonymized) ----
_s = dbm.SessionLocal(); _u = dbm.get_user_by_username(_s, "dataco"); dbm.deposit(_s, _u, 50.0); _s.commit(); _s.close()
# TIERED pricing: a premium dataset (benchmarks, weight 5) costs more than a commodity one
# (savings, weight 1) — proper monetization, not one flat rate.
_sv = c.get("/api/v1/data/savings", headers=_kh)
ok("savings index: per-GPU cheaper-than-cloud %, metered (weight 1 -> $1)",
   _sv.status_code == 200 and isinstance(_sv.json().get("gpus"), list)
   and abs(_sv.json()["usage"]["charged"] - 1.0) < 1e-9)
_hist = c.get("/api/v1/data/gpu-prices/history?days=1", headers=_kh)
ok("price history served (billable) and returns recorded points",
   _hist.status_code == 200 and _hist.json()["count"] > 0)
_av = c.get("/api/v1/data/availability", headers=_kh)
ok("availability index: live supply by GPU + region (aggregate counts, no identity)",
   _av.status_code == 200 and "live_nodes_total" in _av.json()
   and "by_gpu" in _av.json() and "by_region" in _av.json())
# seed a benchmark sample so the authenticity dataset has a row to serve
_s = dbm.SessionLocal()
_s.add(dbm.BenchmarkSample(spec_id=None, seller_id=None, gpu_model="RTX 4090", source="benchmark",
                           metrics='{"tflops_fp16": 320.0}', verdict="consistent",
                           pow_verified=True, reputation=100, jobs_completed=5, fraud_count=0))
_s.commit(); _s.close()
_bj = c.get("/api/v1/data/benchmarks?limit=10", headers=_kh).json()
ok("authenticity dataset: labelled feature rows + corpus stats, metered",
   _bj["count"] >= 1 and "stats" in _bj and any("label_verdict" in r for r in _bj["rows"]))
ok("TIERED pricing: the premium benchmarks dataset (weight 5) costs 5x the commodity rate",
   abs(_bj["usage"]["charged"] - 5.0) < 1e-9)
ok("the sold dataset is ANONYMIZED: no seller_id and no node/spec_id in any row",
   all("seller_id" not in r and "spec_id" not in r for r in _bj["rows"]))

# ---- buyer-side demand datasets (aggregate, real-only, no buyer identity) ----
_dm = c.get("/api/v1/data/demand", headers=_kh)
_dmj = _dm.json()
ok("demand index: totals + per-GPU bookings/GMV/realized-price, metered",
   _dm.status_code == 200 and "totals" in _dmj and "by_gpu" in _dmj
   and set(_dmj["totals"]) >= {"bookings", "gpu_hours", "gmv_usd"})
ok("demand rows carry no buyer identity (aggregate only)",
   all("buyer_id" not in r and "buyer" not in r for r in _dmj["by_gpu"]))
_wk = c.get("/api/v1/data/workloads", headers=_kh)
ok("workload-mix index: jobs by type + template, metered",
   _wk.status_code == 200 and "by_type" in _wk.json() and "by_template" in _wk.json()
   and "total_jobs" in _wk.json())

# seed a REAL paid, templated job so /templates has something to aggregate
_s = dbm.SessionLocal()
_du = dbm.get_user_by_username(_s, "dataco")
_sp = dbm.SellerSpec(user_id=_du.id, cpu=4, ram=16, price_per_hour=dbm.q(1),
                     duration=24, gpu_model="RTX 4090"); _s.add(_sp); _s.commit()
_bk = dbm.Booking(buyer_id=_du.id, seller_id=_du.id, spec_id=_sp.id, hours=2,
                  price_per_hour=dbm.q(1), gross_amount=dbm.q(2), platform_fee=dbm.q(0.2),
                  seller_payout=dbm.q(1.8), status="released", test=False, is_demo=False)
_s.add(_bk); _s.commit()
_s.add(dbm.Task(booking_id=_bk.id, spec_id=_sp.id, buyer_id=_du.id, task_type="template",
                template="vllm", template_params='{"model":"facebook/opt-125m"}',
                status="completed")); _s.commit(); _s.close()
_tp = c.get("/api/v1/data/templates", headers=_kh).json()
_vllm = next((r for r in _tp["templates"] if r["template"] == "vllm"), None)
ok("templates-bought index: per template jobs/buyers/GMV + top models, from real paid jobs",
   _vllm is not None and _vllm["jobs"] >= 1 and _vllm["unique_buyers"] >= 1
   and _vllm["gmv_usd"] >= 2.0
   and any(m["model"] == "facebook/opt-125m" for m in _vllm["top_models"]))
ok("templates dataset leaks no buyer identity (only counts)",
   all("buyer_id" not in r and "buyers" not in r for r in _tp["templates"]))

# ---- monetization is MEASURED: revenue scoreboard reflects the billed calls ----
_s = dbm.SessionLocal(); _rev_sb = dbm.data_api_revenue(_s); _s.close()
ok("revenue metric reflects real billed calls (all-time revenue > 0, paying account counted)",
   _rev_sb["revenue_usd_total"] > 0 and _rev_sb["billed_calls_total"] >= 3
   and _rev_sb["paying_accounts_month"] >= 1)

# ---- developer onboarding: try before you buy (sandbox key + keyless sample) ----
# The published SANDBOX key exercises the REAL endpoints, free & unmetered — no account, no wallet,
# never billed, and no data scope needed. Think Stripe's test key.
_sbh = {"X-API-KEY": main.DATA_API_SANDBOX_KEY}
_sb = c.get("/api/v1/data/gpu-prices", headers=_sbh)
ok("the sandbox key authenticates the real endpoint (200) and serves live data",
   _sb.status_code == 200 and isinstance(_sb.json().get("gpus"), list))
ok("a sandbox call is FREE & unmetered (sandbox flag set, never billed, $0 charged)",
   _sb.json()["usage"].get("sandbox") is True and _sb.json()["usage"]["billed"] is False
   and abs(_sb.json()["usage"].get("charged", 0.0)) < 1e-9)
# even a PREMIUM dataset (benchmarks, weight 5) is free under the sandbox key — no scope, no charge
_sbb = c.get("/api/v1/data/benchmarks?limit=3", headers=_sbh)
ok("the sandbox key reaches premium datasets free too (no data scope required)",
   _sbb.status_code == 200 and _sbb.json()["usage"].get("sandbox") is True
   and abs(_sbb.json()["usage"].get("charged", 0.0)) < 1e-9)
# and it never records usage / never moves money
_su = c.get("/api/v1/data/usage", headers=_sbh).json()
ok("sandbox /usage reports it is untracked (never billed)",
   _su.get("sandbox") is True and _su["billed_calls"] == 0 and abs(_su["amount_usd"]) < 1e-9)
_s = dbm.SessionLocal()
_sandbox_rows = _s.query(dbm.ApiUsage).filter(dbm.ApiUsage.user_id.is_(None)).count()
_s.close()
ok("sandbox calls create no ApiUsage rows and touch no wallet (nothing to bill)", _sandbox_rows == 0)

# the keyless /api/v1/data/sample returns example payloads for EVERY dataset — no key at all
_sample = c.get("/api/v1/data/sample")
_sj = _sample.json()
ok("/api/v1/data/sample is keyless (200 with no X-API-KEY) and flagged sandbox/example",
   _sample.status_code == 200 and _sj.get("sandbox") is True)
ok("the sample covers every published dataset so devs see each shape before paying",
   set(_sj.get("endpoints", {})) >=
   {"gpu-prices", "gpu-prices/history", "market", "savings", "availability",
    "benchmarks", "demand", "workloads", "templates"})
ok("the sample publishes the sandbox key so devs can go from dummy data to live data",
   main.DATA_API_SANDBOX_KEY in (_sj.get("note") or ""))

# a bogus (non-sandbox) key is still rejected — the sandbox path doesn't weaken real auth
ok("a random non-sandbox key is still rejected (401), sandbox is an exact match only",
   c.get("/api/v1/data/gpu-prices", headers={"X-API-KEY": "not-the-sandbox-key"}).status_code == 401)

# ---- the two key NAMESPACES cannot collide or cross over ----
# The sandbox key is honoured ONLY on the data API; it can never act as a seller/node/jobs key.
ok("the sandbox key is REFUSED on a seller/node endpoint (can't onboard a node or pull jobs)",
   c.get("/jobs/next", headers=_sbh).status_code == 401)
# Real minted keys are Fernet tokens; they can NEVER carry the sandbox prefix. Disjoint by design.
ok("the sandbox key carries its own namespace prefix (pk_sandbox_), unlike any real key",
   main.DATA_API_SANDBOX_KEY.startswith(main.DATA_API_SANDBOX_KEY_PREFIX))
ok("a real minted key (data / node) never looks like the sandbox key (no prefix collision)",
   not _key.startswith(main.DATA_API_SANDBOX_KEY_PREFIX)
   and not _nkey.startswith(main.DATA_API_SANDBOX_KEY_PREFIX)
   and _key != main.DATA_API_SANDBOX_KEY and _nkey != main.DATA_API_SANDBOX_KEY)
# Fail-closed config: a sandbox value WITHOUT the prefix is refused (a real key can't be aliased in).
from main import _SandboxCaller  # noqa: E402
import main as _mm  # noqa: E402
_saved = _mm.DATA_API_SANDBOX_KEY
_fcs = dbm.SessionLocal()
try:
    _mm.DATA_API_SANDBOX_KEY = _key            # pretend an operator pasted a REAL key here
    _res = _mm.data_api_caller(x_api_key=_key, db=_fcs)
    ok("even if a real key is mis-set as the sandbox key, it is NOT treated as sandbox (no prefix)",
       not isinstance(_res, _SandboxCaller))
finally:
    _mm.DATA_API_SANDBOX_KEY = _saved
    _fcs.close()

for f in ("data_api_test.db", "data_api_test.db-wal", "data_api_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== data_api: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
