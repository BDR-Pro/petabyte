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
r4 = c.get("/api/v1/data/gpu-prices", headers=_kh)
ok("after funding, a billable call succeeds and is marked billed + charged $1.00",
   r4.status_code == 200 and r4.json()["usage"]["billed"] is True
   and abs(r4.json()["usage"]["charged"] - 1.0) < 1e-9)
r5 = c.get("/api/v1/data/gpu-prices/history?days=1", headers=_kh)
ok("price history is served (billable) and returns recorded points",
   r5.status_code == 200 and r5.json()["count"] > 0)

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

for f in ("data_api_test.db", "data_api_test.db-wal", "data_api_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== data_api: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
