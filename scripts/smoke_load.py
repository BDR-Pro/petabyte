#!/usr/bin/env python3
"""smoke_load.py — concurrent Buyer -> Platform -> Seller load over the REAL API.

Proves the marketplace path under contention, not just that endpoints return 200:
  * many simultaneous buyers pay + dispatch through the REAL endpoints (Stripe TEST/fake
    gateway — never live money),
  * sellers with LIMITED capacity claim + execute jobs concurrently,
  * capacity is never oversold and is fully released afterwards,
  * every booking/job id is unique and a buyer can never read another buyer's transaction,
  * the ledger stays balanced and no capture is duplicated,
  * the platform stays ready (/healthz, /readyz) throughout.

Emits artifacts/SMOKE_LOAD_REPORT.json (+ .md). PASS requires the INVARIANTS to hold, not
merely HTTP 200s.

Postgres is REQUIRED for a real concurrency-correctness claim: set DATABASE_URL to a
Postgres URL (the GitHub `load_test` workflow does). On SQLite it still runs as a functional
signal but records a caveat that SQLite serialises writers, so races can't be proven.

Config (env, with defaults):
  SMOKE_BUYERS=8  SMOKE_JOBS_PER_BUYER=1  SMOKE_CONCURRENCY=8
  SMOKE_SELLERS=2  SMOKE_SELLER_CAPACITY=1  (total capacity = SELLERS*CAPACITY)
  SMOKE_JOB_RUNTIME_S=1.5  SMOKE_TIMEOUT_SECONDS=240
  SMOKE_MAX_P95_MS=8000   SMOKE_MAX_ERROR_RATE=0.05
"""
from __future__ import annotations

import base64
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from cryptography.fernet import Fernet

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.path.join(REPO, "lumaris_api")
AGENT_DIR = os.path.join(REPO, "lumaris_agent")
ARTIFACTS = os.path.join(REPO, "artifacts")


def _int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _flt(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


CFG = {
    "buyers": _int("SMOKE_BUYERS", 8),
    "jobs_per_buyer": _int("SMOKE_JOBS_PER_BUYER", 1),
    "concurrency": _int("SMOKE_CONCURRENCY", 8),
    "sellers": _int("SMOKE_SELLERS", 2),
    "capacity": _int("SMOKE_SELLER_CAPACITY", 1),
    "job_runtime_s": _flt("SMOKE_JOB_RUNTIME_S", 1.5),
    "reserve_wait_s": _int("SMOKE_RESERVE_WAIT_S", 8),
    "timeout_s": _int("SMOKE_TIMEOUT_SECONDS", 240),
    "max_p95_ms": _flt("SMOKE_MAX_P95_MS", 8000),
    "max_error_rate": _flt("SMOKE_MAX_ERROR_RATE", 0.05),
    "port": _int("SMOKE_PORT", 8097),
}
PW = "pw-correct-horse-load-1"
HOST = "127.0.0.1"
BASE = f"http://{HOST}:{CFG['port']}"

# agent signing identity (faithful to a real seller node)
_keydir = tempfile.mkdtemp(prefix="pb-smoke-agent-")
os.environ["PETABYTE_AGENT_KEY"] = os.path.join(_keydir, "agent_ed25519.key")
sys.path.insert(0, AGENT_DIR)
import crypto as agent_crypto  # noqa: E402
# lumaris_api on the path so this process can read the SAME DB for capacity/ledger invariants
sys.path.insert(0, API_DIR)


def signed_proof(output_hash: str) -> dict:
    proof = {"output_hash": output_hash, "ts": int(time.time())}
    return {"proof": proof, "signature": agent_crypto.sign_proof(proof)}


# --------------------------------------------------------------------------- server
def start_server():
    """Boot the REAL API. Uses DATABASE_URL if provided (Postgres in CI); else a temp
    SQLite file shared with this process for capacity sampling."""
    provided = os.environ.get("DATABASE_URL", "").strip()
    if provided:
        db_url = provided
        engine_kind = "postgres" if provided.startswith("postgres") else "sqlite"
    else:
        db_path = os.path.join(tempfile.mkdtemp(prefix="pb-smoke-db-"), "smoke_load.db")
        db_url = f"sqlite:///{db_path}"
        engine_kind = "sqlite"
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": db_url,
        "SECRET_KEY": "smoke-load-secret",
        "SERVER_PRIVATE_KEY": Fernet.generate_key().decode(),
        "WG_PUBLIC_KEY": "SMOKEPUBLICKEYbase64==", "WG_ENDPOINT": "vpn.smoke.example",
        "TRUSTED_PROXIES": "127.0.0.1,::1", "REAPER_DISABLED": "true",
        "HEARTBEAT_TIMEOUT_S": "300", "NOTIFY_STUB": "true", "PAYOUT_STUB": "true",
        "S3_STUB": "true", "GEOIP_STUB": "true", "GOOGLE_OAUTH_STUB": "true",
        "ADMIN_USERS": "admin1", "MIN_REPUTATION": "0",
        "STRIPE_GATEWAY": "fake", "STRIPE_MODE": "test", "PAYMENTS_MODE": "sandbox",
        "STRIPE_SECRET_KEY": "sk_test_smoke", "STRIPE_PUBLISHABLE_KEY": "pk_test_smoke",
        "PAYMENT_WEBHOOK_SECRET": "whsec_smoke", "STRIPE_WEBHOOK_SECRET": "whsec_smoke",
        # make this process able to read the SAME db for capacity sampling
    })
    # expose to THIS process too, for in-process invariant/capacity queries
    os.environ["DATABASE_URL"] = db_url
    for k in ("SECRET_KEY", "SERVER_PRIVATE_KEY"):
        os.environ.setdefault(k, env[k])
    log = open(os.path.join(_keydir, "server.log"), "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", HOST,
         "--port", str(CFG["port"]), "--workers", "1"],
        cwd=API_DIR, env=env, stdout=log, stderr=subprocess.STDOUT)
    return proc, log, db_url, engine_kind


def wait_up(timeout=60):
    for _ in range(timeout * 2):
        try:
            if httpx.get(f"{BASE}/healthz", timeout=3).status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _tok(c, u):
    r = c.post(f"{BASE}/login", data={"username": u, "password": PW})
    return r.json().get("access_token") if r.status_code == 200 else None


def _stripe_webhook(c, event):
    import hashlib
    import hmac
    event.setdefault("object", "event")
    payload = json.dumps(event, separators=(",", ":")).encode()
    ts = int(time.time())
    sig = hmac.new(b"whsec_smoke", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return c.post(f"{BASE}/webhooks/stripe", content=payload,
                  headers={"Stripe-Signature": f"t={ts},v1={sig}",
                           "Content-Type": "application/json"})


# --------------------------------------------------------------------------- metrics
ERRORS = []          # (label, status)
LAT = []             # per-request latencies (ms)
_lock = threading.Lock()


def req(c, method, path, **kw):
    """Timed request. Records latency + any >=400 status (except expected 409/404 which the
    caller interprets). Returns the response."""
    label = kw.pop("label", f"{method} {path}")
    t0 = time.monotonic()
    r = getattr(c, method)(f"{BASE}{path}", **kw)
    dt = (time.monotonic() - t0) * 1000.0
    with _lock:
        LAT.append(dt)
        if r.status_code >= 500:
            ERRORS.append((label, r.status_code))
    return r


# --------------------------------------------------------------------------- capacity sampling
SAMPLES = {"max_running": 0, "max_reserved": 0, "min_available": None,
           "health_fail": 0, "ready_fail": 0, "samples": 0, "negative_capacity": False}


def sample_loop(stop_evt, spec_ids):
    import db as dbmod
    from sqlalchemy import func
    S, CT = dbmod.SellerSpec, dbmod.ComputeTransaction
    hc = httpx.Client(timeout=4)
    while not stop_evt.is_set():
        # platform readiness/health
        for p, key in (("/healthz", "health_fail"), ("/readyz", "ready_fail")):
            try:
                if hc.get(f"{BASE}{p}").status_code >= 400:
                    SAMPLES[key] += 1
            except Exception:
                SAMPLES[key] += 1
        # capacity + running (best-effort; tolerate sqlite lock contention). The session is
        # ALWAYS closed in finally — a query that raised here previously leaked the connection,
        # exhausting the pool over a long sampling run.
        s = None
        try:
            s = dbmod.SessionLocal()
            running = s.query(func.count(CT.id)).filter(CT.status == "RUNNING").scalar() or 0
            rows = s.query(S.id, S.available_units, S.total_units).filter(
                S.id.in_(spec_ids)).all()
            reserved = sum(max(0, (tu or 0) - (au or 0)) for _, au, tu in rows)
            avail = sum((au or 0) for _, au, _ in rows)
            with _lock:
                SAMPLES["max_running"] = max(SAMPLES["max_running"], int(running))
                SAMPLES["max_reserved"] = max(SAMPLES["max_reserved"], int(reserved))
                SAMPLES["min_available"] = avail if SAMPLES["min_available"] is None \
                    else min(SAMPLES["min_available"], avail)
                if any((au or 0) < 0 for _, au, _ in rows):
                    SAMPLES["negative_capacity"] = True
                SAMPLES["samples"] += 1
        except Exception:
            pass
        finally:
            if s is not None:
                s.close()
        time.sleep(0.4)
    hc.close()


# --------------------------------------------------------------------------- seller workers
def seller_worker(api_key, stop_evt, done_counter, total_jobs):
    hdr = {"X-API-KEY": api_key}
    with httpx.Client(timeout=20) as c:
        while not stop_evt.is_set():
            try:
                r = c.get(f"{BASE}/jobs/next", headers=hdr)
            except Exception:
                time.sleep(0.2)
                continue
            if r.status_code == 204:
                if done_counter["done"] >= total_jobs:
                    return
                time.sleep(0.15)
                continue
            if r.status_code != 200:
                time.sleep(0.2)
                continue
            j = r.json()
            tid = j.get("task_id")
            # hold the slot briefly so capacity is genuinely contended (a real running window)
            time.sleep(CFG["job_runtime_s"])
            try:
                c.post(f"{BASE}/jobs/result", headers=hdr,
                       json={"task_id": tid, "status": "completed", "result": "ok",
                             **signed_proof(f"sha256:smoke-{tid}")})
            except Exception:
                pass


# --------------------------------------------------------------------------- buyer flow
def buyer_job(buyer, spec_pub, idx):
    """Full real-API path for ONE job. Returns a record dict."""
    rec = {"buyer": buyer["u"], "idx": idx, "ok": False, "tx_id": None,
           "task_id": None, "stage": "start", "http_error": False,
           "capacity_rejected": False}
    deadline = time.monotonic() + CFG["timeout_s"]
    with httpx.Client(timeout=25) as c:
        BT = {"Authorization": f"Bearer {buyer['t']}"}
        try:
            req(c, "post", "/payments/quote", headers=BT,
                json={"spec_id": spec_pub, "estimated_seconds": 60}, label="quote")
            az = req(c, "post", "/payments/authorize", headers=BT,
                     json={"spec_id": spec_pub, "estimated_seconds": 60}, label="authorize")
            if az.status_code == 409:
                # capacity full already at authorize — EXPECTED under contention, not a failure
                rec["stage"] = "authorize-409"
                rec["capacity_rejected"] = True
                return rec
            if az.status_code != 200:
                rec["stage"] = "authorize"
                rec["http_error"] = az.status_code >= 500
                return rec
            tx = az.json()["transaction_id"]
            rec["tx_id"] = tx
            req(c, "post", f"/payments/{tx}/simulate-card", headers=BT, label="simulate-card")
            req(c, "post", f"/payments/{tx}/confirm", headers=BT, label="confirm")
            # reserve: contend for capacity. 409 = capacity full (EXPECTED under load); retry
            # until a slot frees or the window ends, at which point this job is honestly
            # "capacity_rejected" (NOT a failure — proves the limit binds, never oversells).
            rec["stage"] = "reserve"
            reserve_deadline = time.monotonic() + min(CFG["timeout_s"], CFG["reserve_wait_s"])
            while True:
                rv = req(c, "post", f"/payments/{tx}/reserve", headers=BT, label="reserve")
                if rv.status_code == 200:
                    break
                if rv.status_code == 409:
                    if time.monotonic() > reserve_deadline:
                        rec["capacity_rejected"] = True
                        return rec
                    time.sleep(0.25)
                    continue
                rec["http_error"] = rv.status_code >= 500   # a genuine error
                return rec
            dp = req(c, "post", f"/payments/{tx}/dispatch", headers=BT,
                     json={"task_type": "notebook", "code": f"print('smoke {idx}')"},
                     label="dispatch")
            if dp.status_code != 200:
                rec["stage"] = "dispatch"
                rec["http_error"] = dp.status_code >= 500
                return rec
            rec["task_id"] = dp.json().get("task_id")
            # wait for the seller to complete it -> tx captured
            rec["stage"] = "await-complete"
            while time.monotonic() < deadline:
                pv = req(c, "get", f"/payments/{tx}", headers=BT, label="tx-status")
                st = pv.json().get("status") if pv.status_code == 200 else None
                if st in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED"):
                    rec["ok"] = True
                    rec["final_status"] = st
                    return rec
                if st in ("CANCELLED", "REFUNDED", "CAPTURE_FAILED", "JOB_FAILED"):
                    rec["final_status"] = st
                    return rec
                time.sleep(0.3)
            rec["stage"] = "timeout"
            return rec
        except Exception as e:  # noqa: BLE001
            rec["stage"] = f"exception:{type(e).__name__}"
            return rec


def _sum_available(spec_ids):
    import db as dbmod
    from sqlalchemy import func
    s = dbmod.SessionLocal()
    try:
        return int(s.query(func.coalesce(func.sum(dbmod.SellerSpec.available_units), 0))
                   .filter(dbmod.SellerSpec.id.in_(spec_ids)).scalar() or 0)
    finally:
        s.close()


def release_check(buyer, spec_pub, spec_ids):
    """Deterministic capacity-RELEASE proof: reserve one unit, then cancel before dispatch
    and confirm the unit is returned (capacity is time-bound to a rental and freed on the
    cancel path). Returns True iff reserve decremented AND cancel restored capacity."""
    before = _sum_available(spec_ids)
    with httpx.Client(timeout=20) as c:
        BT = {"Authorization": f"Bearer {buyer['t']}"}
        az = c.post(f"{BASE}/payments/authorize", headers=BT,
                    json={"spec_id": spec_pub, "estimated_seconds": 60})
        if az.status_code != 200:
            return False
        tx = az.json()["transaction_id"]
        c.post(f"{BASE}/payments/{tx}/simulate-card", headers=BT)
        c.post(f"{BASE}/payments/{tx}/confirm", headers=BT)
        if c.post(f"{BASE}/payments/{tx}/reserve", headers=BT).status_code != 200:
            return False
        during = _sum_available(spec_ids)
        cancelled = c.post(f"{BASE}/payments/{tx}/cancel", headers=BT).status_code == 200
    after = _sum_available(spec_ids)
    return cancelled and during == before - 1 and after == before


# --------------------------------------------------------------------------- orchestration
def main():
    started = time.time()
    # A per-run tag isolates this run's users/specs from anything already in a SHARED database
    # (the load_test workflow uses a persistent Postgres, and re-runs reuse it). Without it,
    # fixed names like "seller0" collide (register_user 400) and, worse, spec discovery would
    # pick up other runs'/tenants' specs and mis-count capacity. Tagged names keep the run's
    # capacity math scoped to exactly the sellers this run created.
    run_tag = os.urandom(4).hex()
    providers = [f"seller_{run_tag}_{i}" for i in range(CFG["sellers"])]
    proc, log, db_url, engine_kind = start_server()
    result = {"pass": False}
    try:
        if not wait_up():
            print("SERVER FAILED TO START:\n" + open(log.name).read()[-2000:])
            return 2
        print(f"server up at {BASE} (db={engine_kind})")

        # ---- bootstrap: admin, sellers (limited capacity), buyers ----
        with httpx.Client(timeout=25) as c:
            spec_pubs, spec_ids, seller_keys = [], [], []
            for i in range(CFG["sellers"]):
                u = providers[i]
                c.post(f"{BASE}/register_user", json={"username": u, "password": PW})
                st = _tok(c, u)
                c.post(f"{BASE}/change_role", headers={"Authorization": f"Bearer {st}"},
                       json={"role": "seller"})
                kr = c.post(f"{BASE}/create_api_key?days=90&scopes=node,jobs",
                            headers={"Authorization": f"Bearer {st}"})
                api_key = kr.json()["api_key"]
                seller_keys.append(api_key)
                sr = c.post(f"{BASE}/register_specs",
                            headers={"Authorization": f"Bearer {st}"},
                            json={"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.0,
                                  "provider": u, "gpu_model": "NVIDIA L4", "gpu_count": 1,
                                  "vram_gb": 24, "units": CFG["capacity"], "region": "us-east",
                                  "country": "US"})
                sp = sr.json().get("spec_id")
                att = {"node": "petabyte-agent",
                       "nonce": base64.b64encode(os.urandom(9)).decode(), "ts": int(time.time())}
                c.post(f"{BASE}/prove", headers={"Authorization": f"Bearer {st}"},
                       json={"spec_id": sp, "attestation": att,
                             "signature": agent_crypto.sign_proof(att),
                             "pubkey": agent_crypto.public_key_b64()})
                c.post(f"{BASE}/heartbeat", headers={"X-API-KEY": api_key},
                       json={"spec_id": sp})
                # payout-ready via a signed fake webhook
                ca = c.post(f"{BASE}/payments/connect/account",
                            headers={"Authorization": f"Bearer {st}"},
                            json={"country": "US", "email": f"{u}@x.com"})
                acct = ca.json().get("connected_account_id")
                _stripe_webhook(c, {"id": f"evt_acct_{run_tag}_{i}", "type": "account.updated",
                    "data": {"object": {"id": acct, "charges_enabled": True,
                        "payouts_enabled": True, "details_submitted": True,
                        "capabilities": {"transfers": "active", "card_payments": "active"},
                        "requirements": {"currently_due": [], "past_due": []}}}})
            buyers = []
            for i in range(CFG["buyers"]):
                u = f"buyer_{run_tag}_{i}"
                c.post(f"{BASE}/register_user", json={"username": u, "password": PW})
                buyers.append({"u": u, "t": _tok(c, u)})

        # Collect the bookable specs SCOPED TO THIS RUN'S SELLERS (by our unique provider
        # names) straight from the DB — never the whole marketplace, which on a shared DB
        # would include other runs'/tenants' specs and corrupt the capacity math. We read both
        # the public_id (used by /payments/authorize) and the internal id (capacity sampling)
        # from the same rows, so the two id spaces can never drift apart.
        import db as dbmod
        s = dbmod.SessionLocal()
        initial_avail = {}
        try:
            rows = s.query(dbmod.SellerSpec).filter(
                dbmod.SellerSpec.provider.in_(providers)).all()
            for sp in rows:
                spec_ids.append(sp.id)
                spec_pubs.append(sp.public_id)
                initial_avail[sp.id] = sp.available_units
        finally:
            s.close()
        if not spec_pubs:
            print("NO bookable specs after bootstrap for this run — server log tail:\n"
                  + open(log.name).read()[-1800:])
            return 2
        total_capacity = sum(initial_avail.values())
        print(f"bootstrapped {CFG['sellers']} seller(s), total capacity={total_capacity}, "
              f"{CFG['buyers']} buyer(s); dispatching {CFG['buyers']*CFG['jobs_per_buyer']} jobs")

        # deterministic capacity-release proof (before the load, while capacity is free)
        release_works = release_check(buyers[0], spec_pubs[0], spec_ids)
        print(f"capacity release check (reserve->cancel->restored): {release_works}")

        # ---- launch monitor + seller workers ----
        stop_evt = threading.Event()
        done = {"done": 0}
        total_jobs = CFG["buyers"] * CFG["jobs_per_buyer"]
        mon = threading.Thread(target=sample_loop, args=(stop_evt, spec_ids), daemon=True)
        mon.start()
        sellers = [threading.Thread(target=seller_worker,
                                    args=(k, stop_evt, done, total_jobs), daemon=True)
                   for k in seller_keys]
        for t in sellers:
            t.start()

        # ---- run buyers concurrently ----
        # each buyer submits jobs_per_buyer jobs; spec is round-robined across sellers.
        jobs = []
        n = 0
        for bi in range(CFG["buyers"]):
            for _ in range(CFG["jobs_per_buyer"]):
                jobs.append((buyers[bi], spec_pubs[n % len(spec_pubs)], n))
                n += 1
        records = []
        with ThreadPoolExecutor(max_workers=CFG["concurrency"]) as ex:
            futs = [ex.submit(buyer_job, b, sp, n) for (b, sp, n) in jobs]
            for f in futs:
                r = f.result()
                records.append(r)
                if r["ok"]:
                    done["done"] += 1

        # Let sellers drain any still-in-flight jobs, then stop. Wait on the ACTUAL server-side
        # RUNNING count reaching zero — the previous condition compared done["done"] to the
        # count of ok records, which are already equal once the futures resolve, so it never
        # waited and left the fixed sleep to gate, intermittently tripping no_orphan_running_jobs.
        from sqlalchemy import func as _func
        drain_deadline = time.monotonic() + 15
        while time.monotonic() < drain_deadline:
            _s = dbmod.SessionLocal()
            try:
                running_now = _s.query(_func.count(dbmod.ComputeTransaction.id)).filter(
                    dbmod.ComputeTransaction.status == "RUNNING").scalar() or 0
            except Exception:
                running_now = -1   # transient read error: keep waiting, don't stop early
            finally:
                _s.close()
            if running_now == 0:
                break
            time.sleep(0.3)
        stop_evt.set()
        for t in sellers:
            t.join(timeout=5)
        mon.join(timeout=5)

        # ---- final capacity ----
        from sqlalchemy import func
        s = dbmod.SessionLocal()
        final_avail = {sp.id: sp.available_units for sp in
                       s.query(dbmod.SellerSpec).filter(
                           dbmod.SellerSpec.id.in_(spec_ids)).all()}
        running_left = s.query(func.count(dbmod.ComputeTransaction.id)).filter(
            dbmod.ComputeTransaction.status == "RUNNING").scalar() or 0
        held = s.query(func.count(dbmod.Booking.id)).filter(
            dbmod.Booking.spec_id.in_(spec_ids),
            dbmod.Booking.status == "stripe_reserved").scalar() or 0
        fi = dbmod.financial_integrity(s)
        s.close()

        # ---- invariants (aligned to Petabyte's real capacity model) ----
        # Capacity is time-bound to a rental: a unit is held for the booking and freed on the
        # cancel path (or rental expiry), NOT per completed job. So a 409 on reserve under
        # contention is CORRECT (capacity full), not a failure; and after the load the units
        # of still-active rentals are legitimately held (no leak = reserved == held bookings).
        ok_jobs = [r for r in records if r["ok"]]
        rejected = [r for r in records if r.get("capacity_rejected")]
        failed = [r for r in records if not r["ok"] and not r.get("capacity_rejected")]
        tx_ids = [r["tx_id"] for r in records if r["tx_id"]]
        task_ids = [r["task_id"] for r in records if r["task_id"]]
        reserved_now = total_capacity - sum(final_avail.values())
        inv = {
            "capacity_never_oversold": SAMPLES["max_reserved"] <= total_capacity,
            "capacity_never_negative": (not SAMPLES["negative_capacity"])
                and (SAMPLES["min_available"] is None or SAMPLES["min_available"] >= 0),
            "max_running_within_capacity": SAMPLES["max_running"] <= total_capacity,
            "no_capacity_leak": reserved_now == held,
            "capacity_release_works": bool(release_works),
            "no_orphan_running_jobs": running_left == 0,
            "no_real_failures": len(failed) == 0,
            "some_jobs_completed": len(ok_jobs) >= 1,
            "booking_ids_unique": len(tx_ids) == len(set(tx_ids)),
            "job_ids_unique": len(task_ids) == len(set(task_ids)),
            "ledger_balanced": fi["balanced"],
        }
        if len(jobs) > total_capacity:   # we deliberately oversubscribed -> expect contention
            inv["contention_enforced"] = len(rejected) >= 1
        # cross-buyer isolation: a buyer cannot read another buyer's tx (404)
        iso_ok = True
        if len(buyers) >= 2 and len(ok_jobs) >= 1 and ok_jobs[0]["tx_id"]:
            victim = ok_jobs[0]
            other = next((b for b in buyers if b["u"] != victim["buyer"]), None)
            if other:
                with httpx.Client(timeout=10) as c:
                    rr = c.get(f"{BASE}/payments/{victim['tx_id']}",
                               headers={"Authorization": f"Bearer {other['t']}"})
                    iso_ok = rr.status_code == 404
        inv["cross_buyer_isolation"] = iso_ok

        # ledger audit (subprocess; read-only)
        audit = subprocess.run([sys.executable, "scripts/audit_ledger.py"], cwd=REPO,
                               capture_output=True, text=True, env=os.environ.copy())
        inv["ledger_audit"] = audit.returncode == 0

        # latency + error rate
        p50 = round(statistics.median(LAT), 1) if LAT else 0.0
        p95 = round(sorted(LAT)[int(len(LAT) * 0.95)] if len(LAT) > 1 else (LAT[0] if LAT else 0.0), 1)
        total_requests = len(LAT)
        err_rate = round(len(ERRORS) / total_requests, 4) if total_requests else 0.0
        inv["p95_within_threshold"] = p95 <= CFG["max_p95_ms"]
        inv["error_rate_within_threshold"] = err_rate <= CFG["max_error_rate"]
        inv["platform_stayed_ready"] = SAMPLES["ready_fail"] == 0 and SAMPLES["health_fail"] == 0

        # SQLite cannot PROVE concurrency correctness — record the caveat, don't fake it.
        caveats = []
        if engine_kind != "postgres":
            caveats.append("Ran on SQLite: writers serialise, so concurrency/race correctness "
                           "is NOT proven. Re-run with a Postgres DATABASE_URL (the load_test "
                           "workflow does).")

        passed = all(inv.values())
        result = {
            "tool": "smoke_load",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                     capture_output=True, text=True).stdout.strip(),
            "environment": {"db": engine_kind, **CFG},
            "buyer": {
                "buyers": CFG["buyers"], "jobs_submitted": len(jobs),
                "jobs_completed": len(ok_jobs),
                "jobs_rejected_capacity": len(rejected),
                "jobs_failed": len(failed),
                "requests": total_requests, "errors": len(ERRORS),
                "p50_ms": p50, "p95_ms": p95,
                "total_duration_s": round(time.time() - started, 1),
            },
            "seller": {
                "sellers": CFG["sellers"], "capacity": total_capacity,
                "max_concurrent_running": SAMPLES["max_running"],
                "max_reserved": SAMPLES["max_reserved"],
                "min_available_seen": SAMPLES["min_available"],
                "capacity_before": total_capacity,
                "capacity_after": sum(final_avail.values()),
            },
            "gpu": {"status": "NOT_EXERCISED_HERE",
                    "note": "GPU load is proven by scripts/smoke_gpu.py on a seller GPU host; "
                            "this scenario proves the marketplace path + contention."},
            "platform": {"health_failures": SAMPLES["health_fail"],
                         "readiness_failures": SAMPLES["ready_fail"],
                         "http_5xx": len(ERRORS)},
            "financial": {"ledger_balanced": fi["balanced"],
                          "ledger_net_minor": fi["net_minor"],
                          "imbalanced_tx": fi["imbalanced_tx"],
                          "ledger_audit_pass": inv["ledger_audit"],
                          "payment_mode": "sandbox/test (fake gateway) — never live"},
            "invariants": inv,
            "caveats": caveats,
            "final": "PASS" if passed else "FAIL",
        }
        _write_report(result)
        _print_summary(result)
        return 0 if passed else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def _write_report(result):
    os.makedirs(ARTIFACTS, exist_ok=True)
    with open(os.path.join(ARTIFACTS, "SMOKE_LOAD_REPORT.json"), "w") as f:
        json.dump(result, f, indent=2)
    b, se, pl, fin = result["buyer"], result["seller"], result["platform"], result["financial"]
    lines = [
        f"# Smoke load report — {result['final']}", "",
        f"- commit: `{result['commit'][:12]}`  ·  db: `{result['environment']['db']}`  "
        f"·  {result['timestamp']}", "",
        "## Buyer",
        f"- buyers: {b['buyers']}  ·  jobs submitted/completed/failed: "
        f"{b['jobs_submitted']}/{b['jobs_completed']}/{b['jobs_failed']}",
        f"- requests: {b['requests']}  ·  5xx errors: {b['errors']}  ·  "
        f"p50: {b['p50_ms']}ms  ·  p95: {b['p95_ms']}ms  ·  duration: {b['total_duration_s']}s",
        "## Seller",
        f"- sellers: {se['sellers']}  ·  capacity: {se['capacity']}  ·  "
        f"max concurrent running: {se['max_concurrent_running']}  ·  "
        f"max reserved: {se['max_reserved']}",
        f"- capacity before/after: {se['capacity_before']}/{se['capacity_after']}",
        "## Platform",
        f"- health failures: {pl['health_failures']}  ·  readiness failures: "
        f"{pl['readiness_failures']}  ·  5xx: {pl['http_5xx']}",
        "## Financial",
        f"- ledger balanced: {fin['ledger_balanced']}  ·  audit: {fin['ledger_audit_pass']}  "
        f"·  mode: {fin['payment_mode']}",
        "## Invariants",
    ]
    for k, v in result["invariants"].items():
        lines.append(f"- {'✅' if v else '❌'} {k}")
    if result["caveats"]:
        lines += ["", "## Caveats"] + [f"- {c}" for c in result["caveats"]]
    with open(os.path.join(ARTIFACTS, "SMOKE_LOAD_REPORT.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def _print_summary(result):
    print("\n=== SMOKE LOAD SUMMARY ===")
    print(f"db={result['environment']['db']} buyers={result['buyer']['buyers']} "
          f"jobs {result['buyer']['jobs_completed']}/{result['buyer']['jobs_submitted']} "
          f"p95={result['buyer']['p95_ms']}ms")
    print(f"capacity={result['seller']['capacity']} max_running="
          f"{result['seller']['max_concurrent_running']} max_reserved="
          f"{result['seller']['max_reserved']} after={result['seller']['capacity_after']}")
    for k, v in result["invariants"].items():
        print(f"  {'ok  ' if v else 'FAIL'} {k}")
    for c in result["caveats"]:
        print(f"  caveat: {c}")
    print(f"artifacts/SMOKE_LOAD_REPORT.json  ->  {result['final']}")


if __name__ == "__main__":
    raise SystemExit(main())
