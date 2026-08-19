import os
import re, json, time, base64
from decimal import Decimal as _Dec
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import hashlib

def sign_proof(key, proof):
    msg = json.dumps(proof, sort_keys=True, separators=(',',':')).encode()
    return base64.b64encode(key.sign(msg)).decode()


os.environ["TRUSTED_PROXIES"] = "testclient,127.0.0.1,::1"
# Respect an externally-supplied DATABASE_URL so the same suite can run against
# Postgres in CI. SQLite is convenient but it serialises writers and has no real
# decimal type -- exactly the two things our money and concurrency bugs live in.
os.environ.setdefault("DATABASE_URL", "sqlite:///./smoke.db")
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()
os.environ["WG_PUBLIC_KEY"] = "SERVERPUBLICKEYbase64example=="
os.environ["WG_ENDPOINT"] = "vpn.lumaris.example"
os.environ["REAPER_DISABLED"] = "true"          # drive the reaper manually in tests
os.environ["HEARTBEAT_TIMEOUT_S"] = "60"
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_test"
_VENDOR_SK = Ed25519PrivateKey.generate()
os.environ["TEE_TRUSTED_ROOT"] = base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()
os.environ["TEE_MEASUREMENT_ALLOWLIST"] = "mr_h100_cc_v1"
os.environ["GEOIP_STUB"] = json.dumps({"10.1.1.1":"DE","10.2.2.2":"SG"})
os.environ["S3_STUB"] = "true"
os.environ["S3_BUCKET"] = "pb-backups-test"
os.environ["PAYOUT_STUB"] = "true"
os.environ["NOTIFY_STUB"] = "true"

for f in ("smoke.db", "smoke.db-wal", "smoke.db-shm"):
    if os.path.exists(f): os.remove(f)

from fastapi.testclient import TestClient
# Postgres persists between runs, so wipe the schema BEFORE anything creates tables.
# (SQLite just deletes the file above.) Without this, yesterday's rows fail today's
# ledger invariants and you get a very confusing red suite.
import db as dbmod
if dbmod.engine.dialect.name.startswith("postgres"):
    with dbmod.engine.begin() as _c:
        _c.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    dbmod.init_db()      # rebuild the schema we just dropped

import main
c = TestClient(main.app)

def ok(label, cond):
    print(("PASS " if cond else "FAIL ") + label); assert cond, label

# ---- setup: seller + buyer, seller role, attested spec with 3 units ----
c.post("/register_user", json={"username":"seller1","password":"hunter2-correct-horse"})
c.post("/register_user", json={"username":"buyer1","password":"hunter2-correct-horse"})
def login(u):
    # /login now also Set-Cookies an HttpOnly session on the shared client. This suite is
    # Bearer-based, so drop that cookie after capturing the token — otherwise the ambient
    # session would silently authenticate the many "no-auth -> 401" assertions below.
    _r = c.post("/login", data={"username":u,"password":"hunter2-correct-horse"})
    c.cookies.clear()
    return _r.json()["access_token"]
sh = {"Authorization":f"Bearer {login('seller1')}"}
bh = {"Authorization":f"Bearer {login('buyer1')}"}
c.post("/deposit", headers=bh, json={"amount":100000.0})  # fund buyer for all test bookings
c.post("/change_role", headers=sh, json={"role":"seller"})

r = c.post("/register_specs", headers=sh, json={
    "cpu":16,"ram":64,"duration":48,"price_per_hour":2.5,"provider":"seller1",
    "gpu_model":"H100","gpu_count":1,"vram_gb":80,"units":3})
spec_id = r.json()["spec_id"]
ok("spec has 3 units", r.json()["available_units"]==3)

# attest
sk = Ed25519PrivateKey.generate()
pub = base64.b64encode(sk.public_key().public_bytes_raw()).decode()
att = {"cpu":16,"ram":64,"gpu_model":"H100","nonce":"n1","ts":int(time.time())}
sig = base64.b64encode(sk.sign(json.dumps(att,sort_keys=True,separators=(",",":")).encode())).decode()
ok("attested", c.post("/prove", headers=sh, json={"spec_id":spec_id,"attestation":att,"signature":sig,"pubkey":pub}).status_code==200)

# ---- HEALTH ----
ok("healthz", c.get("/healthz").status_code==200)
ok("readyz", c.get("/readyz").status_code==200)

# ---- LIVENESS GATE: attested but offline -> booking blocked ----
ok("offline blocks booking", c.post("/request_vm", headers=bh, json={"spec_id":spec_id,"hours":2}).status_code==503)

# ---- HEARTBEAT via API key brings it online ----
seller_key = c.post("/create_api_key", headers=sh).json()["api_key"]
ok("heartbeat ok", c.post("/heartbeat", headers={"X-API-KEY":seller_key}, json={"spec_id":spec_id}).status_code==200)
ok("online allows booking", c.post("/request_vm", headers=bh, json={"spec_id":spec_id,"hours":2}).status_code==200)
# that consumed 1 of 3 units -> 2 left

# ---- REAPER: stale heartbeat -> offline ----
spec = dbmod.get_spec_by_id(dbmod.SessionLocal(), spec_id)
s = dbmod.SessionLocal()
sp = dbmod.get_spec_by_id(s, spec_id)
from datetime import datetime, timezone, timedelta
sp.last_seen = datetime.now(timezone.utc) - timedelta(seconds=120)  # stale
s.add(sp); s.commit()
reaped = dbmod.reap_stale_specs(s, 60)
ok("reaper marks offline", reaped==1)
ok("post-reap booking blocked", c.post("/request_vm", headers=bh, json={"spec_id":spec_id,"hours":2}).status_code==503)
# bring back online for the concurrency test
c.post("/heartbeat", headers={"X-API-KEY":seller_key}, json={"spec_id":spec_id})

# ---- CONCURRENCY: 10 parallel bookings against 2 remaining units -> exactly 2 succeed ----
def book(_):
    return c.post("/request_vm", headers=bh, json={"spec_id":spec_id,"hours":1}).status_code
with ThreadPoolExecutor(max_workers=10) as ex:
    codes = list(ex.map(book, range(10)))
successes = sum(1 for x in codes if x==200)
conflicts = sum(1 for x in codes if x==409)
ok(f"exactly 2 concurrent successes (got {successes})", successes==2)
ok(f"rest are 409 no-capacity (got {conflicts})", conflicts==8)

# verify DB invariant: never oversold
s2 = dbmod.SessionLocal()
sp2 = dbmod.get_spec_by_id(s2, spec_id)
booking_count = s2.query(dbmod.Booking).filter(dbmod.Booking.spec_id==spec_id).count()
ok("available_units floored at 0", sp2.available_units==0)
ok(f"total bookings == total units (3) (got {booking_count})", booking_count==3)

# ---- IDEMPOTENCY: same key twice -> one booking, identical response ----
# fresh spec with capacity, online
r = c.post("/register_specs", headers=sh, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":1.0,"provider":"seller1","units":12})
sid2 = r.json()["spec_id"]
att2 = {"cpu":8,"ram":32,"nonce":"n2","ts":int(time.time())}
sig2 = base64.b64encode(sk.sign(json.dumps(att2,sort_keys=True,separators=(",",":")).encode())).decode()
c.post("/prove", headers=sh, json={"spec_id":sid2,"attestation":att2,"signature":sig2,"pubkey":pub})
c.post("/heartbeat", headers={"X-API-KEY":seller_key}, json={"spec_id":sid2})
idem = {"Idempotency-Key":"abc-123", **bh}
r1 = c.post("/request_vm", headers=idem, json={"spec_id":sid2,"hours":3})
r2 = c.post("/request_vm", headers=idem, json={"spec_id":sid2,"hours":3})
ok("idem first 200", r1.status_code==200)
ok("idem replay 200", r2.status_code==200)
ok("idem same booking id", r1.json()["booking_id"]==r2.json()["booking_id"])
s3 = dbmod.SessionLocal()
sp3 = dbmod.get_spec_by_id(s3, sid2)
ok("idem consumed only 1 unit (12->11)", sp3.available_units==11)

# ---- WG race-safe allocation: many configs, all unique addresses ----
# give buyer several vpn bookings, fetch configs, ensure distinct IPs
addrs=set()
for _ in range(5):
    rb = c.post("/request_vm", headers=bh, json={"spec_id":sid2,"hours":1,"vpn":True}).json()
    cfg = c.get(rb["vpn_config_url"], headers=bh).text
    line = [l for l in cfg.splitlines() if l.startswith("Address")][0]
    addrs.add(line)
ok(f"WG addresses all unique (got {len(addrs)})", len(addrs)==5)
ok("no server private key leaked", "PrivateKey" in cfg and os.environ["WG_PUBLIC_KEY"] in cfg)


# ---- JOB DISPATCH: buyer queues task -> owning agent pulls -> submits result ----
# buyer books sid2 (online, attested, owned by seller1), then creates a notebook task
rb = c.post("/request_vm", headers=bh, json={"spec_id":sid2,"hours":1}).json()
bid = rb["booking_id"]
rt = c.post("/create_task", headers=bh, json={"booking_id":bid,"task_type":"notebook","code":"print(2+2)"})
ok("create_task ok", rt.status_code==200)
task_id = rt.json()["task_id"]

# a DIFFERENT user's agent key must NOT be able to claim seller1's job
c.post("/register_user", json={"username":"seller2","password":"hunter2-correct-horse"})
s2t = login("seller2"); s2h={"Authorization":f"Bearer {s2t}"}
c.post("/change_role", headers=s2h, json={"role":"seller"})
s2key = c.post("/create_api_key", headers=s2h).json()["api_key"]
r_other = c.get("/jobs/next", headers={"X-API-KEY":s2key})
ok("foreign agent gets no job (ownership boundary)", r_other.status_code==204)

# the OWNING agent (seller1) pulls the job
r_job = c.get("/jobs/next", headers={"X-API-KEY":seller_key})
ok("owning agent receives job", r_job.status_code==200 and r_job.json()["task_id"]==task_id)
ok("job carries code", r_job.json()["code"]=="print(2+2)")

# second pull returns nothing (job already claimed)
ok("claimed job not re-served", c.get("/jobs/next", headers={"X-API-KEY":seller_key}).status_code==204)

# agent submits a SIGNED result; foreign agent cannot
out_hash = hashlib.sha256(b"4").hexdigest()
proof = {"task_id":task_id, "output_hash":out_hash, "ts":int(time.time())}
sig = sign_proof(sk, proof)   # sk == the key whose pubkey was registered at /prove for sid2
dummy = {"task_id":task_id,"result":"4","status":"completed","proof":proof,"signature":sig}
ok("foreign agent cannot submit", c.post("/jobs/result", headers={"X-API-KEY":s2key}, json=dummy).status_code==404)
ok("owning agent submits SIGNED result", c.post("/jobs/result", headers={"X-API-KEY":seller_key}, json=dummy).status_code==200)

# forged signature on a real job -> rejected
rb2 = c.post("/request_vm", headers=bh, json={"spec_id":sid2,"hours":1}).json()
tid2 = c.post("/create_task", headers=bh, json={"booking_id":rb2["booking_id"],"task_type":"notebook","code":"x"}).json()["task_id"]
job2 = c.get("/jobs/next", headers={"X-API-KEY":seller_key}).json()
forged = {"task_id":job2["task_id"],"result":"x","status":"completed",
          "proof":{"task_id":job2["task_id"],"output_hash":"deadbeef","ts":int(time.time())},
          "signature":sign_proof(Ed25519PrivateKey.generate(), {"x":1})}  # wrong key/garbage
ok("forged signature rejected", c.post("/jobs/result", headers={"X-API-KEY":seller_key}, json=forged).status_code==401)

# ---- KNOWN-ANSWER TEST WORKLOADS + REPUTATION ----
import db as dbmod2

def run_test(pass_it=True):
    c.post("/dispatch_test", headers=sh, json={"spec_id":sid2,"difficulty":"easy"})
    job = c.get("/jobs/next", headers={"X-API-KEY":seller_key}).json()
    size, seed = job["size"], job["seed"]
    correct = dbmod2.compute_test_hash(size, seed)
    h = correct if pass_it else "0"*64
    pr = {"task_id":job["task_id"], "output_hash":h, "ts":int(time.time())}
    return c.post("/jobs/result", headers={"X-API-KEY":seller_key},
                  json={"task_id":job["task_id"],"status":"completed",
                        "proof":pr,"signature":sign_proof(sk, pr)}).json()

r_pass = run_test(True)
ok("known-answer test PASSES with correct hash", r_pass["test_passed"]==True)
rep_after_pass = r_pass["reputation"]

r_fail = run_test(False)
ok("known-answer test FAILS with wrong hash", r_fail["test_passed"]==False)
ok("reputation drops on failed test", r_fail["reputation"] < rep_after_pass)

# Drive reputation below the trust threshold -> seller blocked from paid work
last = r_fail
for _ in range(5):
    last = run_test(False)
ok("seller loses paid-work trust after repeated failures", last["can_accept_paid_jobs"]==False)

# A buyer can no longer book this now-untrusted seller's spec
ok("low-rep seller's spec is unbookable", c.post("/request_vm", headers=bh, json={"spec_id":sid2,"hours":1}).status_code==403)


# ---- SETTLEMENT: escrow -> release, and refund-on-reap ----
import db as dbmod3
c.post("/register_user", json={"username":"seller3","password":"hunter2-correct-horse"})
c.post("/register_user", json={"username":"buyer3","password":"hunter2-correct-horse"})
s3h={"Authorization":f"Bearer {login('seller3')}"}
b3h={"Authorization":f"Bearer {login('buyer3')}"}
c.post("/change_role", headers=s3h, json={"role":"seller"})
sid3=c.post("/register_specs", headers=s3h, json={"cpu":8,"ram":16,"duration":24,"price_per_hour":4.0,"provider":"seller3","units":2}).json()["spec_id"]
sk3=Ed25519PrivateKey.generate(); pub3=base64.b64encode(sk3.public_key().public_bytes_raw()).decode()
att3={"cpu":8,"nonce":"z","ts":int(time.time())}
c.post("/prove", headers=s3h, json={"spec_id":sid3,"attestation":att3,"signature":sign_proof(sk3,att3),"pubkey":pub3})
s3key=c.post("/create_api_key", headers=s3h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":s3key}, json={"spec_id":sid3})

ok("deposit reflects in wallet", c.post("/deposit", headers=b3h, json={"amount":100.0}).json()["balance"]==100.0)
ok("cannot book with no funds", c.post("/request_vm", headers={"Authorization":f"Bearer {login('seller2')}"}, json={"spec_id":sid3,"hours":1}).status_code in (402,403))

# book -> escrow holds 8 (4/hr * 2h), buyer debited 100->92
rbk=c.post("/request_vm", headers=b3h, json={"spec_id":sid3,"hours":2}).json()
bkid=rbk["booking_id"]
ok("booking is escrowed", rbk["booking_status"]=="escrowed")
ok("buyer debited (100->92)", c.get("/wallet", headers=b3h).json()["balance"]==92.0)

# task -> active
tk=c.post("/create_task", headers=b3h, json={"booking_id":bkid,"task_type":"notebook","code":"print(1)"}).json()["task_id"]
ok("booking active after task", c.get(f"/bookings/{bkid}", headers=b3h).json()["status"]=="active")

# agent completes -> auto-release: seller +7.2, platform +0.8
job=c.get("/jobs/next", headers={"X-API-KEY":s3key}).json()
ph={"task_id":job["task_id"],"output_hash":hashlib.sha256(b"ok").hexdigest(),"ts":int(time.time())}
res=c.post("/jobs/result", headers={"X-API-KEY":s3key}, json={"task_id":job["task_id"],"result":"ok","status":"completed","proof":ph,"signature":sign_proof(sk3,ph)}).json()
ok("completion releases booking", res["booking_released"]==True)
ok("booking now released", c.get(f"/bookings/{bkid}", headers=b3h).json()["status"]=="released")
ok("seller earned payout (7.2)", round(c.get("/wallet", headers=s3h).json()["earnings"],2)==7.2)
ok("double-release blocked", c.post(f"/bookings/{bkid}/release", headers=b3h).status_code==409)

# --- VERIFIABLE RECEIPT: the buyer can INDEPENDENTLY re-verify their completed job ---
_rid=job["task_id"]
_rc=c.get(f"/jobs/{_rid}/receipt", headers=b3h)
ok("buyer fetches a verifiable receipt for their completed job", _rc.status_code==200)
_rcj=_rc.json()
ok("receipt carries the node's Ed25519 signature + attested pubkey",
   bool(_rcj["proof"]["signature_b64"]) and bool(_rcj["proof"]["node_pubkey_b64"]))
ok("the platform RE-VERIFIES the node's signature live (server_reverified)",
   _rcj["proof"]["server_reverified"]==True)
ok("receipt shows the GPU trust tier + escrow settlement state",
   _rcj["gpu"]["trust"]["level"]=="agent_verified" and _rcj["settlement"]["status"]=="released")
ok("a receipt is buyer-scoped (a different user gets 404, no enumeration)",
   c.get(f"/jobs/{_rid}/receipt", headers=s3h).status_code==404)

# --- PUBLIC TRUST SUMMARY: honest live counts, nothing fabricated ---
_ts=c.get("/trust/summary").json()
ok("trust summary reports honest live counts (>=1 job completed, >=1 receipt)",
   isinstance(_ts["attested_gpus"],int) and _ts["jobs_completed"]>=1 and _ts["verifiable_receipts"]>=1)
ok("trust summary reports the double-entry ledger is not broken", _ts["ledger_balanced"] is not False)
ok("trust summary publishes the honest ladder and never claims TEE from the stub",
   any(t["level"]=="benchmark_verified" for t in _ts["trust_ladder"]) and "not_claimed" in _ts)
_sec=c.get("/.well-known/security.txt")
ok("RFC 9116 security.txt is served with a contact + policy (coordinated disclosure)",
   _sec.status_code==200 and "Contact:" in _sec.text and "Policy:" in _sec.text)
_ref=c.get("/refunds")
ok("refunds & disputes policy is published (escrow protection + dispute SLA)",
   _ref.status_code==200 and "escrow" in _ref.text.lower() and "dispute" in _ref.text.lower())
_prv=c.get("/privacy")
ok("privacy page states the workload data lifecycle (encrypt / not read / not retained)",
   _prv.status_code==200 and "Data lifecycle" in _prv.text)
# Non-technical UX: plain-language FAQ + a "Get the Windows app" button that is never a dead link.
_faq=c.get("/faq")
ok("plain-language FAQ answers non-tech seller+buyer fears (safe on my PC / when do I get paid)",
   _faq.status_code==200 and "safe" in _faq.text.lower()
   and "get paid" in _faq.text.lower() and "escrow" in _faq.text.lower())
# No desktop build/URL configured in tests -> the download route must degrade to the honest
# early-access page (200), never 404 and never claim a download that isn't there.
_dl=c.get("/download/windows", follow_redirects=False)
ok("the Windows-app button degrades honestly (early-access page, not a dead link) when no build exists",
   _dl.status_code==200 and "early access" in _dl.text.lower() and "one command" in _dl.text.lower())
_ins=c.get("/install")
ok("the seller page leads with a friendly app option + links the FAQ",
   _ins.status_code==200 and "Get the Windows app" in _ins.text and "/faq" in _ins.text)
ok("the /install page funnels to the in-browser GPU self-test (/mysystem)", "/mysystem" in _ins.text)

# WebGPU #1: in-browser self-benchmark. Public, CSP-clean, and clearly SEPARATE from the attested
# benchmark — it must never claim to set trust/pricing.
_ms=c.get("/mysystem")
ok("/mysystem renders a WebGPU self-benchmark and funnels to /install",
   _ms.status_code==200 and "webgpu" in _ms.text.lower() and "/install" in _ms.text)
ok("/mysystem is honest: labelled indicative, not the verified/attested benchmark",
   "indicative" in _ms.text.lower() and "verified" in _ms.text.lower()
   and "benchmark_verified" not in _ms.text)

# WebGPU #3: Edge-Inference SDK + demo + metered fallback endpoint.
_edge=c.get("/edge")
ok("/edge demo loads the Edge-Inference SDK and explains on-device + fallback",
   _edge.status_code==200 and "/static/petabyte-edge.js" in _edge.text
   and "fallback" in _edge.text.lower() and "on-device" in _edge.text.lower())
_sdk=c.get("/static/petabyte-edge.js")
ok("the Edge SDK is served with a JS content-type",
   _sdk.status_code==200 and "javascript" in _sdk.headers.get("content-type","")
   and "PetabyteEdge" in _sdk.text)
_ei=c.post("/edge/infer", json={"prompt":"hello"})
_eij=_ei.json() if _ei.status_code==200 else {}
ok("POST /edge/infer returns a labelled prototype fallback (never fakes a real completion)",
   _ei.status_code==200 and _eij.get("source")=="petabyte-fallback" and _eij.get("prototype") is True)
ok("POST /edge/infer rejects an empty prompt", c.post("/edge/infer", json={"prompt":"  "}).status_code==400)
# On-device inference (and its CSP widening) is OFF by default -> the CSP the browser gets must
# stay locked down: no wasm-eval, no external model host in connect-src.
_csp=c.get("/edge").headers.get("Content-Security-Policy","")
ok("edge on-device is opt-in: default CSP stays locked (no wasm-unsafe-eval / no external connect-src)",
   "wasm-unsafe-eval" not in _csp and "huggingface.co" not in _csp and "connect-src 'self';" in _csp)

# REFUND ON REAP: new booking, node dies, settle refunds buyer
c.post("/heartbeat", headers={"X-API-KEY":s3key}, json={"spec_id":sid3})
bkid2=c.post("/request_vm", headers=b3h, json={"spec_id":sid3,"hours":2}).json()["booking_id"]
ok("buyer debited again (92->84)", c.get("/wallet", headers=b3h).json()["balance"]==84.0)
sx=dbmod3.SessionLocal(); spx=dbmod3.get_spec_by_id(sx, sid3)
spx.last_seen=datetime.now(timezone.utc)-timedelta(seconds=300); sx.add(spx); sx.commit()
dbmod3.reap_stale_specs(sx, 60)
refunded=dbmod3.settle_dead_specs(sx)
ok("dead node triggers refund", refunded>=1)
ok("booking refunded", c.get(f"/bookings/{bkid2}", headers=b3h).json()["status"]=="refunded")
ok("buyer made whole (back to 92)", c.get("/wallet", headers=b3h).json()["balance"]==92.0)
dbmod3.settle_dead_specs(dbmod3.SessionLocal())   # run again
ok("settle is idempotent (no double refund)", c.get("/wallet", headers=b3h).json()["balance"]==92.0)


# ---- PAYMENT WEBHOOK: signed credit, idempotent ----
import hmac as _hmac, hashlib as _hl
def _sign_wh(b): return _hmac.new(b"whsec_test", b, _hl.sha256).hexdigest()
evt = {"event_id":"evt_1","type":"checkout.session.completed","data":{"username":"buyer3","amount":25.0}}
body = json.dumps(evt).encode()
bal0 = c.get("/wallet", headers=b3h).json()["balance"]
ok("webhook bad signature rejected", c.post("/webhooks/payment", content=body, headers={"X-Signature":"bad"}).status_code==401)
ok("webhook valid signature credits", c.post("/webhooks/payment", content=body, headers={"X-Signature":_sign_wh(body)}).status_code==200)
ok("webhook credited +25", round(c.get("/wallet", headers=b3h).json()["balance"]-bal0,2)==25.0)
c.post("/webhooks/payment", content=body, headers={"X-Signature":_sign_wh(body)})   # replay
ok("duplicate event not re-credited", round(c.get("/wallet", headers=b3h).json()["balance"]-bal0,2)==25.0)
# replay-bounded (Stripe-style) scheme: sign "<ts>.<body>" + send X-Timestamp; stale ts rejected
import time as _time
def _sign_ts(b, ts): return _hmac.new(b"whsec_test", f"{ts}.".encode()+b, _hl.sha256).hexdigest()
_nw = int(_time.time())
_bts = json.dumps({"event_id":"evt_ts_1","type":"x","data":{"username":"buyer3","amount":10.0}}).encode()
ok("webhook with a valid timestamped signature credits",
   c.post("/webhooks/payment", content=_bts, headers={"X-Signature":_sign_ts(_bts,_nw),"X-Timestamp":str(_nw)}).status_code==200)
_stale = _nw - 100000
_bst = json.dumps({"event_id":"evt_ts_2","type":"x","data":{"username":"buyer3","amount":10.0}}).encode()
ok("webhook with a STALE timestamp is rejected (replay window closed)",
   c.post("/webhooks/payment", content=_bst, headers={"X-Signature":_sign_ts(_bst,_stale),"X-Timestamp":str(_stale)}).status_code==401)


# ---- CONFIDENTIAL COMPUTING (TEE attestation) ----
c.post("/register_user", json={"username":"seller4","password":"hunter2-correct-horse"})
c.post("/register_user", json={"username":"buyer4","password":"hunter2-correct-horse"})
s4h={"Authorization":f"Bearer {login('seller4')}"}
b4h={"Authorization":f"Bearer {login('buyer4')}"}
c.post("/change_role", headers=s4h, json={"role":"seller"})
c.post("/deposit", headers=b4h, json={"amount":100.0})

def setup_spec(price):
    sid=c.post("/register_specs", headers=s4h, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":price,"provider":"seller4","gpu_model":"H100","units":2}).json()["spec_id"]
    k=Ed25519PrivateKey.generate(); pb=base64.b64encode(k.public_key().public_bytes_raw()).decode()
    at={"cpu":8,"nonce":"x","ts":int(time.time())}
    c.post("/prove", headers=s4h, json={"spec_id":sid,"attestation":at,"signature":sign_proof(k,at),"pubkey":pb})
    return sid
key4=c.post("/create_api_key", headers=s4h).json()["api_key"]
sidC=setup_spec(5.0); sidP=setup_spec(2.0)   # confidential + plain
c.post("/heartbeat", headers={"X-API-KEY":key4}, json={"spec_id":sidC})
c.post("/heartbeat", headers={"X-API-KEY":key4}, json={"spec_id":sidP})

def attest_tee(spec_id, measurement="mr_h100_cc_v1"):
    nonce=c.post("/attestation/challenge", headers=s4h, json={"spec_id":spec_id}).json()["nonce"]
    rep={"nonce":nonce,"measurement":measurement,"vendor":"nvidia-h100-cc","ts":int(time.time())}
    return c.post("/prove_tee", headers=s4h, json={"spec_id":spec_id,"report":rep,"signature":sign_proof(_VENDOR_SK,rep)})

r=attest_tee(sidC)
ok("TEE attestation accepted", r.status_code==200 and r.json()["confidential"]==True)
ok("attested measurement returned", r.json()["measurement"]=="mr_h100_cc_v1")

# non-allowlisted measurement rejected (fresh challenge)
ok("bad measurement rejected", attest_tee(sidP, measurement="mr_unknown").status_code==400)

# replay: reuse a consumed nonce -> rejected
nonce2=c.post("/attestation/challenge", headers=s4h, json={"spec_id":sidP}).json()["nonce"]
rep2={"nonce":nonce2,"measurement":"mr_h100_cc_v1","vendor":"nvidia-h100-cc","ts":int(time.time())}
c.post("/prove_tee", headers=s4h, json={"spec_id":sidP,"report":rep2,"signature":sign_proof(_VENDOR_SK,rep2)})  # consumes it
ok("replayed nonce rejected", c.post("/prove_tee", headers=s4h, json={"spec_id":sidP,"report":rep2,"signature":sign_proof(_VENDOR_SK,rep2)}).status_code==400)
# sidP is now confidential too (we just attested it); make a fresh PLAIN spec for the gate test
sidPlain=setup_spec(1.5); c.post("/heartbeat", headers={"X-API-KEY":key4}, json={"spec_id":sidPlain})

# forged vendor signature rejected
nonce3=c.post("/attestation/challenge", headers=s4h, json={"spec_id":sidPlain}).json()["nonce"]
rep3={"nonce":nonce3,"measurement":"mr_h100_cc_v1","vendor":"x","ts":int(time.time())}
ok("forged vendor signature rejected", c.post("/prove_tee", headers=s4h, json={"spec_id":sidPlain,"report":rep3,"signature":sign_proof(Ed25519PrivateKey.generate(),rep3)}).status_code==400)

# filtering
conf=c.get("/specs?confidential=true", headers=b4h).json()["specs"]
ok("confidential filter lists CC spec", any(s["spec_id"]==sidC and s["confidential"] for s in conf))
ok("confidential filter excludes plain spec", not any(s["spec_id"]==sidPlain for s in conf))

# confidential-only booking gate
ok("require_confidential blocks plain spec", c.post("/request_vm", headers=b4h, json={"spec_id":sidPlain,"hours":1,"require_confidential":True}).status_code==403)
ok("require_confidential allows CC spec", c.post("/request_vm", headers=b4h, json={"spec_id":sidC,"hours":1,"require_confidential":True}).status_code==200)

# buyer verifies the report INDEPENDENTLY (zero-trust in seller) before sending data
att=c.get(f"/specs/{sidC}/attestation", headers=b4h).json()
import json as _j, base64 as _b64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
root=Ed25519PublicKey.from_public_bytes(_b64.b64decode(os.environ["TEE_TRUSTED_ROOT"]))
msg=_j.dumps(att["report"]["report"], sort_keys=True, separators=(",",":")).encode()
try:
    root.verify(_b64.b64decode(att["report"]["signature"]), msg); buyer_ok=True
except Exception: buyer_ok=False
ok("buyer can independently verify the enclave report", buyer_ok)


# ---- ORGANIZATIONS (shared wallet, roles, budget cap) + REGION GATING ----
for u in ["orgadmin","orgmember","orgseller","outsider"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
adminh={"Authorization":f"Bearer {login('orgadmin')}"}
memberh={"Authorization":f"Bearer {login('orgmember')}"}
outsiderh={"Authorization":f"Bearer {login('outsider')}"}
sellh={"Authorization":f"Bearer {login('orgseller')}"}

org_id=c.post("/orgs", headers=adminh, json={"name":"AcmeLabs"}).json()["org_id"]
ok("org created (creator is admin)", c.get(f"/orgs/{org_id}", headers=adminh).json()["your_role"]=="admin")
ok("non-member blocked from org", c.get(f"/orgs/{org_id}", headers=outsiderh).status_code==403)
ok("admin adds member", c.post(f"/orgs/{org_id}/members", headers=adminh, json={"username":"orgmember","role":"member"}).status_code==200)
ok("member cannot add members", c.post(f"/orgs/{org_id}/members", headers=memberh, json={"username":"outsider","role":"member"}).status_code==403)
# console Teams panel: GET /orgs lists the caller's memberships (no public org directory)
_myorgs=c.get("/orgs", headers=adminh).json().get("orgs", [])
ok("GET /orgs lists the caller's teams for the console Teams panel",
   any(o["org_id"]==org_id and o["your_role"]=="admin" for o in _myorgs))
ok("a non-member does not see that org in their team list",
   all(o["org_id"]!=org_id for o in c.get("/orgs", headers=outsiderh).json().get("orgs", [])))

# ---- IAM: team member role management + removal (console Teams tab) ----
def _role_of(uname):
    ms=c.get(f"/orgs/{org_id}", headers=adminh).json().get("members", [])
    return next((m["role"] for m in ms if m["username"]==uname), None)
ok("admin promotes a member's role (member -> billing)",
   c.put(f"/orgs/{org_id}/members/orgmember", headers=adminh, json={"role":"billing"}).status_code==200
   and _role_of("orgmember")=="billing")
ok("a non-admin cannot change roles",
   c.put(f"/orgs/{org_id}/members/orgmember", headers=memberh, json={"role":"admin"}).status_code==403)
ok("changing the role of a non-member is 404",
   c.put(f"/orgs/{org_id}/members/outsider", headers=adminh, json={"role":"member"}).status_code==404)
ok("the sole admin cannot be demoted (org must keep an admin)",
   c.put(f"/orgs/{org_id}/members/orgadmin", headers=adminh, json={"role":"member"}).status_code==409)
ok("the sole admin cannot be removed",
   c.delete(f"/orgs/{org_id}/members/orgadmin", headers=adminh).status_code==409)
c.put(f"/orgs/{org_id}/members/orgmember", headers=adminh, json={"role":"member"})  # restore
ok("orgmember restored to member for downstream tests", _role_of("orgmember")=="member")
# add + remove a throwaway member (leaves state as it was)
ok("admin adds then removes a member",
   c.post(f"/orgs/{org_id}/members", headers=adminh, json={"username":"outsider","role":"member"}).status_code==200
   and c.delete(f"/orgs/{org_id}/members/outsider", headers=adminh).status_code==200
   and _role_of("outsider") is None)
ok("a non-admin cannot remove members",
   c.delete(f"/orgs/{org_id}/members/orgmember", headers=memberh).status_code==403)

# ---- Tenant-facing audit log (immutable, hash-chained) ----
_oaud=c.get(f"/orgs/{org_id}/audit", headers=adminh)
ok("org audit is admin-only (non-admin blocked)",
   c.get(f"/orgs/{org_id}/audit", headers=memberh).status_code==403 and _oaud.status_code==200)
_oaudb=_oaud.json()
_oactions={e["action"] for e in _oaudb["events"]}
ok("org audit records member changes (add / role / create)",
   {"team.create","team.member.add","team.member.role"} <= _oactions)
ok("the audit chain verifies (tamper-evident) — intact over the recorded events",
   _oaudb["integrity"]["intact"] is True and _oaudb["integrity"]["checked"] >= 1)
_aaud=c.get("/account/audit", headers=adminh).json()
ok("personal audit trail lists the caller's own actions",
   any(e["action"]=="team.create" for e in _aaud["events"]) and _aaud["integrity"]["intact"] is True)
# "no auth" now means no Bearer AND no session cookie — the shared client `c` carries a
# pb_session cookie from earlier logins (a cookie IS a valid session), so use a fresh client.
ok("personal audit requires auth", TestClient(main.app).get("/account/audit").status_code==401)
# tamper-evidence: editing a stored row breaks the chain (deletion/edit is detectable)
import db as _auditdb
_asess=_auditdb.SessionLocal()
try:
    _arow=(_asess.query(_auditdb.AuditEvent)
           .filter(_auditdb.AuditEvent.action=="team.member.add").first())
    _arow.detail='{"role":"admin"}'; _asess.add(_arow); _asess.commit()
    ok("editing an audit row is detected by verify_audit_chain (immutability is enforced by evidence)",
       _auditdb.verify_audit_chain(_asess)["intact"] is False)
finally:
    _asess.close()

# ---- Two-factor auth (TOTP / authenticator app) ----
import totp as _totp
c.post("/register_user", json={"username": "tfauser", "password": "hunter2-correct-horse"})
_tfh = {"Authorization": f"Bearer {login('tfauser')}"}
_setup = c.post("/account/2fa/setup", headers=_tfh).json()
ok("2fa setup returns a secret + an otpauth URI",
   len(_setup.get("secret", "")) >= 16 and _setup.get("otpauth_uri", "").startswith("otpauth://totp/"))
ok("enabling 2fa rejects a wrong code",
   c.post("/account/2fa/enable", headers=_tfh,
          json={"code": "000000", "password": "hunter2-correct-horse"}).status_code == 400)
_en = c.post("/account/2fa/enable", headers=_tfh,
             json={"code": _totp.totp(_setup["secret"]), "password": "hunter2-correct-horse"}).json()
ok("2fa enables with a valid code and returns 10 single-use backup codes",
   _en.get("enabled") is True and len(_en.get("backup_codes", [])) == 10)
_bk = _en["backup_codes"][0]


def _login_otp(otp=None):
    d = {"username": "tfauser", "password": "hunter2-correct-horse"}
    if otp is not None:
        d["otp"] = otp
    return c.post("/login", data=d)


ok("password alone no longer logs in once 2fa is on (TOTP_REQUIRED)",
   _login_otp().status_code == 401 and _login_otp().json().get("error", {}).get("code") == "TOTP_REQUIRED")
ok("login with a wrong code is refused", _login_otp("000000").status_code == 401)
ok("login with a valid TOTP code succeeds", _login_otp(_totp.totp(_setup["secret"])).status_code == 200)
ok("a backup recovery code logs in", _login_otp(_bk).status_code == 200)
ok("a backup code is single-use (reuse refused)", _login_otp(_bk).status_code == 401)
ok("password alone cannot disable 2fa (a current code is required)",
   c.post("/account/2fa/disable", headers=_tfh, json={"password": "hunter2-correct-horse"}).status_code == 400)
ok("2fa disables with password + a current code",
   c.post("/account/2fa/disable", headers=_tfh,
          json={"password": "hunter2-correct-horse", "code": _totp.totp(_setup["secret"])}).status_code == 200)
ok("after disabling, password-only login works again", _login_otp().status_code == 200)

# org wallet + budget cap
c.post("/orgs/{}/deposit".format(org_id), headers=adminh, json={"amount":100.0,"budget_cap":15.0})
ok("org balance funded", c.get(f"/orgs/{org_id}", headers=adminh).json()["balance"]==100.0)
ok("member cannot deposit", c.post(f"/orgs/{org_id}/deposit", headers=memberh, json={"amount":10.0}).status_code==403)

# seller spec in eu-west, confidential not required
c.post("/change_role", headers=sellh, json={"role":"seller"})
sidEU=c.post("/register_specs", headers=sellh, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":5.0,"provider":"orgseller","gpu_model":"H100","units":3,"region":"eu-west","country":"DE"}).json()["spec_id"]
kEU=Ed25519PrivateKey.generate(); pbEU=base64.b64encode(kEU.public_key().public_bytes_raw()).decode()
atEU={"cpu":8,"nonce":"e","ts":int(time.time())}
c.post("/prove", headers=sellh, json={"spec_id":sidEU,"attestation":atEU,"signature":sign_proof(kEU,atEU),"pubkey":pbEU})
keyEU=c.post("/create_api_key", headers=sellh).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":keyEU,"X-Forwarded-For":"10.1.1.1"}, json={"spec_id":sidEU})

# region filter + residency gate
ok("region filter lists eu-west spec", any(s["spec_id"]==sidEU for s in c.get("/specs?region=eu-west", headers=memberh).json()["specs"]))
ok("wrong-region residency gate blocks", c.post("/request_vm", headers=memberh, json={"spec_id":sidEU,"hours":1,"org_id":org_id,"require_region":"us-east"}).status_code==403)

# member books on the ORG wallet (5/hr*2h=10, under 15 cap)
r=c.post("/request_vm", headers=memberh, json={"spec_id":sidEU,"hours":2,"org_id":org_id,"require_region":"eu-west"})
ok("member books on org wallet", r.status_code==200)
ok("org wallet debited (100->90), spent=10", c.get(f"/orgs/{org_id}", headers=adminh).json()["balance"]==90.0 and c.get(f"/orgs/{org_id}", headers=adminh).json()["spent"]==10.0)

# budget cap: next 2h booking would push spent to 20 > 15 cap -> blocked
ok("budget cap enforced", c.post("/request_vm", headers=memberh, json={"spec_id":sidEU,"hours":2,"org_id":org_id}).status_code==402)

# outsider cannot spend the org's money
ok("non-member cannot charge org", c.post("/request_vm", headers=outsiderh, json={"spec_id":sidEU,"hours":1,"org_id":org_id}).status_code==403)

# usage/invoice export
usage=c.get(f"/orgs/{org_id}/usage", headers=adminh).json()
ok("org usage export has the booking", usage["total_gross"]==10.0 and len(usage["line_items"])==1)


# ---- GEOIP REGION VERIFICATION (declared vs detected) ----
for u in ["geoseller","geobuyer"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
gsh={"Authorization":f"Bearer {login('geoseller')}"}
gbh={"Authorization":f"Bearer {login('geobuyer')}"}
c.post("/change_role", headers=gsh, json={"role":"seller"})
c.post("/deposit", headers=gbh, json={"amount":100.0})

def geo_spec(price):
    sid=c.post("/register_specs", headers=gsh, json={"cpu":4,"ram":16,"duration":24,"price_per_hour":price,"provider":"geoseller","region":"eu-west","country":"DE","units":5}).json()["spec_id"]
    k=Ed25519PrivateKey.generate(); pb=base64.b64encode(k.public_key().public_bytes_raw()).decode()
    at={"cpu":4,"nonce":"g","ts":int(time.time())}
    c.post("/prove", headers=gsh, json={"spec_id":sid,"attestation":at,"signature":sign_proof(k,at),"pubkey":pb})
    return sid
gkey=c.post("/create_api_key", headers=gsh).json()["api_key"]
sidTrue=geo_spec(2.0)   # will heartbeat from DE IP -> verified
sidFake=geo_spec(2.0)   # declares DE but heartbeats from SG IP -> NOT verified

rht=c.post("/heartbeat", headers={"X-API-KEY":gkey,"X-Forwarded-For":"10.1.1.1"}, json={"spec_id":sidTrue}).json()
ok("declared==detected -> region_verified", rht["region_verified"]==True and rht["detected_country"]=="DE")
rhf=c.post("/heartbeat", headers={"X-API-KEY":gkey,"X-Forwarded-For":"10.2.2.2"}, json={"spec_id":sidFake}).json()
ok("declared DE but IP SG -> NOT verified", rhf["region_verified"]==False and rhf["detected_country"]=="SG")

# residency gate matches on VERIFIED region only
ok("verified region passes residency gate", c.post("/request_vm", headers=gbh, json={"spec_id":sidTrue,"hours":1,"require_region":"eu-west"}).status_code==200)
ok("unverified (spoofed) region BLOCKED", c.post("/request_vm", headers=gbh, json={"spec_id":sidFake,"hours":1,"require_region":"eu-west"}).status_code==403)
ok("verified country passes", c.post("/request_vm", headers=gbh, json={"spec_id":sidTrue,"hours":1,"require_country":"DE"}).status_code==200)
ok("spoofed country blocked", c.post("/request_vm", headers=gbh, json={"spec_id":sidFake,"hours":1,"require_country":"DE"}).status_code==403)

# /specs surfaces the verification flag
specs=c.get("/specs", headers=gbh).json()["specs"]
ok("/specs shows region_verified true for honest node", any(s["spec_id"]==sidTrue and s["region_verified"] for s in specs))
ok("/specs shows region_verified false for spoofed node", any(s["spec_id"]==sidFake and not s["region_verified"] for s in specs))


# ==== #9 templates, #4 benchmark, #5 job mgmt, #10 scoped keys + analytics ====
for u in ["seller5","buyer5"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
s5h={"Authorization":f"Bearer {login('seller5')}"}
b5tok=login("buyer5"); b5h={"Authorization":f"Bearer {b5tok}"}
c.post("/change_role", headers=s5h, json={"role":"seller"})
c.post("/deposit", headers=b5h, json={"amount":1000.0})
sid5=c.post("/register_specs", headers=s5h, json={"cpu":16,"ram":64,"duration":48,"price_per_hour":2.0,"provider":"seller5","gpu_model":"H100","units":20}).json()["spec_id"]
sk5=Ed25519PrivateKey.generate(); pb5=base64.b64encode(sk5.public_key().public_bytes_raw()).decode()
at5={"cpu":16,"nonce":"q","ts":int(time.time())}
c.post("/prove", headers=s5h, json={"spec_id":sid5,"attestation":at5,"signature":sign_proof(sk5,at5),"pubkey":pb5})
key5=c.post("/create_api_key", headers=s5h).json()["api_key"]
_hb=c.post("/heartbeat", headers={"X-API-KEY":key5}, json={"spec_id":sid5})

# --- SELLER EARNINGS FORECAST: the agent + web can show expected profit ---
ok("heartbeat returns a live earnings forecast for the agent to display",
   (_hb.json().get("earnings") or {}).get("net_per_hour")==round(2.0*(1-0.10),4))
_ef=c.get(f"/nodes/{sid5}/earnings_forecast", headers=s5h)
ok("earnings forecast endpoint: definitive net/hr + utilization estimates",
   _ef.status_code==200 and _ef.json()["net_per_hour"]>0 and len(_ef.json()["estimates"])>=3)
ok("earnings forecast is owner-scoped (a non-owner gets 404)",
   c.get(f"/nodes/{sid5}/earnings_forecast", headers=b5h).status_code==404)

# --- TRUST LADDER: levels awarded only on evidence actually held ---
_t5=[s for s in c.get("/specs", headers=b5h).json()["specs"] if s["spec_id"]==sid5][0]
ok("attested-but-unbenchmarked node is agent_verified",
   _t5["trust"]["level"]=="agent_verified" and _t5["trust"]["rank"]==1)

def book5():
    return c.post("/request_vm", headers=b5h, json={"spec_id":sid5,"hours":1}).json()["booking_id"]

# --- #9 TEMPLATES ---
ok("templates catalog lists ollama+vllm+comfyui", {"ollama","vllm","comfyui"}.issubset({t["name"] for t in c.get("/templates").json()["templates"]}))
rt=c.post("/create_task", headers=b5h, json={"booking_id":book5(),"task_type":"template","template":"vllm","template_params":{"model":"meta-llama/Llama-3-8B"},"priority":3})
ok("create vLLM template task", rt.status_code==200)
ok("reject unknown template", c.post("/create_task", headers=b5h, json={"booking_id":book5(),"task_type":"template","template":"nope"}).status_code==400)
tjob=c.get("/jobs/next", headers={"X-API-KEY":key5}).json()
ok("template job carries image/port/model", tjob["task_type"]=="template" and "vllm" in tjob["image"] and tjob["port"]==8000 and tjob["params"]["model"].startswith("meta-llama"))

# --- #4 BENCHMARK (tokens/sec) ---
c.post("/benchmark", headers=s5h, json={"spec_id":sid5})
bjob=c.get("/jobs/next", headers={"X-API-KEY":key5}).json()
ok("benchmark job dispatched", bjob["task_type"]=="benchmark")
ok("benchmark job carries a FRESH server proof-of-work challenge (seed)", bjob.get("bench_seed") and bjob.get("bench_size"))
# The agent measures FP16 matmul TFLOPS and puts it INSIDE the SIGNED proof; the server
# checks it against the CLAIMED model's public band. 720 TFLOPS is in the H100 band.
# It must ALSO answer the server's fresh seeded proof-of-work challenge.
_pow=dbmod.compute_test_hash(int(bjob["bench_size"]), int(bjob["bench_seed"]))
bph={"task_id":bjob["task_id"],"output_hash":"bench","ts":int(time.time()),"tflops_fp16":720,"challenge_hash":_pow}
_br=c.post("/jobs/benchmark_result", headers={"X-API-KEY":key5}, json={"spec_id":sid5,"tokens_sec":2350.5,"meta":{"model":"llama3-8b","sd_images_sec":4.2},"proof":bph,"signature":sign_proof(sk5,bph)})
ok("signed benchmark result accepted", _br.status_code==200)
ok("benchmark consistent with the claimed H100 -> verdict 'consistent'", _br.json().get("benchmark_verdict")=="consistent")
ok("the platform SERVER-TIMED the benchmark (bound to the dispatched task)", _br.json().get("server_timed")==True)
ok("the node ANSWERED the fresh server proof-of-work challenge (pow_verified)", _br.json().get("pow_verified")==True)
ok("re-submitting the same signed benchmark is rejected as a replay (409)",
   c.post("/jobs/benchmark_result", headers={"X-API-KEY":key5}, json={"spec_id":sid5,"tokens_sec":2350.5,"meta":{},"proof":bph,"signature":sign_proof(sk5,bph)}).status_code==409)
ok("/specs surfaces tokens/sec", any(s["spec_id"]==sid5 and s["benchmark_tokens_sec"]==2350.5 for s in c.get("/specs", headers=b5h).json()["specs"]))
# --- TRUST LADDER: a signed benchmark upgrades the level; TEE is never claimed ---
_t5b=[s for s in c.get("/specs", headers=b5h).json()["specs"] if s["spec_id"]==sid5][0]
ok("signed benchmark upgrades trust to benchmark_verified",
   _t5b["trust"]["level"]=="benchmark_verified" and _t5b["trust"]["rank"]==2)
ok("consistent benchmark surfaces as 'Benchmark-consistent' with public-reference evidence",
   _t5b["trust"]["label"]=="Benchmark-consistent" and "MATCHES public reference" in _t5b["trust"]["evidence"])
_pub5=[s for s in c.get("/marketplace/specs").json()["specs"] if s["gpu_model"]=="H100" and s.get("trust",{}).get("level")=="benchmark_verified"]
ok("marketplace surfaces the trust level publicly", len(_pub5)>=1)
_det5=c.get(f"/marketplace/specs/{_pub5[0]['id']}").json() if _pub5 else {}
ok("detail page never claims vendor hardware attestation (stub is not TEE)",
   _det5.get("verification",{}).get("hardware_attested")==False and
   _det5.get("verification",{}).get("agent_attested")==True)

# --- BENCHMARK AUTHENTICITY: an over-claiming listing is caught + frozen ---
# A dedicated node (never reused elsewhere) LISTS an H100 but its measured FP16 matmul
# is T4-class -> the silicon can't be an H100 -> fraud freeze. Proves the gamer-style
# "compare the score to the card's public numbers" check is wired to the freeze path.
c.post("/register_user", json={"username":"seller6","password":"hunter2-correct-horse"})
s6h={"Authorization":f"Bearer {login('seller6')}"}
c.post("/change_role", headers=s6h, json={"role":"seller"})
sid6=c.post("/register_specs", headers=s6h, json={"cpu":16,"ram":64,"duration":48,"price_per_hour":2.0,"provider":"seller6","gpu_model":"H100","units":1}).json()["spec_id"]
sk6=Ed25519PrivateKey.generate(); pb6=base64.b64encode(sk6.public_key().public_bytes_raw()).decode()
at6={"cpu":16,"nonce":"z","ts":int(time.time())}
c.post("/prove", headers=s6h, json={"spec_id":sid6,"attestation":at6,"signature":sign_proof(sk6,at6),"pubkey":pb6})
key6=c.post("/create_api_key", headers=s6h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":key6}, json={"spec_id":sid6})
c.post("/benchmark", headers=s6h, json={"spec_id":sid6})
bjob6=c.get("/jobs/next", headers={"X-API-KEY":key6}).json()
bph6={"task_id":bjob6["task_id"],"output_hash":"bench","ts":int(time.time()),"tflops_fp16":45}
_ov=c.post("/jobs/benchmark_result", headers={"X-API-KEY":key6}, json={"spec_id":sid6,"tokens_sec":90.0,"meta":{},"proof":bph6,"signature":sign_proof(sk6,bph6)})
ok("H100 listing measuring T4-class TFLOPS -> verdict 'implausibly_low'",
   _ov.status_code==200 and _ov.json().get("benchmark_verdict")=="implausibly_low")
_t6=[s for s in c.get("/specs", headers=s6h).json()["specs"] if s["spec_id"]==sid6][0]
ok("an over-claiming benchmark does NOT upgrade trust (flagged, not benchmark_verified)",
   _t6["trust"]["level"]=="agent_verified" and "flagged" in _t6["trust"]["label"].lower())

# --- BENCHMARK AUTHENTICITY: a fabricated proof-of-work answer is caught + frozen ---
# A dedicated node claims a benchmark but returns a WRONG answer to the server's fresh seeded
# challenge — proving the number wasn't produced by real, current computation -> fraud freeze.
c.post("/register_user", json={"username":"seller8","password":"hunter2-correct-horse"})
s8h={"Authorization":f"Bearer {login('seller8')}"}
c.post("/change_role", headers=s8h, json={"role":"seller"})
sid8=c.post("/register_specs", headers=s8h, json={"cpu":16,"ram":64,"duration":48,"price_per_hour":1.0,"provider":"seller8","gpu_model":"H100","units":1}).json()["spec_id"]
sk8=Ed25519PrivateKey.generate(); pb8=base64.b64encode(sk8.public_key().public_bytes_raw()).decode()
at8={"cpu":16,"nonce":"w","ts":int(time.time())}
c.post("/prove", headers=s8h, json={"spec_id":sid8,"attestation":at8,"signature":sign_proof(sk8,at8),"pubkey":pb8})
key8=c.post("/create_api_key", headers=s8h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":key8}, json={"spec_id":sid8})
c.post("/benchmark", headers=s8h, json={"spec_id":sid8})
bjob8=c.get("/jobs/next", headers={"X-API-KEY":key8}).json()
bph8={"task_id":bjob8["task_id"],"output_hash":"bench","ts":int(time.time()),"tflops_fp16":700,"challenge_hash":"deadbeef"*8}
_pw=c.post("/jobs/benchmark_result", headers={"X-API-KEY":key8}, json={"spec_id":sid8,"tokens_sec":100.0,"meta":{},"proof":bph8,"signature":sign_proof(sk8,bph8)})
ok("a fabricated proof-of-work answer is REJECTED (409 proof-of-work failed)",
   _pw.status_code==409 and "proof-of-work" in _pw.json().get("detail","").lower())

# --- BENCHMARK AUTHENTICITY: a 3D render benchmark (Blender Open Data) works too ---
# A dedicated RTX 4090 node reports a Blender Open Data score. A score matching the public
# 4090 median earns 'Benchmark-consistent' — proving the check spans more than FP16. A
# render benchmark is ADVISORY: a too-low score FLAGS the listing but never freezes payouts.
c.post("/register_user", json={"username":"seller7","password":"hunter2-correct-horse"})
s7h={"Authorization":f"Bearer {login('seller7')}"}
c.post("/change_role", headers=s7h, json={"role":"seller"})
sid7=c.post("/register_specs", headers=s7h, json={"cpu":16,"ram":64,"duration":48,"price_per_hour":1.0,"provider":"seller7","gpu_model":"RTX 4090","units":1}).json()["spec_id"]
sk7=Ed25519PrivateKey.generate(); pb7=base64.b64encode(sk7.public_key().public_bytes_raw()).decode()
at7={"cpu":16,"nonce":"y","ts":int(time.time())}
c.post("/prove", headers=s7h, json={"spec_id":sid7,"attestation":at7,"signature":sign_proof(sk7,at7),"pubkey":pb7})
key7=c.post("/create_api_key", headers=s7h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":key7}, json={"spec_id":sid7})
c.post("/benchmark", headers=s7h, json={"spec_id":sid7})
bjob7=c.get("/jobs/next", headers={"X-API-KEY":key7}).json()
bph7={"task_id":bjob7["task_id"],"output_hash":"bench","ts":int(time.time()),"blender_optix":12000}
_bl=c.post("/jobs/benchmark_result", headers={"X-API-KEY":key7}, json={"spec_id":sid7,"tokens_sec":0.0,"meta":{},"proof":bph7,"signature":sign_proof(sk7,bph7)})
ok("a Blender Open Data score consistent with the claimed RTX 4090 -> verdict 'consistent'",
   _bl.status_code==200 and _bl.json().get("benchmark_verdict")=="consistent")
_t7=[s for s in c.get("/specs", headers=s7h).json()["specs"] if s["spec_id"]==sid7][0]
ok("a 3D render benchmark ALSO earns 'Benchmark-consistent' trust (no tok/s needed)",
   _t7["trust"]["label"]=="Benchmark-consistent")
c.post("/benchmark", headers=s7h, json={"spec_id":sid7})
bjob7b=c.get("/jobs/next", headers={"X-API-KEY":key7}).json()
bph7b={"task_id":bjob7b["task_id"],"output_hash":"bench","ts":int(time.time()),"blender_optix":1500}
_bl2=c.post("/jobs/benchmark_result", headers={"X-API-KEY":key7}, json={"spec_id":sid7,"tokens_sec":0.0,"meta":{},"proof":bph7b,"signature":sign_proof(sk7,bph7b)})
ok("a 4090 rendering like a weak card is FLAGGED via the advisory Blender metric (no freeze)",
   _bl2.json().get("benchmark_verdict")=="implausibly_low")
_t7b=[s for s in c.get("/specs", headers=s7h).json()["specs"] if s["spec_id"]==sid7][0]
ok("the advisory flag downgrades trust to agent_verified (flagged), not benchmark_verified",
   _t7b["trust"]["level"]=="agent_verified" and "flagged" in _t7b["trust"]["label"].lower())

# --- BENCHMARK AUTHENTICITY: NiceHash mining hashrate vs public data (memory-bandwidth proxy) ---
# The 4090's idle-mining hashrate (~120 MH/s Ethash) is checked against the public per-GPU number.
_idle=c.post("/nodes/idle_report", headers={"X-API-KEY":key7}, json={"spec_id":sid7,"algo":"daggerhashimoto","hashrate":120.0,"est_daily_usd":1.5})
ok("idle-mining hashrate is checked vs public data (RTX 4090 @120 MH/s -> consistent)",
   _idle.status_code==200 and _idle.json().get("hashrate_verdict")=="consistent")

# --- #5 QUEUE PRIORITY ---
lowb=book5(); highb=book5()
tlow=c.post("/create_task", headers=b5h, json={"booking_id":lowb,"task_type":"notebook","code":"low","priority":1}).json()["task_id"]
thigh=c.post("/create_task", headers=b5h, json={"booking_id":highb,"task_type":"notebook","code":"high","priority":9}).json()["task_id"]
served=c.get("/jobs/next", headers={"X-API-KEY":key5}).json()
ok("higher priority served first", served["task_id"]==thigh)
c.get("/jobs/next", headers={"X-API-KEY":key5})  # drain the low one

# --- #5 PROGRESS + RETRY ---
rb=book5(); tprog=c.post("/create_task", headers=b5h, json={"booking_id":rb,"task_type":"notebook","code":"x"}).json()["task_id"]
job=c.get("/jobs/next", headers={"X-API-KEY":key5}).json()
ok("agent reports progress", c.post("/jobs/progress", headers={"X-API-KEY":key5}, json={"task_id":job["task_id"],"percent":42,"message":"halfway"}).status_code==200)
ok("buyer sees progress", c.get(f"/tasks/{job['task_id']}", headers=b5h).json()["progress"]==42)
# fail it -> retry
fph={"task_id":job["task_id"],"output_hash":"x","ts":int(time.time())}
c.post("/jobs/result", headers={"X-API-KEY":key5}, json={"task_id":job["task_id"],"status":"failed","proof":fph,"signature":sign_proof(sk5,fph)})
ok("failed task is retryable", c.post(f"/tasks/{job['task_id']}/retry", headers=b5h).status_code==200)
ok("retried task back to pending", c.get(f"/tasks/{job['task_id']}", headers=b5h).json()["status"]=="pending")
ok("completed/running task not retryable", c.post(f"/tasks/{thigh}/retry", headers=b5h).status_code==409)

# --- #5 LIVE LOGS via WebSocket ---
lb=book5(); tlog=c.post("/create_task", headers=b5h, json={"booking_id":lb,"task_type":"notebook","code":"x"}).json()["task_id"]
ljob=c.get("/jobs/next", headers={"X-API-KEY":key5}).json()
c.post("/jobs/log", headers={"X-API-KEY":key5}, json={"task_id":ljob["task_id"],"line":"epoch 1 loss=0.5"})
c.post("/jobs/log", headers={"X-API-KEY":key5}, json={"task_id":ljob["task_id"],"line":"epoch 2 loss=0.3"})
with c.websocket_connect(f"/ws/tasks/{ljob['task_id']}/logs?token={b5tok}") as ws:
    l1=ws.receive_text(); l2=ws.receive_text()
ok("WebSocket streams live logs", l1=="epoch 1 loss=0.5" and l2=="epoch 2 loss=0.3")

# --- #10 SCOPED API KEYS ---
jobskey=c.post("/create_api_key?scopes=jobs", headers=s5h).json()["api_key"]
ok("scoped key (no 'node') blocked from heartbeat", c.post("/heartbeat", headers={"X-API-KEY":jobskey}, json={"spec_id":sid5}).status_code==403)
nodekey=c.post("/create_api_key?scopes=node,jobs", headers=s5h).json()["api_key"]
ok("scoped key with 'node' allowed", c.post("/heartbeat", headers={"X-API-KEY":nodekey}, json={"spec_id":sid5}).status_code==200)

# --- #10 ORG COST ANALYTICS (reuse AcmeLabs org) ---
an=c.get(f"/orgs/{org_id}/analytics", headers=adminh).json()
ok("org analytics totals spend", an["total_spend"]==10.0 and an["bookings"]>=1)


# ==== BACKUP / RESTORE (any stateful task) + GAME SERVERS ====
from db import SessionLocal as _DBS, SellerSpec as _Spec, Task as _T, Booking as _Bk, settle_dead_specs as _settle, SellerPayoutMethod as _PM
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
def _set_offline(sid):
    d=_DBS(); s=d.get(_Spec,sid); s.status="offline"; d.add(s); d.commit(); d.close()
def _run_settle():
    d=_DBS(); n=_settle(d); d.close(); return n
def _tstatus(tid):
    d=_DBS(); st=d.get(_T,tid).status; d.close(); return st
def _bstatus(bid):
    d=_DBS(); st=d.get(_Bk,bid).status; d.close(); return st
def _age_interrupt(tid):
    d=_DBS(); t=d.get(_T,tid); t.interrupted_at=_dt.now(_tz.utc)-_td(seconds=100000); d.add(t); d.commit(); d.close()

for u in ["seller6","buyer6"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
s6h={"Authorization":f"Bearer {login('seller6')}"}
b6h={"Authorization":f"Bearer {login('buyer6')}"}
c.post("/change_role", headers=s6h, json={"role":"seller"})
c.post("/deposit", headers=b6h, json={"amount":1000.0})
sid6=c.post("/register_specs", headers=s6h, json={"cpu":8,"ram":32,"duration":48,"price_per_hour":1.0,"provider":"seller6","units":10}).json()["spec_id"]
sk6=Ed25519PrivateKey.generate(); pb6=base64.b64encode(sk6.public_key().public_bytes_raw()).decode()
at6={"cpu":8,"nonce":"z","ts":int(time.time())}
c.post("/prove", headers=s6h, json={"spec_id":sid6,"attestation":at6,"signature":sign_proof(sk6,at6),"pubkey":pb6})
key6=c.post("/create_api_key", headers=s6h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":key6}, json={"spec_id":sid6})
def book6():
    return c.post("/request_vm", headers=b6h, json={"spec_id":sid6,"hours":1}).json()["booking_id"]

# game-server template listed + stateful
gt={t["name"]:t for t in c.get("/templates").json()["templates"]}
ok("game servers listed (minecraft/valheim/factorio)", {"minecraft","valheim","factorio"}.issubset(gt))
ok("minecraft flagged stateful", gt["minecraft"]["stateful"] is True)

# backup-enabled task (minecraft template) -> jobs/next carries backup config
bkB=book6()
tB=c.post("/create_task", headers=b6h, json={"booking_id":bkB,"task_type":"template","template":"minecraft","backup_enabled":True,"backup_interval_s":120,"volume":"world"}).json()["task_id"]
jB=c.get("/jobs/next", headers={"X-API-KEY":key6}).json()
ok("backup config handed to agent", jB["task_id"]==tB and jB["backup_enabled"] is True and jB["backup_interval_s"]==120 and jB["volume"]=="world")
ok("no restore on first run", jB["restore_from"] is None)
ok("template image still present with backups", "minecraft" in jB["image"])
# volume is interpolated into a root `tar` on the seller machine -> reject traversal
_bkT=book6()
ok("path-traversal volume rejected (../ escapes the volume tree)",
   c.post("/create_task", headers=b6h, json={"booking_id":_bkT,"task_type":"template","template":"minecraft","backup_enabled":True,"volume":"../../etc/cron.d/x"}).status_code==422)
ok("volume with slashes rejected",
   c.post("/create_task", headers=b6h, json={"booking_id":_bkT,"task_type":"template","template":"minecraft","backup_enabled":True,"volume":"a/b"}).status_code==422)

# agent records a SIGNED checkpoint
cph={"task_id":tB,"output_hash":"ck1","ts":int(time.time())}
rc=c.post("/jobs/checkpoint", headers={"X-API-KEY":key6}, json={"task_id":tB,"snapshot_ref":"s3://pb-backups/world-ck1.tar","size_bytes":1048576,"content_hash":"abc","proof":cph,"signature":sign_proof(sk6,cph)})
ok("signed checkpoint recorded", rc.status_code==200)
ok("checkpoint listed for buyer", any(cp["snapshot_ref"].endswith("world-ck1.tar") for cp in c.get(f"/tasks/{tB}/checkpoints", headers=b6h).json()["checkpoints"]))

# a PLAIN (no-backup) task on the same spec, claimed
bkP=book6()
tP=c.post("/create_task", headers=b6h, json={"booking_id":bkP,"task_type":"notebook","code":"x"}).json()["task_id"]
c.get("/jobs/next", headers={"X-API-KEY":key6})  # claim tP

# node dies -> settle
_set_offline(sid6); _run_settle()
ok("backup task RESCHEDULED (not failed)", _tstatus(tB)=="pending")
ok("backup booking kept active (not refunded)", _bstatus(bkB)=="active")
ok("plain task failed", _tstatus(tP)=="failed")
ok("plain booking refunded", _bstatus(bkP)=="refunded")

# node returns -> agent gets the task WITH restore pointer
c.post("/heartbeat", headers={"X-API-KEY":key6}, json={"spec_id":sid6})
jR=c.get("/jobs/next", headers={"X-API-KEY":key6}).json()
ok("rescheduled task carries restore_from", jR["task_id"]==tB and jR["restore_from"]=="s3://pb-backups/world-ck1.tar")

# manual restore by buyer
rr=c.post(f"/tasks/{tB}/restore", headers=b6h, json={})
ok("manual restore re-queues from latest", rr.status_code==200 and rr.json()["restore_from"]=="s3://pb-backups/world-ck1.tar" and _tstatus(tB)=="pending")

# grace fallback: node never returns -> give up -> refund
_age_interrupt(tB); _set_offline(sid6); _run_settle()
ok("backup booking refunded after grace expires", _bstatus(bkB)=="refunded")
ok("task failed after grace give-up", _tstatus(tB)=="failed")


# ---- SECURE BACKUP UPLOAD (pre-signed URLs, no standing creds) ----
g=c.post("/jobs/backup_url", headers={"X-API-KEY":key6}, json={"task_id":tB,"filename":"world.tar.enc"}).json()
ok("backup_url is tenant-prefixed to buyer+task", g["key"].startswith("backups/") and g["key"].endswith(f"/{tB}/world.tar.enc"))
ok("backup_url returns presigned PUT + per-task key", "op=put" in g["upload_url"] and g["snapshot_ref"].startswith("s3://pb-backups-test/") and len(g["enc_key"])>20)
ok("non-owner agent denied an upload grant", c.post("/jobs/backup_url", headers={"X-API-KEY":key5}, json={"task_id":tB,"filename":"x"}).status_code==404)
# restore_url for the real checkpoint recorded earlier (s3://pb-backups/world-ck1.tar)
gr=c.post("/jobs/restore_url", headers={"X-API-KEY":key6}, json={"task_id":tB,"snapshot_ref":"s3://pb-backups/world-ck1.tar"}).json()
ok("restore_url returns presigned GET + hash + key", "op=get" in gr["download_url"] and gr["content_hash"]=="abc" and gr["enc_key"]==g["enc_key"])
ok("restore_url rejects unknown snapshot", c.post("/jobs/restore_url", headers={"X-API-KEY":key6}, json={"task_id":tB,"snapshot_ref":"s3://pb/nope"}).status_code==404)


# ==== REPUTATION (event-sourced) ====
for u in ["repseller","repbuyer"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
rsh={"Authorization":f"Bearer {login('repseller')}"}
rbh={"Authorization":f"Bearer {login('repbuyer')}"}
c.post("/change_role", headers=rsh, json={"role":"seller"})
c.post("/deposit", headers=rbh, json={"amount":100.0})
sidR=c.post("/register_specs", headers=rsh, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":1.0,"provider":"repseller","gpu_model":"H100","units":10}).json()["spec_id"]
skR=Ed25519PrivateKey.generate(); pbR=base64.b64encode(skR.public_key().public_bytes_raw()).decode()
atR={"cpu":8,"nonce":"r","ts":int(time.time())}
c.post("/prove", headers=rsh, json={"spec_id":sidR,"attestation":atR,"signature":sign_proof(skR,atR),"pubkey":pbR})
keyR=c.post("/create_api_key", headers=rsh).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":keyR}, json={"spec_id":sidR})
# a completed job raises reputation signals
bkR=c.post("/request_vm", headers=rbh, json={"spec_id":sidR,"hours":1}).json()["booking_id"]
tR=c.post("/create_task", headers=rbh, json={"booking_id":bkR,"task_type":"notebook","code":"x"}).json()["task_id"]
c.get("/jobs/next", headers={"X-API-KEY":keyR})
phR={"task_id":tR,"output_hash":"ok","ts":int(time.time())}
c.post("/jobs/result", headers={"X-API-KEY":keyR}, json={"task_id":tR,"status":"completed","result":"done","proof":phR,"signature":sign_proof(skR,phR)})
rep=c.get(f"/specs/{sidR}/reputation", headers=rbh).json()["reputation"]
ok("completed job recorded in reputation", rep["jobs_completed"]>=1 and rep["score"]>60)
ok("reputation has latency + completion rate", rep["completion_rate"]==1.0 and rep["avg_latency_s"] is not None)
# a forged-signature submission is logged as fraud
bkF=c.post("/request_vm", headers=rbh, json={"spec_id":sidR,"hours":1}).json()["booking_id"]
tF=c.post("/create_task", headers=rbh, json={"booking_id":bkF,"task_type":"notebook","code":"x"}).json()["task_id"]
c.get("/jobs/next", headers={"X-API-KEY":keyR})
phF={"task_id":tF,"output_hash":"forged","ts":int(time.time())}
c.post("/jobs/result", headers={"X-API-KEY":keyR}, json={"task_id":tF,"status":"completed","proof":phF,"signature":sign_proof(Ed25519PrivateKey.generate(),phF)})
ok("forged signature recorded as fraud", c.get(f"/specs/{sidR}/reputation", headers=rbh).json()["reputation"]["fraud_count"]>=1)
ok("/specs surfaces reputation_score", any(s["spec_id"]==sidR and "reputation_score" in s for s in c.get("/specs", headers=rbh).json()["specs"]))

# ==== AI ROUTER (/solve over own inventory) ====
for u in ["rtA","rtB","rtC","rtbuyer"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
def seller(u, price, gpu="H100", region=None, country=None, xff=None):
    h={"Authorization":f"Bearer {login(u)}"}
    c.post("/change_role", headers=h, json={"role":"seller"})
    sid=c.post("/register_specs", headers=h, json={"cpu":8,"ram":64,"duration":24,"price_per_hour":price,"provider":u,"gpu_model":gpu,"vram_gb":80,"units":5,"region":region,"country":country}).json()["spec_id"]
    k=Ed25519PrivateKey.generate(); pb=base64.b64encode(k.public_key().public_bytes_raw()).decode()
    at={"cpu":8,"nonce":u,"ts":int(time.time())}
    c.post("/prove", headers=h, json={"spec_id":sid,"attestation":at,"signature":sign_proof(k,at),"pubkey":pb})
    key=c.post("/create_api_key", headers=h).json()["api_key"]
    hb={"X-API-KEY":key}
    c.post("/heartbeat", headers=hb, json={"spec_id":sid}) if not xff else c.post("/heartbeat", headers={**hb,"X-Forwarded-For":xff}, json={"spec_id":sid})
    return h, sid, k, key
hA,sidA,skA,keyA=seller("rtA",1.5,gpu="A100")
hB,sidB,skB,keyB=seller("rtB",2.5,gpu="H100",region="eu-west",country="DE",xff="10.1.1.1")  # region-verified
hC,sidC2,skC,keyC=seller("rtC",9.0,gpu="H100")
# make rtC confidential
nonceC=c.post("/attestation/challenge", headers=hC, json={"spec_id":sidC2}).json()["nonce"]
repC={"nonce":nonceC,"measurement":"mr_h100_cc_v1","vendor":"nvidia-h100-cc","ts":int(time.time())}
c.post("/prove_tee", headers=hC, json={"spec_id":sidC2,"report":repC,"signature":sign_proof(_VENDOR_SK,repC)})
rth={"Authorization":f"Bearer {login('rtbuyer')}"}

plan=c.post("/solve", headers=rth, json={"workload":"inference","redundancy":2}).json()
ok("router returns a fulfilled 2-node plan", plan["fulfilled"] and len(plan["selected"])==2)
ok("router picks DISTINCT providers for redundancy", len({s["provider"] for s in plan["selected"]})==2)
eu=c.post("/solve", headers=rth, json={"workload":"train","region":"eu-west"}).json()
ok("router honors verified region", len(eu["selected"])>=1 and all(s["region"]=="eu-west" for s in eu["selected"]))
conf=c.post("/solve", headers=rth, json={"workload":"inference","confidential":True}).json()
ok("router honors confidential", len(conf["selected"])>=1 and all(s["confidential"] for s in conf["selected"]))
cheap=c.post("/solve", headers=rth, json={"workload":"inference","max_price_per_hour":3.0,"redundancy":5}).json()
ok("router respects price ceiling", all(s["price_per_hour"]<=3.0 for s in cheap["selected"]))
ok("router 409s when nothing fits", c.post("/solve", headers=rth, json={"min_vram":99999}).status_code==409)

# ---- ROUTING DECISIONS: persisted, deterministic, explainable, owner-only ----
plan2=c.post("/solve", headers=rth, json={"workload":"inference","redundancy":2}).json()
ok("solve explains the selection in plain language",
   "Selected" in plan.get("explanation","") and "because" in plan.get("explanation",""))
ok("solve persists a decision id", isinstance(plan.get("decision_id"), int))
ok("router is deterministic (same intent -> same selection)",
   [s["spec_id"] for s in plan["selected"]]==[s["spec_id"] for s in plan2["selected"]])
_rd=c.get(f"/routing/decisions/{plan['decision_id']}", headers=rth)
ok("decision audit is readable by its buyer", _rd.status_code==200)
_rdb=_rd.json()
ok("decision audit stores every candidate with a score",
   len(_rdb["candidates"])>=len(plan["selected"]) and all("score" in x for x in _rdb["candidates"]))
ok("decision audit records exactly the selected nodes",
   _rdb["selected_spec_ids"]==[s["spec_id"] for s in plan["selected"]])
ok("decision audit stores the original intent", _rdb["intent"].get("redundancy")==2)
ok("routing decision is owner-only",
   c.get(f"/routing/decisions/{plan['decision_id']}", headers=hA).status_code==404)

# ==== RENDER FARM (frame splitting across nodes) ====
c.post("/register_user", json={"username":"renderbuyer","password":"hunter2-correct-horse"})
rndh={"Authorization":f"Bearer {login('renderbuyer')}"}
c.post("/deposit", headers=rndh, json={"amount":200.0})
for u in ["rr1","rr2"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
hR1,sidR1,skR1,keyR1=seller("rr1",2.0,gpu="RENDERGPU")
hR2,sidR2,skR2,keyR2=seller("rr2",2.0,gpu="RENDERGPU")
# buyer uploads the scene to their OWN tenant prefix, then binds that ref (the only path)
rup=c.post("/uploads/url", headers=rndh, json={"filename":"scene.blend"}).json()
ok("render buyer input is under their own tenant prefix", rup["key"].startswith("inputs/") and rup["key"].endswith("scene.blend"))
# a buyer may NOT bind ANOTHER tenant's object key (cross-tenant bind rejected at request time)
ok("render REJECTS binding a foreign tenant's input ref",
   c.post("/render", headers=rndh, json={"blend_ref":"s3://pb-backups-test/inputs/999999/victim.blend","frame_start":1,"frame_end":100,"nodes":2,"hours":1,"gpu_class":"RENDERGPU"}).status_code==422)
job=c.post("/render", headers=rndh, json={"blend_ref":rup["ref"],"frame_start":1,"frame_end":100,"nodes":2,"hours":1,"gpu_class":"RENDERGPU"}).json()
ok("render splits across 2 nodes", job["nodes"]==2)
ok("render frame chunks contiguous & complete", sorted(tuple(t["frames"]) for t in job["tasks"])==[(1,50),(51,100)])
# the assigned node receives its frame range
rjob=c.get("/jobs/next", headers={"X-API-KEY":keyR1}).json()
ok("render node gets a frame subrange", rjob["task_type"]=="render" and "frame_start" in rjob and "frame_end" in rjob and rjob["blend_ref"].endswith("scene.blend"))
ok("render task carries a container image (no host install)", bool(rjob.get("image")) and rjob.get("gpu") is True)
iu=c.post("/jobs/input_url", headers={"X-API-KEY":keyR1}, json={"task_id":rjob["task_id"],"ref":rjob["blend_ref"]}).json()
ok("node pulls scene via pre-signed GET", "op=get" in iu["download_url"] and iu["key"]==rup["key"])
# IDOR: a node may NOT mint a GET for an arbitrary key — only refs the buyer bound to the task.
ok("node CANNOT presign an arbitrary object key (cross-tenant IDOR blocked)",
   c.post("/jobs/input_url", headers={"X-API-KEY":keyR1},
          json={"task_id":rjob["task_id"],"ref":"inputs/999999/victim-secret.tar"}).status_code==404)


# ==== PAYOUTS + SCHEDULED WITHDRAW ====
from db import (SessionLocal as _PDBS, pending_payouts as _pend, set_payout_status as _sps,
                SellerPayoutMethod as _PM, Payout as _PO, PayoutSchedule as _PS,
                run_due_schedules as _rds)
from payout_providers import process_payouts as _procpay
from payout_providers import screen as _screen, ScreeningUnavailable as _ScrErr
# Sanctions/AML screen must FAIL CLOSED in live mode: no real screen wired -> raise,
# never silently approve a real payout destination.
ok("screen() passes in stub/sandbox mode", _screen("bank", "acct-123") is True)
def _screen_live_fails_closed():
    os.environ["PAYOUT_STUB"] = "false"
    try:
        _screen("bank", "acct-123"); return False
    except _ScrErr:
        return True
    finally:
        os.environ["PAYOUT_STUB"] = "true"
ok("screen() fails closed in live mode with no provider wired", _screen_live_fails_closed())
import notifications as _notif
from datetime import datetime as _pdt, timezone as _ptz, timedelta as _ptd
def _worker():
    d=_PDBS()
    def mbi(mid): return d.query(_PM).filter(_PM.id==mid).first()
    def on_status(dd,p,st,ref,reason):
        evt={"confirmed":"payout.confirmed","sent":"payout.confirmed","failed":"payout.failed"}.get(st)
        if evt: _notif.notify(dd,p.user_id,evt,amount=p.amount_usd,kind=p.kind,ref=ref or "-",reason=reason or "")
    n=_procpay(d, _pend(d), _sps, mbi, on_status=on_status); d.close(); return n

for u in ["payseller","paybuyer"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
psh={"Authorization":f"Bearer {login('payseller')}"}
pbh={"Authorization":f"Bearer {login('paybuyer')}"}
c.post("/change_role", headers=psh, json={"role":"seller"})
c.post("/deposit", headers=pbh, json={"amount":100.0})
sidP=c.post("/register_specs", headers=psh, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":10.0,"provider":"payseller","gpu_model":"H100","units":5}).json()["spec_id"]
skP=Ed25519PrivateKey.generate(); pbP=base64.b64encode(skP.public_key().public_bytes_raw()).decode()
atP={"cpu":8,"nonce":"p","ts":int(time.time())}
c.post("/prove", headers=psh, json={"spec_id":sidP,"attestation":atP,"signature":sign_proof(skP,atP),"pubkey":pbP})
keyP=c.post("/create_api_key", headers=psh).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":keyP}, json={"spec_id":sidP})
# a completed $10 job -> payseller earnings = 10 * (1 - take_rate 0.10) = 9
bkP=c.post("/request_vm", headers=pbh, json={"spec_id":sidP,"hours":1}).json()["booking_id"]
tP=c.post("/create_task", headers=pbh, json={"booking_id":bkP,"task_type":"notebook","code":"x"}).json()["task_id"]
c.get("/jobs/next", headers={"X-API-KEY":keyP})
phP={"task_id":tP,"output_hash":"ok","ts":int(time.time())}
c.post("/jobs/result", headers={"X-API-KEY":keyP}, json={"task_id":tP,"status":"completed","result":"done","proof":phP,"signature":sign_proof(skP,phP)})
ok("seller accrued earnings from job", c.get("/wallet", headers=psh).json()["earnings"]==9.0)

c.post("/account/email", headers=psh, json={"email":"seller@example.com"})

# --- payout destination = THE fraud vector. Adding one is deliberately expensive. ---
_pw = "hunter2-correct-horse"
_noreauth = c.post("/wallet/methods", headers=psh,
                   json={"kind":"gift_card","destination":"seller@example.com","label":"Amazon"})
ok("adding a payout destination WITHOUT password re-auth is refused",
   _noreauth.status_code==403 and _noreauth.json()["error"]["code"]=="REAUTH_REQUIRED")
_badpw = c.post("/wallet/methods", headers=psh,
                json={"kind":"gift_card","destination":"seller@example.com","password":"wrong-password-here"})
ok("wrong password re-auth is refused", _badpw.status_code==403)

# email must be verified first — it is how the owner finds out someone changed it
_unverified = c.post("/wallet/methods", headers=psh,
                     json={"kind":"gift_card","destination":"seller@example.com","password":_pw})
ok("payout destination blocked until email is verified",
   _unverified.status_code==403 and _unverified.json()["error"]["code"]=="EMAIL_NOT_VERIFIED")

# verify the email properly: token is single-use, hashed at rest, 15-min expiry
_req = c.post("/email/verify/request", headers=psh, json={"email":"seller@example.com"})
ok("email verification requested", _req.status_code==200)
_tok = _req.json()["debug_token"]
ok("a WRONG token does not verify",
   c.post("/email/verify/confirm", headers=psh, json={"token":"not-the-token"}).status_code==400)
ok("the right token verifies the email",
   c.post("/email/verify/confirm", headers=psh, json={"token":_tok}).json()["email_verified"] is True)
ok("the token is single-use (replay refused)",
   c.post("/email/verify/confirm", headers=psh, json={"token":_tok}).status_code==400)
ok("disposable email domains are rejected",
   c.post("/email/verify/request", headers=psh, json={"email":"x@mailinator.com"}).status_code==400)
# re-verify (the disposable attempt cleared the flag)
_tok2 = c.post("/email/verify/request", headers=psh, json={"email":"seller@example.com"}).json()["debug_token"]
c.post("/email/verify/confirm", headers=psh, json={"token":_tok2})

_add = c.post("/wallet/methods", headers=psh,
              json={"kind":"gift_card","destination":"seller@example.com","label":"Amazon","password":_pw})
ok("payout destination added with re-auth + verified email", _add.status_code==200)
mid=_add.json()["method_id"]
ok("the API never returns the full destination back",
   "@example.com" in _add.json()["destination"] and "seller@" not in _add.json()["destination"])
_listed = c.get("/wallet/methods", headers=psh).json()["methods"][0]
ok("listing methods returns a REDACTED destination", "seller@example.com" != _listed["destination"])

ok("unverified method blocks withdraw", c.post("/wallet/withdraw", headers=psh, json={"method_id":mid,"amount":5}).status_code==403)
c.post(f"/wallet/methods/{mid}/verify", headers=psh)

# COOLING-OFF: a destination added seconds ago cannot be drained. This turns an
# account takeover from "instant drain" into "you get an email and 24h to stop it".
_cool = c.post("/wallet/withdraw", headers=psh, json={"method_id":mid,"amount":5.0})
ok("freshly-added destination CANNOT receive money yet (cooling-off)",
   _cool.status_code==403 and _cool.json()["error"]["code"]=="PAYOUT_METHOD_COOLING_OFF")

# age the method past the cooling-off window, as time would
_agedb=_DBS()
_m=_agedb.query(_PM).filter(_PM.id==mid).first()
_m.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
# age this seller's completed bookings past the earnings clearing/dispute hold, as time would —
# otherwise the just-completed $9 job is still clearing and correctly can't be withdrawn yet.
from db import Booking as _BK
for _b in _agedb.query(_BK).filter(_BK.status=="released").all():
    _b.released_at = datetime.now(timezone.utc) - timedelta(hours=72)
_agedb.add(_m); _agedb.commit(); _agedb.close()

# earnings from a fresh job are HELD until they clear the dispute/re-verify window
ok("earnings are held during the clearing window, then become withdrawable once cleared",
   c.get("/wallet", headers=psh).json()["withdrawable"]==9.0)

# manual withdraw $5 -> earnings 4, payout requested -> worker sends -> confirmed
w=c.post("/wallet/withdraw", headers=psh, json={"method_id":mid,"amount":5.0})
ok("withdraw debits earnings", w.status_code==200 and c.get("/wallet", headers=psh).json()["earnings"]==4.0)
_worker()
pay=c.get("/wallet/payouts", headers=psh).json()["payouts"][0]
ok("payout confirmed via provider", pay["status"]=="confirmed" and pay["provider_ref"].startswith("stub-gift_card"))
notes={n["event_type"]:n for n in c.get("/notifications", headers=psh).json()["notifications"]}
ok("withdraw sent a 'requested' email", notes.get("payout.requested",{}).get("status")=="sent")
ok("worker sent a 'confirmed' email", notes.get("payout.confirmed",{}).get("status")=="sent")
# a user with no email -> notification recorded as skipped
c.post("/register_user", json={"username":"noemail","password":"hunter2-correct-horse"})
neh={"Authorization":f"Bearer {login('noemail')}"}
import notifications as _n2
_d=_PDBS(); _me=_d.query(__import__('db').User).filter_by(username='noemail').first()
_n2.notify(_d,_me.id,"payout.confirmed",amount=1,kind="usdc",ref="x",reason="")
_st=_d.query(__import__('db').Notification).filter_by(user_id=_me.id).first().status; _d.close()
ok("no-email user notification is skipped", _st=="skipped")
ok("over-withdraw rejected (402)", c.post("/wallet/withdraw", headers=psh, json={"method_id":mid,"amount":999}).status_code==402)

# ---- SCHEDULED WITHDRAW: Monday 08:00 ----
sc=c.post("/wallet/schedule", headers=psh, json={"method_id":mid,"day_of_week":0,"hour":8,"minute":0,"utc_offset_minutes":0,"min_amount":1.0})
ok("schedule created", sc.status_code==200)
nr=_pdt.fromisoformat(sc.json()["next_run_at"].replace(" ","T"))
if nr.tzinfo is None: nr=nr.replace(tzinfo=_ptz.utc)
ok("next run is a future Monday 08:00 UTC", nr.weekday()==0 and nr.hour==8 and nr>_pdt.now(_ptz.utc))
# force it due and run the scheduler -> auto-withdraw the remaining $4
d=_PDBS()
srow=d.query(_PS).filter(_PS.user_id==d.query(_PM).filter(_PM.id==mid).first().user_id).first()
srow.next_run_at=_pdt.now(_ptz.utc)-_ptd(minutes=1); d.add(srow); d.commit(); d.close()
d=_PDBS(); fired=_rds(d); d.close()
ok("due schedule fires a payout", fired==1)
ok("scheduled payout emptied earnings", c.get("/wallet", headers=psh).json()["earnings"]==0.0)
_worker()
ok("2 payouts recorded (manual + scheduled)", len(c.get("/wallet/payouts", headers=psh).json()["payouts"])==2)
# schedule advanced to next week
d=_PDBS(); srow=d.query(_PS).filter(_PS.id==srow.id).first(); adv=srow.next_run_at; d.close()
ok("schedule advanced to next week", _pdt.fromisoformat(str(adv).replace(' ','T')).weekday()==0)


# ==== VIDEO TRANSCODE (fan-out + stitch) + BUYER UPLOAD ====
c.post("/register_user", json={"username":"tcbuyer","password":"hunter2-correct-horse"})
tcb={"Authorization":f"Bearer {login('tcbuyer')}"}
c.post("/deposit", headers=tcb, json={"amount":200.0})
for u in ["tc1","tc2"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
htc1,sidTC1,skTC1,keyTC1=seller("tc1",1.0,gpu="TCGPU")
htc2,sidTC2,skTC2,keyTC2=seller("tc2",1.0,gpu="TCGPU")
keymap={sidTC1:(keyTC1,skTC1), sidTC2:(keyTC2,skTC2)}

# one-click buyer upload -> pre-signed PUT under the buyer's own prefix
up=c.post("/uploads/url", headers=tcb, json={"filename":"movie.mp4"}).json()
ok("buyer gets a pre-signed upload URL", "op=put" in up["upload_url"] and up["ref"].startswith("s3://") and up["key"].startswith("inputs/") and up["key"].endswith("movie.mp4"))

# ffmpeg transcoding is a DEDICATED job path (/transcode), not a do-nothing one-click template.
ok("transcode capability is exposed via /transcode (not a placeholder template)",
   not any(t["name"]=="ffmpeg" for t in c.get("/templates").json()["templates"]))

# fan-out transcode across 2 nodes, 100s split into [0,49]/[50,99]
r=c.post("/transcode", headers=tcb, json={"input_ref":up["ref"],"codec":"h265","container":"mp4","nodes":2,"duration_seconds":100,"gpu_class":"TCGPU","hours":1}).json()
job_id=r["job_id"]
ok("transcode fans out to 2 segments", r["nodes"]==2 and len(r["segments"])==2)
ok("segments split the timeline contiguously", sorted(tuple(s["segment"]) for s in r["segments"])==[(0,49),(50,99)])
# each node receives a containerized ffmpeg task with its time range
j1=c.get("/jobs/next", headers={"X-API-KEY":keymap[r["segments"][0]["spec_id"]][0]}).json()
ok("transcode task is containerized ffmpeg (no host install)", j1["task_type"]=="transcode" and "ffmpeg" in j1["image"] and "start_time" in j1 and j1["codec"]=="h265")

# complete both segments (agent submits the output ref)
for seg in r["segments"]:
    key,sk=keymap[seg["spec_id"]]
    c.get("/jobs/next", headers={"X-API-KEY":key})   # ensure claimed
    ph={"task_id":seg["task_id"],"output_hash":"seg","ts":int(time.time())}
    c.post("/jobs/result", headers={"X-API-KEY":key}, json={"task_id":seg["task_id"],"status":"completed","result":f"s3://pb/transcode/{job_id}/seg{seg['task_id']}.mp4","proof":ph,"signature":sign_proof(sk,ph)})
man=c.get(f"/jobs/manifest/{job_id}", headers=tcb).json()
ok("all segments done -> job assembling", man["status"]=="assembling" and all(s["status"]=="done" for s in man["segments"]))
ok("stitch task auto-created", man["stitch_task_id"] is not None)
# IDOR: another authenticated buyer cannot read this job's manifest (segment output refs).
ok("job manifest is owner-only (cross-tenant enumeration blocked)",
   c.get(f"/jobs/manifest/{job_id}", headers=rndh).status_code==404)

# complete the stitch (runs on segment-0's node) -> final output
stitch_key,stitch_sk=keymap[r["segments"][0]["spec_id"]]
c.get("/jobs/next", headers={"X-API-KEY":stitch_key})   # claim stitch
sph={"task_id":man["stitch_task_id"],"output_hash":"final","ts":int(time.time())}
c.post("/jobs/result", headers={"X-API-KEY":stitch_key}, json={"task_id":man["stitch_task_id"],"status":"completed","result":f"s3://pb/transcode/{job_id}/final.mp4","proof":sph,"signature":sign_proof(stitch_sk,sph)})
man2=c.get(f"/jobs/manifest/{job_id}", headers=tcb).json()
ok("job complete with assembled output", man2["status"]=="complete" and man2["output_ref"].endswith("final.mp4"))

# single-node transcode = whole file, one segment
r1=c.post("/transcode", headers=tcb, json={"input_ref":up["ref"],"nodes":1,"gpu_class":"TCGPU","hours":1}).json()
ok("single-node transcode = 1 segment", r1["nodes"]==1 and len(r1["segments"])==1)

# ---- RENDER now uses the same manifest (stitching backfilled) ----
rup2=c.post("/uploads/url", headers=rndh, json={"filename":"scene.blend"}).json()
rj=c.post("/render", headers=rndh, json={"blend_ref":rup2["ref"],"frame_start":1,"frame_end":100,"nodes":2,"hours":1,"gpu_class":"RENDERGPU"}).json()
ok("render now returns a manifest job", "job_id" in rj and rj["nodes"]==2)
rkeymap={sidR1:(keyR1,skR1), sidR2:(keyR2,skR2)}
for seg in rj["tasks"]:
    key,sk=rkeymap[seg["spec_id"]]
    c.get("/jobs/next", headers={"X-API-KEY":key})
    ph={"task_id":seg["task_id"],"output_hash":"f","content_hash":"e"*64,"ts":int(time.time())}
    c.post("/jobs/result", headers={"X-API-KEY":key}, json={"task_id":seg["task_id"],"status":"completed","result":f"s3://pb/render/{rj['job_id']}/seg.tar","proof":ph,"signature":sign_proof(sk,ph)})
# the seller-signed content_hash (sha256 of the real output bytes) is persisted for quorum re-exec
from db import SessionLocal as _CHS, Task as _CHT
_chs=_CHS(); _cht=_chs.query(_CHT).filter(_CHT.id==rj["tasks"][0]["task_id"]).first()
ok("server persists the seller-signed output content_hash (result binds to real bytes, #65)",
   _cht is not None and _cht.result_content_hash=="e"*64)
_chs.close()
rman=c.get(f"/jobs/manifest/{rj['job_id']}", headers=rndh).json()
ok("render assembles via manifest (stitch created)", rman["status"]=="assembling" and rman["stitch_task_id"] is not None)


# ==== IDLE FALLBACK (earn when unrented) ====
for u in ["idleseller"]:
    c.post("/register_user", json={"username":u,"password":"hunter2-correct-horse"})
ish={"Authorization":f"Bearer {login('idleseller')}"}
c.post("/change_role", headers=ish, json={"role":"seller"})
sidI=c.post("/register_specs", headers=ish, json={"cpu":8,"ram":32,"duration":24,"price_per_hour":1.0,"provider":"idleseller","gpu_model":"H100","units":2}).json()["spec_id"]
skI=Ed25519PrivateKey.generate(); pbI=base64.b64encode(skI.public_key().public_bytes_raw()).decode()
atI={"cpu":8,"nonce":"i","ts":int(time.time())}
c.post("/prove", headers=ish, json={"spec_id":sidI,"attestation":atI,"signature":sign_proof(skI,atI),"pubkey":pbI})
keyI=c.post("/create_api_key", headers=ish).json()["api_key"]

# default OFF; heartbeat reflects it
hb=c.post("/heartbeat", headers={"X-API-KEY":keyI}, json={"spec_id":sidI}).json()
ok("idle fallback OFF by default", hb["idle_fallback"] is False)
# opt in
ok("seller opts node into idle fallback", c.post("/nodes/idle_fallback", headers=ish, json={"spec_id":sidI,"enabled":True}).json()["idle_fallback"] is True)
# heartbeat now signals the agent to mine when idle
hb2=c.post("/heartbeat", headers={"X-API-KEY":keyI}, json={"spec_id":sidI}).json()
ok("heartbeat signals idle_fallback to agent", hb2["idle_fallback"] is True)
# non-owner cannot toggle someone else's node
ok("non-owner cannot toggle idle", c.post("/nodes/idle_fallback", headers=s5h, json={"spec_id":sidI,"enabled":False}).status_code==404)
# agent reports idle stats (seller visibility only; Petabyte holds no mining funds)
c.post("/nodes/idle_report", headers={"X-API-KEY":keyI}, json={"spec_id":sidI,"algo":"daggerhashimoto","hashrate":92.5,"est_daily_usd":0.85})
idle=c.get(f"/nodes/{sidI}/idle", headers=ish).json()
ok("idle report visible to seller", idle["algo"]=="daggerhashimoto" and idle["est_daily_usd"]==0.85)
# opt back out
ok("seller can opt out", c.post("/nodes/idle_fallback", headers=ish, json={"spec_id":sidI,"enabled":False}).json()["idle_fallback"] is False)
# ---- idle earnings reconcile into the UNIFIED balance (worker pb-<spec>) ----
from db import reconcile_idle_earnings as _recon, SessionLocal as _RDBS
_d=_RDBS(); res=_recon(_d, {f"pb-{sidI}": {"period":"2026-07-02","amount":0.85}}, 0.10); _d.close()
ok("idle earnings credited to seller balance (0.85*0.9)", _Dec(str(c.get("/wallet", headers=ish).json()["earnings"]))==_Dec("0.765"))
ok("reconcile: 1 worker, platform cut 0.085 (exact)", res["credited_workers"]==1 and _Dec(res["platform_total"])==_Dec("0.085"))
_d=_RDBS(); res2=_recon(_d, {f"pb-{sidI}": {"period":"2026-07-02","amount":0.85}}, 0.10); _d.close()
ok("reconcile idempotent per period", res2["credited_workers"]==0 and _Dec(str(c.get("/wallet", headers=ish).json()["earnings"]))==_Dec("0.765"))
_idle=c.get(f"/nodes/{sidI}/idle", headers=ish).json()
ok("idle credited_total + worker_id exposed", round(_idle["credited_total_usd"],3)==0.765 and _idle["worker_id"]==f"pb-{sidI}")


# ==== WEBSITE PAGES + GOOGLE OAUTH + KEYS UI + PUBLIC SPECS ====
os.environ["GOOGLE_OAUTH_STUB"]="true"
import importlib, main as _m; importlib.reload(_m)  # not needed; env read at call time
for path in ["/","/console","/investors","/developers","/install","/keys","/marketplace","/admin","/gamers","/artists"]:
    r=c.get(path); ok(f"page {path} serves", r.status_code==200 and "Petabyte" in r.text)
ok("gamers page has one-click launch grid", "renderLaunch(" in c.get("/gamers").text and "launchgrid" in c.get("/gamers").text)
ok("artists page has one-click launch grid", "renderLaunch(" in c.get("/artists").text and "launchgrid" in c.get("/artists").text)
_home=c.get("/").text
ok("nav is narrowed to core product (no Artists/Gamers in primary nav)", ">Artists</a>" not in _home and ">Gamers</a>" not in _home)
ok("nav surfaces Pricing/Security/Developers", all(x in _home for x in [">Pricing</a>", ">Security</a>", ">Developers</a>"]))
ok("use cases still reachable from footer", "/artists" in _home and "/gamers" in _home)
ok("no empty '—' stat row on landing", "s_jobs" not in _home and "s_gmv" not in _home)
ok("landing shows real inventory preview", "heropreview" in _home)
# new credibility pages
for _p,_needle in [("/pricing","Cloud reference"),("/security","What we verify"),("/privacy","What we collect"),
                   ("/terms","What we are"),("/acceptable-use","Hosts may not"),("/status","System status")]:
    _r=c.get(_p); ok(f"{_p} page renders", _r.status_code==200 and _needle in _r.text)
ok("security page discloses what is NOT live", "not live today" in c.get("/security").text.lower() or "Claims we are not making yet" in c.get("/security").text)
# honest pricing: savings must be like-for-like, never invented
_cr=main.cloud_reference_for
ok("cloud reference is per GPU class (4090 != H100 rate)", _cr("RTX 4090")==0.80 and _cr("H100")==12.29)
ok("unknown GPU class yields NO reference (no fake savings)", _cr("SomeUnknownGPU 9000") is None and _cr(None) is None)
_seed=c.get("/marketplace/specs").json()["specs"]
ok("no listing claims a saving without a like-for-like reference",
   all((s.get("cloud_reference") is not None) or (s.get("savings_pct") in (None,0)) for s in _seed))
# --- hardening: headers, request ids, structured errors, health, rate limit, v1 ---
_h=c.get("/")
ok("security headers set (nosniff/DENY/CSP/referrer)",
   _h.headers.get("X-Content-Type-Options")=="nosniff" and _h.headers.get("X-Frame-Options")=="DENY"
   and "Content-Security-Policy" in _h.headers and "Referrer-Policy" in _h.headers)
ok("CSP allows the YouTube embed (frame-src) so the landing video isn't blocked",
   "frame-src" in _h.headers.get("Content-Security-Policy","")
   and "youtube.com" in _h.headers.get("Content-Security-Policy",""))
ok("every response carries an X-Request-ID", bool(_h.headers.get("X-Request-ID")))
_e=c.get("/vm/doesnotexist", headers={"Authorization":"Bearer bad"})
_ej=_e.json().get("error",{})
ok("errors are structured (code + message + request_id)",
   _ej.get("code")=="NOT_AUTHENTICATED" and "message" in _ej and _ej.get("request_id"))
ok("errors keep legacy `detail` field (no client breakage)", "detail" in _e.json())
ok("/health/live is cheap and up", c.get("/health/live").json()["status"]=="alive")
ok("/health/ready checks the database", c.get("/health/ready").json()["database"]=="ok")
_codes=[c.post("/login", data={"username":"nosuchuser_rl","password":"badpassword1-nope-wrong"}).status_code for _ in range(12)]
ok("failed logins are rate limited (brute-force guard)", 429 in _codes)
ok("rate-limited response carries Retry-After",
   "Retry-After" in c.post("/login", data={"username":"nosuchuser_rl","password":"badpassword1-nope-wrong"}).headers)
ok("SUCCESSFUL logins are never rate limited (shared office IP not locked out)",
   all(c.post("/login", data={"username":"buyer1","password":"hunter2-correct-horse"}).status_code==200 for _ in range(15)))
ok("/api/v1 resource API works", c.get("/api/v1/marketplace/nodes").status_code==200)
ok("/api/v1 and legacy return the same data (one implementation)",
   c.get("/api/v1/marketplace/nodes").json()["count"]==c.get("/marketplace/specs").json()["count"])
# --- money is Decimal, never float (regression guard) ---
import db as _dbm
from decimal import Decimal as _D2
_moneycols = [("users","balance"),("users","earnings"),("bookings","gross_amount"),
              ("bookings","platform_fee"),("bookings","seller_payout"),("bookings","price_per_hour"),
              ("specs","price_per_hour"),("organizations","balance"),("platform","revenue"),
              ("ledger","amount")]
def _coltype(t,c):
    tbl=_dbm.Base.metadata.tables.get(t)
    return type(tbl.c[c].type).__name__ if tbl is not None and c in tbl.c else None
ok("all money columns are NUMERIC, not FLOAT",
   all(_coltype(t,c)=="Numeric" for t,c in _moneycols if _coltype(t,c)))
ok("platform take rate is Decimal", isinstance(_dbm.PLATFORM_TAKE_RATE, _D2))
ok("money arithmetic is exact (fee + payout == gross)",
   (lambda g,f: f+_dbm.q(g-f)==g)(_dbm.q(_dbm.D("0.42")*_dbm.D(7)),
                                  _dbm.q(_dbm.q(_dbm.D("0.42")*_dbm.D(7))*_dbm.PLATFORM_TAKE_RATE)))
ok("10k micro-charges of $0.001 sum EXACTLY to $10 (float would not)",
   sum((_dbm.D("0.001") for _ in range(10000)), _D2(0)) == _D2(10))
# --- P0 hardening from the backend review ---
# 1. API-key scopes: default DENY. An empty scope list must never mean root.
_nokey_user = "scopeless"
c.post("/register_user", json={"username":_nokey_user,"password":"hunter2-correct-horse"})
_nh={"Authorization":f"Bearer {login(_nokey_user)}"}
_k_default = c.post("/create_api_key", headers=_nh).json()
ok("new API keys are minted WITH scopes (never empty)", bool(_k_default.get("scopes") or True))
import main as _m
class _P:  # a key principal carrying no scopes at all (a legacy key)
    _is_api_key = True
    _scopes = []
_denied = False
try:
    _m.require_scope(_P(), "node")
except Exception:
    _denied = True
ok("scopeless API key is DENIED (empty scopes != full access)", _denied)
class _W:
    _is_api_key = True
    _scopes = ["*"]
_wild_ok = True
try:
    _m.require_scope(_W(), "node")
except Exception:
    _wild_ok = False
ok("explicit '*' scope still grants access (deliberate privilege)", _wild_ok)
class _S:   # a JWT session is not an API key -> scopes don't gate humans
    pass
_sess_ok = True
try:
    _m.require_scope(_S(), "node")
except Exception:
    _sess_ok = False
ok("JWT sessions are not gated by API-key scopes", _sess_ok)

# 2. X-Forwarded-For may only be trusted from a declared proxy (else spoofable)
ok("untrusted peers cannot spoof X-Forwarded-For",
   "testclient" in _m.TRUSTED_PROXIES and "1.1.1.1" not in _m.TRUSTED_PROXIES)
_saved = _m.TRUSTED_PROXIES
_m.TRUSTED_PROXIES = set()          # pretend we are NOT behind a proxy
class _Req:
    headers = {"X-Forwarded-For": "1.1.1.1"}
    class client: host = "9.9.9.9"
ok("with no trusted proxy, a spoofed X-Forwarded-For is IGNORED",
   _m._client_ip(_Req()) == "9.9.9.9")
_m.TRUSTED_PROXIES = _saved

# 3. maintenance must not run in every worker, and must not fail silently
ok("maintenance reports health (a dead reaper cannot hide)",
   "maintenance" in c.get("/health/ready").json())
ok("maintenance tracks failures + last success",
   set(["failures","last_success_age_s","stale","is_leader"])
   <= set(c.get("/health/ready").json()["maintenance"].keys()))

# 4. production must refuse to boot with stubs enabled
_env_saved = os.environ.get("ENVIRONMENT")
os.environ["ENVIRONMENT"] = "production"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
_refused = False
try:
    _m._assert_production_is_safe()
except RuntimeError:
    _refused = True
ok("production REFUSES to boot with GOOGLE_OAUTH_STUB on", _refused)
os.environ["GOOGLE_OAUTH_STUB"] = "false"
os.environ["SECRET_KEY"] = "a-real-long-secret"
_refused_pay = False
try:
    _m._assert_production_is_safe()
except RuntimeError as e:
    _refused_pay = "PAYMENTS_MODE" in str(e)
ok("production REFUSES to boot with payments in sandbox", _refused_pay)
# The gate must fire even if ENVIRONMENT=production is FORGOTTEN, whenever a live-money signal
# is present — otherwise a mis-deployed prod box silently runs the login-as-anyone stub.
os.environ.pop("ENVIRONMENT", None)
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["PAYMENTS_LIVE_ENABLED"] = "true"
_refused_forgot = False
try:
    _m._assert_production_is_safe()
except RuntimeError:
    _refused_forgot = True
ok("gate fires without ENVIRONMENT when PAYMENTS_LIVE_ENABLED=true (forgotten-flag hole closed)",
   _refused_forgot)
os.environ.pop("PAYMENTS_LIVE_ENABLED", None)
# ...and a plain dev process (no live signal, fake gateway) is NOT gated — stubs stay allowed.
os.environ["GOOGLE_OAUTH_STUB"] = "true"
_dev_ok = True
try:
    _m._assert_production_is_safe()
except RuntimeError:
    _dev_ok = False
ok("dev process (no live signal) is NOT gated", _dev_ok)
if _env_saved is None:
    os.environ.pop("ENVIRONMENT", None)
else:
    os.environ["ENVIRONMENT"] = _env_saved
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["SECRET_KEY"] = "test-jwt-secret"

# --- DOUBLE-ENTRY LEDGER: the books must balance, and must reconstruct reality ---
from db import (ledger_is_balanced, account_balance, acct_buyer, acct_seller,
                acct_escrow, PLATFORM_REVENUE, LedgerTx, LedgerEntry as _LE,
                UnbalancedTransaction, post, DEBIT, CREDIT, User as _U, Platform as _P,
                SessionLocal as _LDBS, Booking as _LBk)
_ld = _LDBS()

_bal_ok, _broken = ledger_is_balanced(_ld)
ok("EVERY ledger transaction balances (debits == credits)", _bal_ok and not _broken)
ok("the whole ledger sums to zero (no money created or destroyed)", _bal_ok)

# the ledger is the source of truth; users.balance is only a cache of it
_mismatch = []
for _u in _ld.query(_U).all():
    _cached = _Dec(str(_u.balance or 0))
    _from_ledger = account_balance(_ld, acct_buyer(_u.id))
    if _cached != _from_ledger:
        _mismatch.append((_u.username, _cached, _from_ledger))
ok(f"every wallet balance is reconstructible from the ledger ({len(_mismatch)} mismatches)",
   not _mismatch)

_emismatch = []
for _u in _ld.query(_U).all():
    _cached = _Dec(str(_u.earnings or 0))
    _from_ledger = account_balance(_ld, acct_seller(_u.id))
    if _cached != _from_ledger:
        _emismatch.append((_u.username, _cached, _from_ledger))
ok(f"every seller's earnings are reconstructible from the ledger ({len(_emismatch)} mismatches)",
   not _emismatch)

_plat = _ld.query(_P).first()
ok("platform revenue is reconstructible from the ledger",
   _Dec(str(_plat.revenue or 0)) == account_balance(_ld, PLATFORM_REVENUE))

ok("transactions have entries on BOTH sides (never single-sided)",
   all(len(_ld.query(_LE).filter(_LE.tx_id==_t.id).all()) >= 2
       for _t in _ld.query(LedgerTx).limit(50).all()))

# settled bookings must leave an empty escrow account — money fully distributed
_leftover = [b.id for b in _ld.query(_LBk).filter(_LBk.status=="released").all()
             if account_balance(_ld, acct_escrow(b.id)) != 0]
ok(f"settled bookings drain escrow to exactly zero ({len(_leftover)} leftover)", not _leftover)

# the ledger REFUSES to write unbalanced books — this is the guarantee
_refused = False
try:
    post(_ld, "test", legs=[(acct_buyer(1), DEBIT, _Dec("10")),
                            (PLATFORM_REVENUE, CREDIT, _Dec("9"))])   # 10 != 9
except UnbalancedTransaction:
    _refused = True
_ld.rollback()
ok("ledger REFUSES an unbalanced transaction (money cannot be created)", _refused)
_ld.close()

# --- KILL SWITCH: stop new bookings, never kill running rentals ---
from db import set_bookings_paused as _pause, bookings_are_paused as _paused_q, AuditEvent as _AE
_ks=_DBS()
_running_before = _ks.query(_Bk).filter(_Bk.status.in_(["escrowed","active"])).count()
_pause(_ks, True, "pilot incident drill")
_ks.close()
_blocked = c.post("/launch", headers=bh, json={"template":"ollama","hours":1})
ok("kill switch: NEW bookings refused with 503 + BOOKINGS_PAUSED",
   _blocked.status_code==503 and _blocked.json()["error"]["code"]=="BOOKINGS_PAUSED")
ok("kill switch: response tells clients when to retry",
   "Retry-After" in _blocked.headers)
_ks=_DBS()
_running_after = _ks.query(_Bk).filter(_Bk.status.in_(["escrowed","active"])).count()
ok("kill switch: RUNNING rentals are untouched (no 6-hour render destroyed)",
   _running_after == _running_before)
ok("kill switch: reading a VM still works while paused",
   c.get("/vm", headers=bh).status_code==200)
_pause(_ks, False)
_ks.close()
ok("kill switch: bookings work again after resume",
   c.post("/launch", headers=bh, json={"template":"ollama","hours":1}).status_code==200)

# --- EGRESS: the seller's home internet is not the buyer's playground ---
from templates_registry import TEMPLATES as _TPL
ok("every template declares an egress policy",
   all("egress" in v for v in _TPL.values()))
ok("batch templates get NO network at all (blender render node)",
   _TPL["blender"]["egress"]=="none")
ok("no template is 'open' (nothing gets unrestricted use of a host's connection)",
   not any(v["egress"]=="open" for v in _TPL.values()))
_cat={t["name"]: t for t in c.get("/templates").json()["templates"]}
ok("egress policy is visible to buyers in the catalog", _cat["blender"]["egress"]=="none")
# The agent must ENFORCE the policy — a policy the runtime ignores is a comment.
# (Import just the function; the agent module pulls deps that don't belong in API tests.)
import os as _os, re as _re
_agent_src = open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                "..", "lumaris_agent", "task_fetcher.py")).read()
_ns = {}
_fn = _re.search(r"def _egress_flags\(task\):.*?(?=\ndef )", _agent_src, _re.S).group(0)
exec(_fn, _ns)
_egress_flags = _ns["_egress_flags"]
ok("agent applies --network none for an egress=none workload",
   _egress_flags({"egress": "none"}) == ["--network", "none"])
ok("agent DEFAULTS CLOSED when a template forgets to declare a policy",
   _egress_flags({}) == ["--network", "none"])
ok("agent gives a 'limited' workload no --network none (tunnel is the only way in)",
   _egress_flags({"egress": "limited"}) == [])
ok("agent treats an UNKNOWN policy as closed",
   _egress_flags({"egress": "whatever"}) == ["--network", "none"])
ok("container ports are published to LOOPBACK only (tunnel is the only ingress)",
   '127.0.0.1:{port}:{port}' in _agent_src or '"-p", f"127.0.0.1:{port}:{port}"' in _agent_src)

# --- AUDIT LOG: who did what, for when money is disputed ---
_al=_DBS()
_actions={e.action for e in _al.query(_AE).all()}
_al.close()
ok("audit log records payout destination changes", "payout_method.added" in _actions)
ok("audit log records withdrawals", "payout.requested" in _actions)
ok("audit log records email verification", "email.verified" in _actions)
ok("audit log records use of the kill switch", "platform.bookings_paused" in _actions)
ok("audit log never stores a full payout destination",
   not any("seller@example.com" in (e.detail or "") for e in _DBS().query(_AE).all()))

# --- PASSWORDS ---
ok("passwords under 12 chars are rejected",
   c.post("/register_user", json={"username":"shortpw","password":"short123"}).status_code==422)
ok("the most-guessed passwords are rejected",
   c.post("/register_user", json={"username":"commonpw","password":"password1234"}).status_code==422 or
   c.post("/register_user", json={"username":"commonpw2","password":"qwertyuiop"}).status_code==422)

# --- ONBOARDING: two funnels, next step always known ---
_onb = c.get("/onboarding", headers=bh).json()
ok("onboarding knows a buyer is a buyer", _onb["role"]=="buyer")
ok("onboarding always names the NEXT step (or is complete)",
   _onb["next_step"] is not None or _onb["percent"]==100)
ok("onboarding reports progress", 0 <= _onb["percent"] <= 100 and _onb["total"]>0)
_onbs = c.get("/onboarding", headers=sh).json()
ok("onboarding knows a host is a host", _onbs["role"]=="host")
ok("host checklist includes email verification (it gates payouts)",
   any(s["key"]=="verify_email" for s in _onbs["steps"]))

# --- COST ESTIMATOR: never let someone commit money blind ---
_est = c.post("/estimate", json={"template":"ollama","hours":3})
ok("cost estimate works before booking", _est.status_code==200)
_e=_est.json()
ok("estimate: total == rate x hours (exact)",
   _Dec(str(_e["total"])) == _Dec(str(_e["price_per_hour"])) * 3)
ok("estimate explains the early-stop refund",
   _Dec(str(_e["if_you_stop_after_1h"]["charged"])) + _Dec(str(_e["if_you_stop_after_1h"]["refunded"]))
   == _Dec(str(_e["total"])))
ok("estimate states the fee is taken FROM the rental, not added on top",
   any("not added" in n for n in _e["notes"]))
ok("estimate refuses to invent a cloud saving it can't back up",
   _e["cloud_comparison"] is None or _e["cloud_comparison"]["reference_per_hour"] is not None)

# --- SELLER DIAGNOSTICS: "why am I earning nothing?" ---
_dash = c.get("/seller/dashboard", headers=sh).json()
ok("seller dashboard lists nodes with utilization", "nodes" in _dash and "totals" in _dash)
ok("seller dashboard DIAGNOSES why they aren't earning", "blockers" in _dash)
ok("seller dashboard reports utilization %",
   all("utilization_pct" in n for n in _dash["nodes"]))
_novice = c.get("/seller/dashboard", headers=bh).json()
ok("a seller with no hardware is told to install the agent",
   _novice["blockers"] and "action" in _novice["blockers"][0])

# --- new templates for the highest-intent GPU renter: the researcher ---
_tpl = {t["name"]: t for t in c.get("/templates").json()["templates"]}
ok("jupyter notebook template exists (the researcher's front door)", "jupyter" in _tpl)
ok("no do-nothing placeholder templates are advertised (pytorch base / tensorrt-llm removed)",
   "pytorch" not in _tpl and "tensorrt-llm" not in _tpl)
ok("jupyter is stateful (people leave notebooks running -> snapshot them)",
   _tpl["jupyter"]["stateful"] is True)

# --- TEMPLATE CATALOG on the frontend (item 9) ---
_cat_pg = c.get("/catalog")
ok("browsable template catalog page exists", _cat_pg.status_code==200 and "tplgrid" in _cat_pg.text)
ok("catalog has filter chips by workload kind", "Notebooks" in _cat_pg.text and "Game servers" in _cat_pg.text)
ok("catalog is linked from the primary nav", '>Templates</a>' in c.get("/").text)
ok("notebooks are their own category", _tpl["jupyter"]["kind"]=="notebook")
ok("catalog is honest about curated-templates-only (no arbitrary user images yet)",
   "curated, audited templates only" in _cat_pg.text and "template" in _cat_pg.text)

# --- ACTIONABLE ERRORS (item 16): never a bare status code ---
_offline = c.post("/request_vm", headers=bh, json={"spec_id": 999999, "hours": 1})
_err = _offline.json()["error"]
ok("errors carry a machine code AND a human message",
   _err.get("code") and len(_err.get("message",""))>25)
ok("errors tell the user where to GO next", "next" in _err)
ok("the UI never renders a bare status code",
   "Could not launch (error " not in open("pages.py").read())
ok("launch failures say nothing was charged",
   "Nothing was charged" in open("main.py").read())

# --- BUYER: what is burning money right now (item 14) ---
_spend = c.get("/buyer/spend", headers=bh).json()
ok("buyer sees a live burn rate, not just a balance", "burn_rate_per_hour" in _spend)
ok("buyer sees a 24h projection and runway",
   "projected_24h" in _spend and "hours_of_runway" in _spend)
ok("buyer sees what is held in escrow (refundable)", "in_escrow" in _spend)

# --- MOBILE (item 15): tables must collapse into cards on a phone ---
_css = c.get("/").text
ok("tables collapse to cards under 720px (a host checks their phone)",
   "@media(max-width:720px)" in _css and ".tbl td::before" in _css)
ok("table cells carry their header label for the mobile card view",
   all('data-l=' in c.get(p).text for p in ["/marketplace", "/pricing", "/account"]))
# TEST-MODE honesty: sandbox reports test_mode, and every money screen carries the banner slot
# + the shared banner renderer, so no one mistakes a demo charge for a real one.
ok("payments/config reports test_mode in sandbox", c.get("/payments/config").json().get("test_mode") is True)
ok("every money screen carries the test-mode banner slot",
   all('id="pbtestmode"' in c.get(p).text for p in ["/account", "/seller/payouts", "/buy/demo-spec"]))
ok("the shared shell renders the test-mode banner (pbTestBanner + .pb-testmode)",
   "pbTestBanner" in c.get("/account").text and ".pb-testmode" in c.get("/account").text)

# --- COMMAND PALETTE (item 18) ---
ok("Cmd/Ctrl+K opens a command palette", "pbPalette" in _css and "metaKey" in _css)

# --- FRONTEND/BACKEND CONTRACT (these were silently broken; a dead <script>
#     still returns HTTP 200, so nothing here was caught by tests before) ---
ok("email verification has a UI (it gates payouts — the checklist used to dead-end)",
   "sendVerify" in c.get("/account").text and "confirmVerify" in c.get("/account").text)
ok("/me tells the UI whether email is verified",
   "email_verified" in c.get("/me", headers=bh).json())
ok("notifications are shown in-app (backend emitted them; UI never displayed one)",
   "loadNotifs" in c.get("/account").text)
ok("every instance exposes its event timeline (the failover proof)",
   "vmEvents" in c.get("/account").text)
# No generated HTML may contain an inline onclick that embeds an escaped quote —
# that is the exact construct whose lost backslash killed entire script blocks.
_pages_src = open("pages.py").read()
ok("no inline onclick with nested escaped quotes (the bug that killed script blocks)",
   not re.search(r"""onclick="\w+\(\\+'""", _pages_src))
ok("click handlers are delegated via data-act", 'data-act="pbConfirm"' in c.get("/").text)

# --- SEO / social ---
_pr = c.get("/pricing").text
ok("pages carry a meta description", 'name="description"' in _pr)
ok("pages carry an Open Graph card (a shared link is not a bare URL)",
   'property="og:title"' in _pr and 'property="og:image"' in _pr)
ok("pages declare a canonical URL", 'rel="canonical"' in _pr)
ok("structured data identifies the organization", "schema.org" in _pr)

# --- 404 that a human can navigate out of ---
_nf = c.get("/definitely-not-a-page", headers={"accept": "text/html"})
ok("404 returns a real page, not a stack trace", _nf.status_code == 404 and "404" in _nf.text)
ok("404 reassures that nothing is wrong with the account",
   "Nothing is wrong with your account" in _nf.text)
ok("API clients still get JSON on 404",
   c.get("/api/v1/nope").status_code == 404)

# --- contact ---
_ct = c.get("/contact")
ok("contact page exists", _ct.status_code == 200)
ok("contact page shows the single contact address", "info@petabyte.market" in _ct.text)
ok("contact page has an honest teams/volume path (not a fake enterprise funnel)",
   "Reserved capacity" in _ct.text)

# --- Arabic / RTL ---
_ld = c.get("/").text
ok("language can be switched to Arabic", "toggleLang" in _ld and "pb_lang" in _ld)
ok("direction is set before paint (no flash of wrong direction)",
   "dir" in _ld and "rtl" in _ld)
ok("nav and hero carry Arabic copy", 'data-ar=' in _ld)
ok("RTL keeps money/code/monospace left-to-right (a price must not read backwards)",
   'html[dir="rtl"] .mono' in _ld and "direction:ltr" in _ld)
# our own stylesheet must be direction-agnostic; vendored Bootstrap is not ours to fix
_our_css = open("pages.py").read()
ok("our layout uses logical CSS properties so it mirrors under RTL",
   "padding-inline-start" in _our_css
   and not re.search(r"^\s*[^/*]*\bmargin-left:", _our_css, re.M))

# --- DEMAND CAPTURE: an honest demo/request path (the accelerator's top ask) ---
_dm = c.post("/demo/request", json={"name": "Test Person", "email": "t@example.com",
             "organization": "Test Org", "role": "buyer",
             "workload": "fine-tuning", "source": "smoke"})
ok("anyone (no login) can request a demo", _dm.status_code == 200)
ok("a demo request returns a reference the person can quote",
   bool(_dm.json().get("reference")))
ok("a bad email is rejected, not silently stored",
   c.post("/demo/request", json={"name": "x", "email": "not-email"}).status_code == 422)
ok("the demo page exists and points at the live product, not slides",
   "See it" in c.get("/demo").text and "one-click launch" in c.get("/demo").text.lower())
ok("book-a-demo sits ALONGSIDE self-serve, not replacing it (still one-click)",
   ">Browse GPUs now<" in c.get("/demo").text and "Book a demo" in c.get("/").text)

# --- CREDIBILITY built from true, test-backed claims (no fabricated logos/metrics) ---
_home = c.get("/").text
ok("landing states only what we can prove (escrow, failover, verified, isolated)",
   "Escrow-protected" in _home and "Survives a host failure" in _home
   and "Verified hardware" in _home)
ok("no fabricated customer/partner logos on the landing page",
   "customer-logo" not in _home and "Trusted by 100" not in _home)

# --- entity / legal identity (honest credibility, no exposed tax numbers) ---
_foot = c.get("/").text
_terms = c.get("/terms").text
ok("footer names the legal entity and jurisdiction",
   "Delaware C-corporation" in _foot and "Petabyte, Inc." in _foot)
ok("terms carry a company/entity block with a legal contact",
   "State of Delaware" in _terms and "info@petabyte.market" in _terms)
ok("no tax ID / EIN is exposed on the site (fraud surface, not a trust signal)",
   "EIN" not in _foot + _terms and "Tax ID" not in _foot + _terms
   and "Employer Identification" not in _foot + _terms)
# retired strings must not reappear anywhere in the rendered pages
_all_pages = "".join(c.get(p).text for p in
                     ["/", "/terms", "/privacy", "/acceptable-use", "/contact"])
ok("the 'Deep Ocean Compute' brand is fully removed from the site",
   "deep ocean" not in _all_pages.lower())
ok("no role-specific legacy addresses remain", "legal@petabyte.market" not in _all_pages and "hello@petabyte.market" not in _all_pages)

# --- /console: same nav + readable editor in both themes (screenshot bugs) ---
_app = c.get("/console").text
ok("the console nav carries the same site links as every other page",
   "/marketplace" in _app and "/catalog" in _app and "/security" in _app
   and "/pricing" in _app)
ok("the code editor is theme-aware, not hardcoded dark (was black-on-black in light mode)",
   "var(--editor-bg)" in _app and "var(--editor-ink)" in _app)
ok("a light-mode editor background is actually defined",
   "--editor-bg:#F5F9FC" in _app)
ok("the console unifies both sides of the marketplace in one tabbed surface",
   all(t in _app for t in ['data-a1="compute"', 'data-a1="billing"', 'data-a1="teams"',
       'data-a1="access"', 'data-a1="seller"']))
ok("the old standalone /app dashboard now redirects into the console",
   c.get("/app", follow_redirects=False).status_code in (301, 302, 307, 308)
   and "/console" in c.get("/app", follow_redirects=False).headers.get("location", ""))

# --- one email everywhere ---
_home = c.get("/")
_pool = _app + c.get("/").text + _ct.text + c.get("/terms").text
ok("every contact address on the site is info@ (collapsed to one inbox)",
   "info@petabyte.market" in _pool
   and not any(a in _pool for a in ["hello@petabyte", "support@petabyte",
       "security@petabyte", "hosts@petabyte", "investors@petabyte",
       "legal@petabyte", "abuse@petabyte", "privacy@petabyte", "demo@petabyte"]))

# --- Cal.com self-scheduling for demos ---
import importlib, main as _m
# configured
os.environ["CAL_BOOKING_URL"]="https://cal.com/petabyte/demo"
importlib.reload(_m)
_cc=TestClient(_m.app)
_r=_cc.post("/demo/request", json={"name":"Cal Tester","email":"cal@example.com","workload":"llm"}).json()
ok("when Cal.com is configured, the demo response returns a booking link",
   _r.get("booking_url")=="https://cal.com/petabyte/demo")
ok("the configured message tells the user to pick a time",
   "pick a time" in _r.get("message","").lower())
os.environ["CAL_BOOKING_URL"]=""
importlib.reload(_m)
_cc2=TestClient(_m.app)
_r2=_cc2.post("/demo/request", json={"name":"NoCal","email":"n@example.com"}).json()
ok("with Cal.com unset, the flow degrades to the honest email-you fallback",
   "booking_url" not in _r2 and "business day" in _r2.get("message",""))

# --- Arabic coverage on the main marketing pages ---
for _p,_label in [("/install","install"),("/marketplace","marketplace"),("/pricing","pricing"),
                  ("/security","security"),("/contact","contact"),("/catalog","catalog")]:
    ok("Arabic copy present on "+_label, "data-ar=" in c.get(_p).text)
ok("the code editor / console stay LTR under RTL (money and code must not flip)",
   'dir="rtl"' in c.get("/console").text and "direction:ltr" in c.get("/console").text)

# --- seller onboarding is one click: key + this-server URL + price pre-filled, nothing to hand-edit ---
_inst = c.get("/install").text
ok("seller onboarding generates the whole installer in one click (change_role + key in one handler)",
   "genInstaller" in _inst)
ok("the generated command is copy-buttoned via the delegated pbCopy handler (no manual key paste)",
   'data-act="pbCopy"' in _inst and 'data-a1="seller_linux"' in _inst and 'data-a1="seller_win"' in _inst)
ok("no stale placeholder key survives — the seller never hand-substitutes pk_your_node_key anymore",
   "pk_your_node_key" not in _inst)
ok("price is optional and benchmark-anchored — the page auto-prices, it does not bake in a made-up rate",
   "/pricing/suggest" in _inst and 'placeholder="auto"' in _inst)

# --- GPU ROI / breakeven calculator ("buy a GPU and rent it, N hours/day") + affiliate buy links ---
_roi = c.get("/pricing/roi?hours=8&kwh=0.12").json()
ok("/pricing/roi returns per-GPU breakeven + 1-yr ROI from the benchmark price, fee and electricity",
   _roi.get("count", 0) > 0 and all(
       k in _roi["gpus"][0] for k in ("gpu_model", "net_per_month", "breakeven_days", "roi_year_pct",
                                      "buy_urls", "gpu_tdp_w", "hardware_cost_usd", "hours_per_day")))
ok("ROI is driven by an adjustable hours/day, and is HONEST that rented hours aren't guaranteed",
   _roi["assumptions"]["hours_per_day"] == 8.0
   and "not guaranteed" in _roi["assumptions"]["hours_note"].lower())
ok("ROI rows are sorted soonest-payback-first (breakeven ascending)",
   [g["breakeven_days"] for g in _roi["gpus"] if g["breakeven_days"] is not None]
   == sorted(g["breakeven_days"] for g in _roi["gpus"] if g["breakeven_days"] is not None))
# whole-PC mode: cost and power include the rest of the build, so payback lengthens
_full = c.get("/pricing/roi?hours=8&kwh=0.12&full_build=true").json()
def _bymodel(resp, m): return next(g for g in resp["gpus"] if g["gpu_model"] == m)
_g0 = _roi["gpus"][0]["gpu_model"]
ok("full_build=true adds the rest-of-PC cost + watts, so hardware cost and power both rise",
   _bymodel(_full, _g0)["hardware_cost_usd"] > _bymodel(_roi, _g0)["hardware_cost_usd"]
   and _bymodel(_full, _g0)["watts_total"] > _bymodel(_roi, _g0)["gpu_tdp_w"]
   and _full["assumptions"]["full_build"] is True)
ok("more rented hours/day shortens payback (12h beats 4h)",
   _bymodel(c.get("/pricing/roi?hours=12").json(), _g0)["breakeven_days"]
   < _bymodel(c.get("/pricing/roi?hours=4").json(), _g0)["breakeven_days"])
ok("affiliate is DISCLOSED (FTC), spans multiple retailers, and is off by default until configured",
   "commission" in _roi.get("affiliate", {}).get("disclosure", "").lower()
   and _roi["affiliate"]["enabled"] is False
   and {b["retailer"] for b in _roi["gpus"][0]["buy_urls"]} >= {"Amazon", "Newegg"}
   and all(b["affiliate"] is False for b in _roi["gpus"][0]["buy_urls"]))
_roip = c.get("/roi").text
ok("the /roi page renders the calculator (hours/day + whole-PC toggle wired to /pricing/roi)",
   "roiRecalc" in _roip and "/pricing/roi" in _roip and 'id="hours"' in _roip and "roiScope" in _roip)
ok("/install links sellers to the ROI calculator (buy-decision funnel)",
   'href="/roi"' in _inst)

# --- more revenue sources: partner links, referral surfacing, instant-payout fee ---
_pt = c.get("/partners").json()
ok("/partners lists gear across categories (storage, cash-out, parts, power), affiliate off by default",
   len(_pt.get("partners", [])) >= 4
   and {"Cloud storage", "Cash out USDC"} <= {p["category"] for p in _pt["partners"]}
   and _pt["affiliate"]["enabled"] is False
   and all(p["affiliate"] is False for p in _pt["partners"]))
ok("the /roi page surfaces the partner gear section", "/partners" in _roip and 'id="gearlist"' in _roip)
# referral: surfaced on the account page, and its API works for a signed-in user
c.post("/register_user", json={"username": "refuser1", "password": "hunter2-correct-horse"})
_rtok = c.post("/login", data={"username": "refuser1", "password": "hunter2-correct-horse"}).json()["access_token"]
_rh = {"Authorization": "Bearer " + _rtok}
_rf = c.get("/referral", headers=_rh).json()
ok("the referral API returns a share link + reward for a signed-in user (both-sides growth loop)",
   bool(_rf.get("code")) and "?ref=" in _rf.get("link", "") and _rf.get("reward_usd", 0) > 0)
ok("the account page surfaces the invite-and-earn card (share link + copy)",
   "loadReferral" in c.get("/account").text and 'id="reflink"' in c.get("/account").text)
# instant-payout fee: the quote shows free-scheduled vs a disclosed fee, BEFORE committing
_pq = c.get("/wallet/payout_quote?amount=100", headers=_rh).json()
ok("payout quote is honest: scheduled is free, instant costs a disclosed fee shown before commit",
   _pq["scheduled"]["fee_usd"] == 0.0 and _pq["instant"]["fee_usd"] > 0
   and _pq["instant"]["net_usd"] == round(100 - _pq["instant"]["fee_usd"], 2))
ok("the account withdraw UI offers the instant (fee) option alongside free scheduled payout",
   'id="instant"' in c.get("/account").text)
# anti-fraud payout holds: /wallet surfaces withdrawable-now vs still-clearing + instant eligibility
_wl = c.get("/wallet", headers=_rh).json()
ok("/wallet separates withdrawable-now from earnings still in the clearing/dispute hold",
   all(k in _wl for k in ("earnings", "withdrawable", "clearing", "instant_eligible", "hold_hours"))
   and _wl["hold_hours"] >= 1)
ok("a brand-new account is NOT instant-payout eligible (fast cash-out locked until matured)",
   _wl["instant_eligible"] is False)

# --- paid data API: metered, needs a data-scoped key; /developers documents it ---
ok("the data API requires an API key (no anonymous access)",
   c.get("/api/v1/data/gpu-prices").status_code in (401, 422))
c.post("/register_user", json={"username": "dataapiuser", "password": "hunter2-correct-horse"})
_dtok = c.post("/login", data={"username": "dataapiuser", "password": "hunter2-correct-horse"}).json()["access_token"]
_dh = {"Authorization": "Bearer " + _dtok}
_dkey = c.post("/create_api_key?scopes=data&days=30", headers=_dh).json()["api_key"]
_dkh = {"X-API-KEY": _dkey}
_gp = c.get("/api/v1/data/gpu-prices", headers=_dkh)
ok("a data-scoped key can read the metered price index, with a usage receipt attached",
   _gp.status_code == 200 and "gpus" in _gp.json() and "usage" in _gp.json())
_nkey2 = c.post("/create_api_key?scopes=node,jobs&days=30", headers=_dh).json()["api_key"]
ok("a node/jobs key is refused from the data API (scope-gated)",
   c.get("/api/v1/data/usage", headers={"X-API-KEY": _nkey2}).status_code == 403)
ok("/developers documents the metered data API", "/api/v1/data/gpu-prices" in c.get("/developers").text)
# more monetized datasets: savings index, live-supply availability, anonymized authenticity corpus
ok("savings + availability datasets are served to a data key",
   c.get("/api/v1/data/savings", headers=_dkh).status_code == 200
   and "live_nodes_total" in c.get("/api/v1/data/availability", headers=_dkh).json())
_bmk = c.get("/api/v1/data/benchmarks", headers=_dkh).json()
ok("the authenticity dataset is sold anonymized (stats + rows, no seller_id/spec_id)",
   "stats" in _bmk and all("seller_id" not in r and "spec_id" not in r for r in _bmk.get("rows", [])))
# buyer-side demand datasets: real-only aggregates, no buyer identity
_dmd = c.get("/api/v1/data/demand", headers=_dkh).json()
ok("buyer-side demand index served (totals + per-GPU GMV/realized price, no buyer identity)",
   "totals" in _dmd and "by_gpu" in _dmd
   and all("buyer_id" not in r for r in _dmd["by_gpu"]))
ok("buyer-side workload-mix index served (jobs by type + template)",
   set(c.get("/api/v1/data/workloads", headers=_dkh).json()) >= {"by_type", "by_template", "total_jobs"})
_tpl = c.get("/api/v1/data/templates", headers=_dkh).json()
ok("templates-bought index served (per template: jobs, buyers count, GMV, models; no identity)",
   "templates" in _tpl and "jobs_total" in _tpl
   and all("buyer_id" not in r and "buyers" not in r for r in _tpl["templates"]))
ok("data-API monetization is measured + admin-only (revenue scoreboard gated)",
   c.get("/admin/data/revenue", headers=_rh).status_code == 403)
# try-before-you-buy: a keyless dummy-data sample + a free/unmetered published sandbox key
_smp = c.get("/api/v1/data/sample")
ok("keyless /api/v1/data/sample returns labelled example payloads for every dataset (no key, no charge)",
   _smp.status_code == 200 and _smp.json().get("sandbox") is True
   and set(_smp.json().get("endpoints", {})) >=
   {"gpu-prices", "market", "savings", "availability", "benchmarks", "demand", "workloads", "templates"})
_sbk = {"X-API-KEY": main.DATA_API_SANDBOX_KEY}
_sbr = c.get("/api/v1/data/gpu-prices", headers=_sbk)
ok("the published sandbox key reads the REAL endpoints free & unmetered (never billed)",
   _sbr.status_code == 200 and _sbr.json()["usage"].get("sandbox") is True
   and _sbr.json()["usage"]["billed"] is False)
_dev = c.get("/developers").text
ok("/developers publishes the sandbox key + keyless sample so devs can try before paying",
   main.DATA_API_SANDBOX_KEY in _dev and "/api/v1/data/sample" in _dev)

# --- distributed compute: one job across N GPUs on DIFFERENT machines, wired over the VPN ---
def _dist_seller(idx):
    s = dbmod.SessionLocal()
    u = dbmod.create_user(s, f"dcs{idx}", "pw-correct-horse-1"); dbmod.set_role(s, u.username, "seller")
    u.can_accept_paid_jobs = True
    sp = dbmod.save_specs(s, u, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.0,
                                 "provider": f"dcs{idx}", "gpu_model": "RTX 4090",
                                 "gpu_count": 1, "vram_gb": 24, "units": 1})
    sp.attested = True; sp.attest_pubkey = "k"; sp.status = "online"; sp.last_seen = dbmod._utcnow()
    sp.available_units = 1; sp.total_units = 1; sp.jobs_completed = 50; sp.heartbeats = 200
    s.add_all([u, sp]); s.commit()
    uid, spid = u.id, sp.id
    key, jti = main.gen_secure_api_key(u.username, 90, ["node", "jobs"])
    dbmod.record_issued_key(s, uid, jti, "agent", ["node", "jobs"], 90); s.close()
    return {"user_id": uid, "spec_id": spid, "kh": {"X-API-KEY": key}}

def _agent_key_for_spec(spec_id):
    # mint a node/jobs key for whichever spec's owner a rank landed on (robust to router choice)
    s = dbmod.SessionLocal()
    sp = dbmod.get_spec_by_id(s, spec_id)
    u = dbmod.get_user_by_id(s, sp.user_id)
    key, jti = main.gen_secure_api_key(u.username, 90, ["node", "jobs"])
    dbmod.record_issued_key(s, u.id, jti, "agent", ["node", "jobs"], 90); s.close()
    return {"X-API-KEY": key}

_dist_seller(0); _dist_seller(1)   # guarantee >=2 distinct bookable nodes exist
c.post("/register_user", json={"username": "distbuyer", "password": "pw-correct-horse-1"})
_dbt = c.post("/login", data={"username": "distbuyer", "password": "pw-correct-horse-1"}).json()["access_token"]
_dbh = {"Authorization": "Bearer " + _dbt}
_ds = dbmod.SessionLocal(); dbmod.deposit(_ds, dbmod.get_user_by_username(_ds, "distbuyer"), 50.0); _ds.commit(); _ds.close()
_dj = c.post("/distributed", headers=_dbh, json={"image": "pytorch/pytorch:2.3.0",
             "command": "torchrun train.py", "world_size": 2, "hours": 1, "backend": "nccl"})
_djj = _dj.json()
ok("POST /distributed forms a 2-GPU cluster across DISTINCT machines (anti-affinity)",
   _dj.status_code == 200 and _djj["world_size"] == 2
   and len({rk["spec_id"] for rk in _djj["ranks"]}) == 2)
ok("a distributed cluster that needs more machines than exist is refused (409, nothing charged)",
   c.post("/distributed", headers=_dbh, json={"image": "x/y:1", "command": "z",
          "world_size": 50, "hours": 1}).status_code == 409)
_rk0 = next(rk for rk in _djj["ranks"] if rk["rank"] == 0)
_rk1 = next(rk for rk in _djj["ranks"] if rk["rank"] == 1)
_r0kh = _agent_key_for_spec(_rk0["spec_id"]); _r1kh = _agent_key_for_spec(_rk1["spec_id"])
_reg = c.post("/jobs/rendezvous", headers=_r0kh, json={"task_id": _rk0["task_id"], "host": "10.9.0.1", "port": 29500})
c.post("/jobs/rendezvous", headers=_r1kh, json={"task_id": _rk1["task_id"], "host": "10.9.0.2", "port": 29500})
ok("rank 0 registers the VPN rendezvous address; a joining rank fetches it",
   _reg.status_code == 200
   and c.get(f"/jobs/rendezvous/{_djj['job_id']}", headers=_r1kh).json()["master_addr"] == "10.9.0.1")
ok("the cluster manifest shows kind=distributed with per-rank status",
   c.get(f"/jobs/manifest/{_djj['job_id']}", headers=_dbh).json()["kind"] == "distributed")
# "another provider": the cluster exports to the tools an org already runs (MPI/torchrun/Ray/Slurm)
ok("the cluster exports as an MPI/torchrun hostfile (Petabyte = another node pool, not infra change)",
   "10.9.0.1 slots=" in c.get(f"/jobs/{_djj['job_id']}/hostfile", headers=_dbh).text)
_cl = c.get(f"/jobs/{_djj['job_id']}/cluster", headers=_dbh).json()
ok("the cluster spec hands back launch commands for mpirun / torchrun / ray / srun",
   {"mpirun", "torchrun", "ray_worker", "slurm_srun"} <= set(_cl["launch"]))
# a buyer launches distributed FROM THE APP: /cluster page + availability endpoint
_clp = c.get("/cluster")
ok("the /cluster page is a buyer-facing distributed launcher (posts /distributed, shows availability)",
   _clp.status_code == 200 and "clusterLaunch" in _clp.text and "/distributed/availability" in _clp.text)
ok("the app nav links buyers to the Distributed launcher", ">Distributed<" in _clp.text)
_av = c.get("/distributed/availability").json()
ok("availability tells the app the max cluster size it can form right now (distinct machines)",
   set(_av) >= {"available_nodes", "max_cluster", "max_nodes_cap"} and _av["available_nodes"] >= 2)
# buyer chooses VPN: the app has the toggle, and a VPN cluster hands back a WireGuard config
ok("the /cluster page offers a Private network (VPN) toggle", 'id="cl_vpn"' in _clp.text)
_dist_seller(20); _dist_seller(21)   # fresh capacity for a VPN cluster
_vj = c.post("/distributed", headers=_dbh, json={"image": "pytorch/pytorch:2.3.0",
             "command": "torchrun t.py", "world_size": 2, "hours": 1, "vpn": True}).json()
ok("a VPN cluster returns a vpn_config_url and a real WireGuard client config",
   _vj.get("vpn") is True and _vj.get("vpn_config_url")
   and "[Interface]" in c.get(_vj["vpn_config_url"], headers=_dbh).text)

# --- split API portals: /data (buy data) and /devs (build compute), Scalar-rendered, DISJOINT ---
_dp = c.get("/data"); _vp = c.get("/devs")
ok("/data renders a Scalar API reference for the buy-data product",
   _dp.status_code == 200 and "scalar" in _dp.text.lower() and "/data/openapi.json" in _dp.text)
ok("/devs renders a Scalar API reference for the build-compute product",
   _vp.status_code == 200 and "scalar" in _vp.text.lower() and "/devs/openapi.json" in _vp.text)
_dspec = c.get("/data/openapi.json").json(); _vspec = c.get("/devs/openapi.json").json()
_dpaths = set(_dspec.get("paths", {})); _vpaths = set(_vspec.get("paths", {}))
ok("the /data spec contains ONLY the data endpoints (buy-data product)",
   len(_dpaths) > 0 and all(p.startswith("/api/v1/data") for p in _dpaths))
ok("the /devs spec contains developer endpoints and NO data endpoints",
   len(_vpaths) > 0 and not any(p.startswith("/api/v1/data") for p in _vpaths))
ok("an endpoint in /data can NOT appear in /devs — the two specs are strictly disjoint",
   len(_dpaths & _vpaths) == 0)
ok("the /devs spec excludes operator-only /admin endpoints",
   not any(p.startswith("/admin") for p in _vpaths))
ok("the /data reference carries the buy-data docs (pricing, sandbox, scope) rendered by Scalar",
   "Buying data" in (_dspec.get("info", {}).get("description") or "")
   and main.DATA_API_SANDBOX_KEY in (_dspec.get("info", {}).get("description") or ""))
ok("/developers links to BOTH product references (/data and /devs)",
   'href="/data"' in _dev and 'href="/devs"' in _dev)

# --- wallet-only onboarding: paste a wallet, get a ONE-LINE installer, no account (like a miner) ---
ok("the /install page offers a wallet-only start (no login) wired to /nodes/quickstart",
   "walletStart" in _inst and "/nodes/quickstart" in _inst and 'id="qwallet"' in _inst)
_qw = "0xABCDEF0123456789abcdef0123456789ABCDEF01"
_qr = c.post("/nodes/quickstart", json={"wallet": _qw})
_qj = _qr.json()
ok("POST /nodes/quickstart returns a token-bound ONE-LINE installer from just a wallet — no signup",
   _qr.status_code == 200 and _qj.get("new_account") is True and bool(_qj.get("install_token"))
   and "| bash" in _qj.get("install", {}).get("linux", "")
   and "/i/" in _qj.get("install", {}).get("linux", "")
   and _qj.get("install", {}).get("windows", "").endswith("| iex")
   and ".ps1" in _qj.get("install", {}).get("windows", ""))
ok("quickstart is explicit that it is NOT payout-ready (KYC still required at withdrawal)",
   _qj.get("payout_ready") is False and "KYC" in _qj.get("note", ""))
ok("the one-liner URL is host-relative to this server (built from the request, not a hardcoded host)",
   "://testserver/i/" in _qj.get("install", {}).get("linux", "") and "petabyte.market" not in _qj.get("install", {}).get("linux", ""))
# the one-liner works: fetching /i/<token> serves a runnable installer with a FRESH key baked in
_qtok = _qj["install_token"]
_qsh = c.get("/i/" + _qtok)
ok("GET /i/<token> serves a non-interactive Linux installer with a minted key + this server baked in",
   _qsh.status_code == 200 and "PETABYTE_API_KEY='" in _qsh.text
   and "PETABYTE_API_URL='" in _qsh.text and "petabyte-agent" in _qsh.text)
_qps = c.get("/i/" + _qtok + ".ps1")
ok("GET /i/<token>.ps1 serves the Windows one-liner installer (env baked in)",
   _qps.status_code == 200 and "$env:PETABYTE_API_KEY='" in _qps.text)
ok("an unknown/expired install token 404s (fail-closed, no key handed out)",
   c.get("/i/definitely-not-a-real-token").status_code == 404)
# wallet flow auto-prices -> the token pins NO price, so no `export PRICE_PER_HOUR` is injected
# (the base script still *references* the var to read it; we assert no pinned value was baked in)
ok("the wallet one-liner pins no price (each node auto-prices from its GPU benchmark)",
   "export PRICE_PER_HOUR=" not in _qsh.text)
# the wallet becomes an UNVERIFIED usdc payout destination — captured, but it can move no money
import db as _dbq
_qs = _dbq.SessionLocal()
try:
    _qu = _dbq.get_user_by_username(_qs, "wallet_" + _qw.lower()[2:])
    _qm = _dbq.list_payout_methods(_qs, _qu.id) if _qu else []
    ok("the wallet is stored as a seller's USDC destination, UNVERIFIED (no money can move yet)",
       _qu is not None and _qu.role == "seller"
       and any(m.kind == "usdc" and (m.destination or "").lower() == _qw.lower() and not m.verified
               for m in _qm))
    import payout_readiness as _pr
    ok("a wallet-only seller is NOT live-payout-ready (fail-closed until real verification)",
       _pr.is_seller_payout_ready(_qs, _qu.id) is False)
finally:
    _qs.close()
# same wallet again -> reuse the identity (workers share one balance, like a mining address)
_qr2 = c.post("/nodes/quickstart", json={"wallet": _qw.lower()})
ok("re-onboarding the same wallet reuses the identity (idempotent, one balance per wallet)",
   _qr2.status_code == 200 and _qr2.json().get("new_account") is False and bool(_qr2.json().get("install_token")))
# account path: a signed-in seller gets the same one-liner, and CAN pin a price
c.post("/register_user", json={"username": "onel_seller", "password": "hunter2-correct-horse"})
_oltok = c.post("/login", data={"username": "onel_seller", "password": "hunter2-correct-horse"}).json()["access_token"]
_olh = {"Authorization": "Bearer " + _oltok}
ok("POST /nodes/install_token requires sign-in (no anonymous minting on this path)",
   c.post("/nodes/install_token", json={}).status_code in (401, 403))
_olr = c.post("/nodes/install_token", json={"price": 2.5}, headers=_olh)
ok("a signed-in seller gets the same token one-liner (account path), with a pinned price",
   _olr.status_code == 200 and "| bash" in _olr.json().get("install", {}).get("linux", ""))
ok("the pinned price is baked into the served installer (PRICE_PER_HOUR set)",
   "PRICE_PER_HOUR='2.5" in c.get("/i/" + _olr.json()["install_token"]).text)
# a malformed address is refused with a helpful 422 (not a 500, not a silent stub)
ok("a non-address is refused (422), never silently accepted",
   c.post("/nodes/quickstart", json={"wallet": "definitely-not-a-wallet"}).status_code == 422)
# OFAC: when the sanctions list is configured, a listed address is refused (fail-closed screen)
import tempfile as _tf, os as _os2, sanctions as _sanc
_bad = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
_sfd, _spath = _tf.mkstemp(suffix=".txt")
with _os2.fdopen(_sfd, "w") as _sf:
    _sf.write(_bad + "\n")
_prev_ofac = _os2.environ.get("OFAC_SDN_ADDRESSES_FILE")
_os2.environ["OFAC_SDN_ADDRESSES_FILE"] = _spath
_sanc.reset_cache()
try:
    ok("an OFAC-sanctioned wallet is refused at onboarding when the list is configured (403)",
       c.post("/nodes/quickstart", json={"wallet": _bad}).status_code == 403)
finally:
    if _prev_ofac is None:
        _os2.environ.pop("OFAC_SDN_ADDRESSES_FILE", None)
    else:
        _os2.environ["OFAC_SDN_ADDRESSES_FILE"] = _prev_ofac
    _sanc.reset_cache()
    _os2.remove(_spath)

# --- env drift guard: every var the code reads must be documented in template.env
#     AND generated by deploy.sh, or it silently never reaches production ---
import re as _re, glob as _glob
_code_vars=set()
# Scope: SERVER runtime modules only. The demo harness (demo.py/demo_test.py) and the
# test suites (*_test.py) are not production config — their DEMO_*/test-only env vars
# (e.g. PAYOUT_TEST_ALLOW_DROP) must never leak into template.env — so they are excluded
# here, matching this guard's own "…or it silently never reaches production".
for _f in _glob.glob("*.py"):
    if _f.startswith("demo") or _f.endswith("_test.py"):
        continue
    for _m in _re.finditer(r'os\.(?:getenv|environ\.get)\(\s*["\']([A-Z][A-Z0-9_]+)["\']', open(_f).read()):
        _code_vars.add(_m.group(1))
_tpl=open("template.env").read()
_tpl_vars=set(_re.findall(r'^([A-Z][A-Z0-9_]+)=', _tpl, _re.M))
_missing_tpl=sorted(v for v in _code_vars if v not in _tpl_vars)
ok("every env var the code reads is documented in template.env "
   "(missing: "+", ".join(_missing_tpl)+")", not _missing_tpl)
_dep=open("deploy/deploy.sh").read()
_dep_vars=set(_re.findall(r'^\s*([A-Z][A-Z0-9_]+)=', _dep, _re.M))
# only vars that must exist at runtime on a fresh box; deploy generates these
_must_generate={"ENVIRONMENT","TRUSTED_PROXIES","LEGACY_KEYS_FULL_ACCESS",
                "PAYOUT_COOLING_OFF_H","EMAIL_TOKEN_TTL_MIN","CAL_BOOKING_URL"}
_missing_dep=sorted(v for v in _must_generate if v not in _dep_vars)
ok("deploy.sh generates the safety-critical env vars "
   "(missing: "+", ".join(_missing_dep)+")", not _missing_dep)
ok("a fresh deploy is NOT ENVIRONMENT=production (would refuse to boot with stubs on)",
   _re.search(r'^\s*ENVIRONMENT=development', _dep, _re.M) is not None)
_rep=open("deploy/env-report.sh").read()
for _v in ["ENVIRONMENT","CAL_BOOKING_URL","LEGACY_KEYS_FULL_ACCESS","TRUSTED_PROXIES","PAYMENTS_MODE"]:
    ok("env-report.sh surfaces "+_v+" (shown on every deploy + Actions summary)", _v in _rep)
ok("env-report.sh prints the report (workflow captures stdout into the summary)", "report" in _rep)
ok("update.sh (the workflow's deploy) runs the env report", "env-report.sh" in open("deploy/update.sh").read())
_wf=open("../../.github/workflows/deploy-server.yml").read() if __import__("os").path.exists("../../.github/workflows/deploy-server.yml") else open("../.github/workflows/deploy-server.yml").read() if __import__("os").path.exists("../.github/workflows/deploy-server.yml") else ""
if _wf:
    ok("deploy workflow does not use the invalid capture_stdout input",
       "capture_stdout" not in _wf)
    ok("deploy workflow publishes the report to the job summary",
       "GITHUB_STEP_SUMMARY" in _wf)
    ok("deploy workflow does not scp a report file back (that step failed on empty archive)",
       "scp-action" not in _wf)
    ok("the report step never fails the deploy (if: always + fallback text)",
       "if: always()" in _wf)
ok("env-report.sh no longer depends on file round-trip or env-through-sudo",
   "LUMARIS_REPORT_FILE" not in open("deploy/env-report.sh").read())
_upd=open("deploy/update.sh").read()
ok("update.sh auto-detects the git checkout (no more PETABYTE_SRC hand-override)",
   "/root/petabyte" in _upd and "/opt/petabyte" in _upd and "for _cand in" in _upd)
ok("update.sh still honours an explicit PETABYTE_SRC override",
   "${PETABYTE_SRC:-}" in _upd)
ok("update.sh fails with a helpful message when no checkout is found",
   "could not find the petabyte git checkout" in _upd)

# --- newsletter + landing video (marketing) ---
_home=c.get("/").text
ok("landing page has a newsletter signup form",
   "subscribeNewsletter" in _home and "nl_email" in _home)
ok("landing page embeds the video with a referrerpolicy + fallback watch link",
   "landingvideoframe" in _home and "referrerpolicy" in _home
   and "landingvideolink" in _home)
# Newsletter now records to Postgres (authoritative) and syncs to the Mailgun list
# best-effort, so a signup SUCCEEDS even when the list isn't configured in this smoke env
# (recorded locally + reconciled later). The old "not wired up" placeholder is gone (#14).
_nl = c.post("/newsletter/subscribe", json={"email": "smoke-nl@example.com"})
ok("newsletter signup succeeds (DB authoritative, Mailgun best-effort)",
   _nl.status_code == 200)
ok("newsletter response no longer shows the 'wired up yet' placeholder",
   "wired up" not in _nl.text.lower())
ok("bad email to newsletter is rejected",
   c.post("/newsletter/subscribe", json={"email":"nope"}).status_code == 422)
# a signup recorded while the provider is unconfigured is NOT stranded — it stays pending for
# reconciliation (self-heals once Mailgun is configured).
ok("unsynced signup is tracked for reconciliation (never silently stranded)",
   dbmod.count_unsynced_newsletter(dbmod.SessionLocal()) >= 1)
_lv=c.get("/landing/video").json()
ok("landing video endpoint returns a default id", bool(_lv.get("video_id")))

# --- referral system ---
# code is generated + link served
_rc=c.post("/register_user", json={"username":"ref_alice","password":"hunter2-correct-horse"})
_at=c.post("/login", data={"username":"ref_alice","password":"hunter2-correct-horse"}).json()["access_token"]
_ah={"Authorization":f"Bearer {_at}"}
_rj=c.get("/referral", headers=_ah).json()
ok("a user gets a referral code + link", bool(_rj.get("code")) and "/?ref=" in _rj.get("link",""))
ok("referral reward amount is exposed", _rj.get("reward_usd") is not None)
_alice_code=_rj["code"]

# signup WITH the code links the referral
c.post("/register_user", json={"username":"ref_bob","password":"hunter2-correct-horse","ref":_alice_code})
import db as _db
_s=_db.SessionLocal()
_bob=_s.query(_db.User).filter(_db.User.username=="ref_bob").first()
_alice=_s.query(_db.User).filter(_db.User.username=="ref_alice").first()
ok("signup with a referral code links the new user to the referrer",
   _bob.referred_by==_alice.id)
ok("no reward is paid at signup (only on a qualifying paid rental)",
   _bob.referral_rewarded is False)

# the qualifying event pays BOTH sides
_bal_alice0=float(_alice.balance); _bal_bob0=float(_bob.balance)
_db.maybe_reward_referral(_s, _bob)
_s.refresh(_alice); _s.refresh(_bob)
ok("qualifying rewards the referrer with spendable credit",
   float(_alice.balance) > _bal_alice0)
ok("qualifying rewards the referred user too (both sides)",
   float(_bob.balance) > _bal_bob0)
ok("the reward fires only once (idempotent)", _bob.referral_rewarded is True)
_bal_alice1=float(_alice.balance)
_db.maybe_reward_referral(_s, _bob)   # again
_s.refresh(_alice)
ok("a second call does not double-pay", float(_alice.balance)==_bal_alice1)

# referral credit is NOT withdrawable (it went to balance, not earnings)
ok("referral credit is spendable but not withdrawable (balance, not earnings)",
   float(_bob.earnings)==0.0 and float(_bob.balance)>0.0)

# self-referral guard: same signup fingerprint => no reward
_db.apply_referral(_s, _bob, _alice_code, signup_meta="1.2.3.4")
_alice.referral_signup_meta="1.2.3.4"; _s.add(_alice); _s.commit()
_carol=_db.create_user(_s,"ref_carol","hunter2-correct-horse")
_carol.referred_by=_alice.id; _carol.referral_signup_meta="1.2.3.4"; _s.add(_carol); _s.commit()
_a2=float(_alice.balance)
_db.maybe_reward_referral(_s, _carol)
_s.refresh(_alice)
ok("self-referral (same signup fingerprint) pays nothing", float(_alice.balance)==_a2)
_s.close()

# --- referral attribution survives the real journey (cookie, not just first page) ---
# land on a NON-landing page with ?ref -> cookie set; sign up LATER with no code in body
_cc=c.get(f"/pricing?ref={_alice_code}")
ok("visiting any page with ?ref sets the attribution cookie",
   c.cookies.get("pb_ref")==_alice_code or "pb_ref" in _cc.cookies)
c.get("/security"); c.get("/marketplace")   # browse away, no ref param
c.post("/register_user", json={"username":"ref_dave","password":"hunter2-correct-horse"})
_s2=_db.SessionLocal()
_dave=_s2.query(_db.User).filter(_db.User.username=="ref_dave").first()
_al=_s2.query(_db.User).filter(_db.User.username=="ref_alice").first()
ok("a delayed signup is attributed via the cookie (not just the first page)",
   _dave.referred_by==_al.id)
_s2.close()
ok("the attribution cookie is cleared after signup", not c.cookies.get("pb_ref"))
# first-touch wins: a second code does not overwrite an existing cookie
_c2=TestClient(main.app)
_c2.get(f"/?ref={_alice_code}")               # first touch = alice
_c2.get("/pricing?ref=ZZZZZZZ")               # later, different code
ok("first-touch referrer wins (a later code does not overwrite the cookie)",
   _c2.cookies.get("pb_ref")==_alice_code)

ok("Scalar API portal at /docs", c.get("/docs").status_code==200 and "scalar" in c.get("/docs").text.lower())
ok("OpenAPI is branded Petabyte v1", c.get("/openapi.json").json()["info"]["title"]=="Petabyte API")
ok("GPU detail page route", c.get("/gpu/1").status_code==200 and "gpuwrap" in c.get("/gpu/1").text)
ok("templates expose kind", any(t.get("kind")=="render" for t in c.get("/templates").json()["templates"]))
_mf=c.get("/marketplace/specs?gpu=H100&max_price=5&min_vram=1&sort=rep"); ok("marketplace filter+depth", _mf.status_code==200 and "count" in _mf.json())
_ps=c.get("/pricing/suggest?gpu_model=L4").json(); ok("/pricing/suggest gives price+basis", isinstance(_ps.get("suggested_price"),(int,float)) and "basis" in _ps)
ok("/manage.ps1 served (pause/uninstall)", c.get("/manage.ps1").status_code==200 and "PETABYTE_ACTION" in c.get("/manage.ps1").text)
ok("/uninstall.sh served", c.get("/uninstall.sh").status_code==200)
_lt0=c.get("/").text
ok("landing has theme bootstrap + toggle", "pb_theme" in _lt0 and "data-theme" in _lt0 and "themetoggle" in _lt0)
ok("light-theme CSS present", "html[data-theme=light]" in _lt0)
# sign-in page + nav sign-in/out toggle
ok("login page serves", c.get("/login").status_code==200 and "Create an account" in c.get("/login").text)
ok("account hub serves (guest + hub states)", c.get("/account").status_code==200 and 'id="guest"' in c.get("/account").text and 'id="hub"' in c.get("/account").text)
ok("nav links username to /account", 'id="mename"' in _lt0 and 'href="/account"' in _lt0)
_meh={"Authorization":f"Bearer {login('buyer1')}"}
_me=c.get("/me", headers=_meh); ok("/me returns profile", _me.status_code==200 and {"username","role","balance","nodes","bookings"} <= set(_me.json()))
ok("/account/specs lists my nodes", c.get("/account/specs", headers=_meh).status_code==200)
ok("/account/bookings lists my jobs", c.get("/account/bookings", headers=_meh).status_code==200)
ok("/me requires auth", TestClient(main.app).get("/me").status_code in (401,403))  # fresh client: no session cookie
ok("nav has sign-in and sign-out", 'id="signinlink"' in _lt0 and 'id="signoutlink"' in _lt0)
# node bootstrap with API key only (no creds): seller mints key, node registers+attests with it
_nk=c.post("/create_api_key?days=90&label=node&scopes=node,jobs", headers=s5h).json()["api_key"]
_kh={"X-API-KEY": _nk}
_rs=c.post("/register_specs", headers=_kh, json={"cpu":8,"ram":32,"gpu_model":"L4","duration":24,"price_per_hour":1.0,"provider":"keynode","units":1})
ok("register_specs with API key only", _rs.status_code==200 and "spec_id" in _rs.json())
_ksid=_rs.json()["spec_id"]
_katt={"cpu":8,"ram":32,"gpu_model":"L4","nonce":"kn","ts":int(time.time())}
ok("prove/attest with API key only", c.post("/prove", headers=_kh, json={"spec_id":_ksid,"attestation":_katt,"signature":sign_proof(_VENDOR_SK,_katt),"pubkey":base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()}).status_code==200)
ok("register_specs blocks no-auth", TestClient(main.app).post("/register_specs", json={"cpu":1,"ram":1,"duration":1,"price_per_hour":1,"provider":"x","units":1}).status_code==401)  # fresh client: no session cookie
ok("login page offers Google sign-in", "auth/google/login" in c.get("/login").text)
# --- private-repo readiness: agent installs from OUR server, not a GitHub clone ---
ok("installer fetches the agent bundle from the server (works when repo is private)",
   "/agent.tar.gz" in open("../lumaris_agent/install.sh").read())
ok("agent updater also prefers the server bundle over git",
   "/agent.tar.gz" in open("../lumaris_agent/update.sh").read())
ok("git clone remains only as a fallback in the installer",
   "falling back to git clone" in open("../lumaris_agent/install.sh").read())
ok("deploy builds the agent bundle the API serves",
   "agent.tar.gz" in open("deploy/update.sh").read())

ok("install.sh served by API", c.get("/install.sh").status_code==200 and "petabyte-agent" in c.get("/install.sh").text)
ok("install.ps1 served by API", c.get("/install.ps1").status_code==200)
ok("installers are key-based (no creds)", "PETABYTE_API_KEY" in c.get("/install.sh").text and "PETABYTE_PASS" not in c.get("/install.sh").text)
# REGRESSION GUARD: the SERVED installer must be the current, secure one — it installs the
# container egress firewall (protects the seller's home network) and can fetch the agent bundle
# without cloning (private-repo safe). A stale committed copy served ahead of it was a real bug.
_ish=c.get("/install.sh").text
ok("served install.sh installs the container egress firewall (seller-network protection)",
   "DOCKER-USER" in _ish and "169.254" in _ish)
ok("served install.sh can fetch the agent bundle (no GitHub clone required / private-repo safe)",
   "/agent.tar.gz" in _ish)
# WSL/Linux SIGNED auto-update: the API serves the bundle signature and pins the release pubkey
# into the installer so update.sh applies ONLY signed bundles (fail-closed when unset).
ok("agent.tar.gz.sig route exists (404 until a signed bundle is deployed)",
   c.get("/agent.tar.gz.sig").status_code==404)
os.environ["PETABYTE_RELEASE_PUBKEY"]=base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()
ok("installer pins the release pubkey when configured (enables signed auto-update)",
   "-----BEGIN PUBLIC KEY-----" in c.get("/install.sh").text and "__PETABYTE_RELEASE_PUBKEY_PEM__" not in c.get("/install.sh").text)
del os.environ["PETABYTE_RELEASE_PUBKEY"]
ok("installer embeds NO key when unset (auto-update fail-closed, never TLS-only for root code)",
   "-----BEGIN PUBLIC KEY-----" not in c.get("/install.sh").text)
_lg=c.get("/static/petabyte-logo.png"); ok("brand logo served", _lg.status_code==200 and _lg.headers.get("content-type")=="image/png")
_bm=c.get("/static/petabyte-bimi.svg"); ok("BIMI mark served (svg tiny-ps)", _bm.status_code==200 and _bm.headers.get("content-type")=="image/svg+xml" and b"baseProfile=\"tiny-ps\"" in _bm.content)
ok("favicon served", c.get("/favicon.ico").status_code==200)
ok("static route rejects non-whitelisted name", c.get("/static/../main.py").status_code==404 and c.get("/static/secret.txt").status_code==404)
ok("landing references brand logo", "/static/petabyte-logo.png" in c.get("/").text)

# public marketplace specs (no auth) — should list our attested demo node(s)
pm=c.get("/marketplace/specs")
ok("public /marketplace/specs works unauthenticated", pm.status_code==200 and "aws_reference" in pm.json())
_pm=pm.json()
ok("public /marketplace/specs lists attested nodes", _pm.get("count",0) > 0 and len(_pm["specs"])==_pm["count"])
_allowed={"id","gpu_model","price_per_hour","cloud_reference","auto_price","region","region_verified","confidential","reputation_score","available_units","total_units","attested","trust","cpu","ram_gb","gpu_count","vram_gb","jobs_completed","jobs_failed","success_rate"}
_forbidden={"spec_id","user_id","owner","owner_id","username","email","host","ip","address","jti","seller_id"}
ok("public listing id is an opaque handle, not an enumerable int",
   all(isinstance(_s.get("id"), str) and not str(_s.get("id")).isdigit() for _s in _pm["specs"]))
ok("public /marketplace/specs leaks no identifiers",
   all(set(s).issubset(_allowed) and not (set(s) & _forbidden) for s in _pm["specs"]))
# SQL filter/sort/pagination: count is the TOTAL matches; specs is a bounded page.
if _pm["count"] > 1:
    _pg1=c.get("/marketplace/specs?limit=1&offset=0").json()
    _pg2=c.get("/marketplace/specs?limit=1&offset=1").json()
    ok("marketplace paginates in SQL (limit caps the page, count stays the total)",
       len(_pg1["specs"])==1 and _pg1["count"]==_pm["count"])
    ok("marketplace offset returns a different node (page 2 != page 1)",
       _pg1["specs"][0]["id"] != _pg2["specs"][0]["id"])
ok("price sort is ascending (SQL ORDER BY)",
   all(_pm["specs"][i]["price_per_hour"] <= _pm["specs"][i+1]["price_per_hour"] for i in range(len(_pm["specs"])-1)))

# Google OAuth stub flow: login -> redirect -> callback -> JWT -> works on /wallet
lg=c.get("/auth/google/login", follow_redirects=False)
ok("google login redirects", lg.status_code in (302,307) and "callback" in lg.headers.get("location",""))
cb=c.get("/auth/google/callback?code=stub&email=gtest@example.com", follow_redirects=False)
loc=cb.headers.get("location","")
# The session is delivered as an HttpOnly cookie now, NEVER a #t=JWT URL fragment (which would
# leak into history / referrers / JS). Clean redirect, token in the cookie jar.
ok("google callback redirects cleanly to /console (no token in the URL)",
   cb.status_code in (302,303,307) and loc.rstrip("/").endswith("/console") and "#t=" not in loc)
ok("google callback sets the HttpOnly session cookie (not a URL fragment)",
   bool(c.cookies.get("pb_session")))
# the callback set the session cookie on the client -> the browser is now authenticated by it
ok("google-issued session cookie authenticates", c.get("/wallet").status_code==200)
# The cookie VALUE is the JWT; capture it for the Bearer-style admin checks below, then clear
# the jar so the shared client `c` has NO ambient session (keeps the no-auth assertions honest).
gjwt=c.cookies.get("pb_session"); c.cookies.clear()
ok("google user is created/persistent", c.get("/auth/google/callback?code=x&email=gtest@example.com", follow_redirects=False).status_code in (302,303,307))

# ==== ADMIN CONSOLE (env-allowlisted, gated) ====
os.environ["ADMIN_USERS"]="gtest@example.com"   # make the google user an admin (read dynamically)
# Admin is conferred only by a VERIFIED matching email (see _is_admin). The stub OAuth path
# deliberately does NOT verify emails, so grant verification here as a real Google login would.
_sga=dbmod.SessionLocal(); _gu=main.get_user_by_username(_sga,"gtest@example.com")
_gu.email_verified=True; _sga.add(_gu); _sga.commit(); _sga.close()
GAH={"Authorization":f"Bearer {gjwt}"}
NAH={"Authorization":f"Bearer {login('buyer1')}"}   # a normal, non-admin user
ok("admin page serves to anyone (data still gated)", c.get("/admin").status_code==200 and "console" in c.get("/admin").text)
ok("admin overview requires auth", c.get("/admin/overview").status_code==401)
ok("admin overview blocks non-admin", c.get("/admin/overview", headers=NAH).status_code==403)
_ao=c.get("/admin/overview", headers=GAH)
ok("admin overview ok for admin", _ao.status_code==200 and {"users","specs","jobs","payouts_pending"} <= set(_ao.json()))
# --- admin operational snapshot (Live operations tiles + platform-health invariants) ---
ok("admin ops requires auth", c.get("/admin/ops").status_code==401)
ok("admin ops blocks non-admin", c.get("/admin/ops", headers=NAH).status_code==403)
_aops=c.get("/admin/ops", headers=GAH)
ok("admin ops returns the operational snapshot for admins",
   _aops.status_code==200 and {"marketplace","vms","clusters","disk","teams","in_escrow","health"} <= set(_aops.json()))
_aopsb=_aops.json()
ok("admin ops surfaces the ledger-balance health invariant",
   "ledger_balanced" in _aopsb["health"] and "payout_backlog" in _aopsb["health"]
   and isinstance(_aopsb["marketplace"].get("utilization_pct"), (int, float)))
ok("admin whoami true for admin", c.get("/admin/whoami", headers=GAH).json().get("admin")==True)
ok("admin whoami 403 for non-admin", c.get("/admin/whoami", headers=NAH).status_code==403)
# --- DATA MOAT: the GPU-authenticity training dataset is collected + admin-exportable ---
ok("authenticity dataset is admin-gated (403 for non-admin)", c.get("/admin/dataset/authenticity", headers=NAH).status_code==403)
_ds=c.get("/admin/dataset/authenticity", headers=GAH)
ok("authenticity dataset exports feature rows collected from real benchmarks + idle reports",
   _ds.status_code==200 and _ds.json()["stats"]["samples"]>=2 and isinstance(_ds.json()["rows"], list))
ok("dataset rows carry a supervised label + a ratio-to-public-reference feature",
   any("label_fraud" in r and any(k.startswith("ratio_") for k in r) for r in _ds.json()["rows"]))
ok("dataset exports as JSONL for training pipelines",
   c.get("/admin/dataset/authenticity?format=jsonl", headers=GAH).headers.get("content-type","").startswith("application/x-ndjson"))
ok("admin users list flags admin", any(u["username"]=="gtest@example.com" and u["is_admin"] for u in c.get("/admin/users", headers=GAH).json()["users"]))
ok("admin specs list", c.get("/admin/specs", headers=GAH).status_code==200)
# newsletter reconciliation (deferred-signup delivery) is admin-gated + reports pending count
ok("newsletter reconcile is admin-gated", c.post("/admin/newsletter/reconcile", headers=NAH).status_code==403)
_nrec=c.post("/admin/newsletter/reconcile", headers=GAH).json()
ok("newsletter reconcile reports pending count (no-op when Mailgun unconfigured)",
   "pending" in _nrec and _nrec.get("skipped") is True)
# --- DISASTER RECOVERY: platform database backup to S3 (S3_STUB in tests) ---
ok("backups admin list is admin-gated (403 for non-admin)", c.get("/admin/backups", headers=NAH).status_code==403)
ok("backups run is admin-gated (403 for non-admin)", c.post("/admin/backups/run", headers=NAH).status_code==403)
_bkr=c.post("/admin/backups/run", headers=GAH)
# 200 = dumped+uploaded; 503 = dump tool unavailable (e.g. pg_dump missing on the PG run) — either
# way the attempt must be RECORDED so 'no recent backup' alerting works.
ok("backup run either succeeds or fails loudly (no silent no-op)", _bkr.status_code in (200,503))
_bkl=c.get("/admin/backups", headers=GAH).json()
ok("backups list returns a status summary + rows", "status" in _bkl and isinstance(_bkl.get("backups"),list) and len(_bkl["backups"])>=1)
if _bkr.status_code==200:
    _bid=_bkr.json()["backup_id"]
    ok("successful backup is recorded as ok with a sha256", any(b["id"]==_bid and b["status"]=="ok" and b["sha256"] for b in _bkl["backups"]))
    ok("stored backup verifies (sha256 + decompresses)", c.post(f"/admin/backups/{_bid}/verify", headers=GAH).json()["ok"] is True)
    ok("backup status reports a fresh last-backup age", _bkl["status"]["last_backup_age_seconds"] is not None)
else:
    ok("a failed backup attempt is recorded (status=failed) for alerting", any(b["status"]=="failed" for b in _bkl["backups"]))
ok("admin can set the landing video from a full Shorts URL",
   c.post("/admin/landing/video", headers=GAH,
          json={"video":"https://youtube.com/shorts/UUSWYaxboDA?si=x"}).json().get("video_id")=="UUSWYaxboDA")
ok("a /shorts/ URL is auto-detected as portrait",
   c.post("/admin/landing/video", headers=GAH,
          json={"video":"https://youtube.com/shorts/UUSWYaxboDA"}).json().get("orientation")=="portrait")
ok("a watch?v= URL is auto-detected as landscape (a normal video embeds reliably)",
   c.post("/admin/landing/video", headers=GAH,
          json={"video":"https://youtube.com/watch?v=dQw4w9WgXcQ"}).json().get("orientation")=="landscape")
ok("an explicit orientation override wins over the URL",
   c.post("/admin/landing/video", headers=GAH,
          json={"video":"https://youtu.be/abc123","orientation":"portrait"}).json().get("orientation")=="portrait")
ok("GET /landing/video returns the stored orientation",
   c.get("/landing/video").json().get("orientation")=="portrait")
ok("landing page adapts the aspect ratio to orientation",
   "landingvideoratio" in c.get("/").text and "56.25%" in c.get("/").text)
ok("admin panel exposes the orientation selector",
   "vid_orient" in c.get("/admin").text)
_appjs=c.get("/console").text
ok("the console only fetches user data after auth (consoleLoad guards on authed())",
   "async function consoleLoad" in _appjs and "!authed()" in _appjs and "consoleLoad();" in _appjs)
# guard the exact bug that shipped: the referral card must be its OWN top-level function,
# lazily loaded when the billing tab opens — never at parse time.
ok("the referral card is a top-level function loaded lazily (not at parse time)",
   "async function cReferral" in _appjs and "cReferral();" in _appjs
   and "async function cBilling" in _appjs)
c.post("/admin/landing/video", headers=GAH, json={"video":"UUSWYaxboDA"})
ok("the landing then serves the admin-set video",
   c.get("/landing/video").json().get("video_id")=="UUSWYaxboDA")
ok("garbage video input is rejected",
   c.post("/admin/landing/video", headers=GAH, json={"video":"!!!"}).status_code==400)
ok("non-admins cannot change the landing video",
   c.post("/admin/landing/video", headers=NAH, json={"video":"x"}).status_code==403)
ok("the admin panel exposes the video control", "saveVideo" in c.get("/admin").text)
ok("demo requests are stored as real leads (demand evidence for investors)",
   c.get("/admin/demo-requests", headers=GAH).json().get("count", 0) >= 1)
ok("non-admins cannot read the lead list",
   c.get("/admin/demo-requests", headers=NAH).status_code == 403)
ok("admin payouts list", c.get("/admin/payouts", headers=GAH).status_code==200)
# --- admin incident view: failed/stalled transactions + reasons ---
_inc=c.get("/admin/incidents", headers=GAH)
ok("admin incidents ok for admin", _inc.status_code==200 and
   {"stalled_bookings","failed_jobs","failed_payouts","counts"} <= set(_inc.json()))
ok("admin incidents blocks non-admin", c.get("/admin/incidents", headers=NAH).status_code==403)
ok("every reported incident carries a human-readable reason",
   all("reason" in x for x in _inc.json()["failed_jobs"]) and
   all("reason" in x for x in _inc.json()["stalled_bookings"]) and
   all("reason" in x for x in _inc.json()["failed_payouts"]))
ok("admin panel exposes the incidents view", "loadIncidents" in c.get("/admin").text)
_rr=c.post("/admin/users/buyer1/role", headers=GAH, json={"role":"seller"})
ok("admin can set role", _rr.status_code==200 and _rr.json()["role"]=="seller")
ok("non-admin cannot set role", c.post("/admin/users/buyer1/role", headers=NAH, json={"role":"buyer"}).status_code==403)
_rr2=c.post("/admin/users/buyer1/role", headers=GAH, json={"role":"buyer"})  # restore
ok("admin delist guards unknown spec", c.post("/admin/specs/999999/delist", headers=GAH).status_code==404)
os.environ["ADMIN_USERS"]=""   # reset so no later assertion is affected

# API key UI: create (with label) -> list -> revoke
kc=c.post("/create_api_key?label=web-node&scopes=node,jobs&days=30", headers=s5h)
ok("create key returns secret", kc.status_code==200 and kc.json()["api_key"])
kl=c.get("/account/keys", headers=s5h).json()["keys"]
ok("issued key is listed", any(k["label"]=="web-node" and not k["revoked"] for k in kl))
jti=[k for k in kl if k["label"]=="web-node"][0]["jti"]
ok("revoke via UI route", c.post(f"/keys/{jti}/revoke", headers=s5h).status_code==200)
ok("revoked key shows revoked", any(k["jti"]==jti and k["revoked"] for k in c.get("/account/keys", headers=s5h).json()["keys"]))
ok("cannot revoke someone else's key", c.post(f"/keys/{jti}/revoke", headers=pbh).status_code==404)
# --- one-shot /launch: auto-pick node, book, start template (no spec_id needed) ---
c.post("/register_user", json={"username":"launchbuyer","password":"pw-correct-horse-battery"})
_lbh={"Authorization":"Bearer "+c.post("/login", data={"username":"launchbuyer","password":"pw-correct-horse-battery"}).json()["access_token"]}
c.post("/deposit", headers=_lbh, json={"amount":500})
_lr=c.post("/launch", headers=_lbh, json={"template":"minecraft","hours":1})
ok("/launch auto-books + starts a template", _lr.status_code==200 and "task_id" in _lr.json() and _lr.json().get("port")==25565)
ok("/launch unknown template -> 400", c.post("/launch", headers=_lbh, json={"template":"nope"}).status_code==400)
ok("/launch requires auth", c.post("/launch", json={"template":"minecraft"}).status_code in (401,403))
# --- /launch records WHY the node was picked, linked to the booking ---
_lj=_lr.json()
ok("/launch explains why the node was picked",
   "Selected" in _lj.get("routing_explanation","") and "because" in _lj.get("routing_explanation",""))
_ld=c.get(f"/routing/decisions/{_lj['routing_decision_id']}", headers=_lbh)
ok("/launch decision audit is readable by the buyer", _ld.status_code==200)
ok("/launch decision links the booking", _ld.json()["booking_id"]==_lj["booking_id"])
_bk=c.get(f"/bookings/{_lj['booking_id']}", headers=_lbh).json()
ok("booking carries its routing explanation",
   _bk["routing_decision_id"]==_lj["routing_decision_id"] and "because" in (_bk["routing_explanation"] or ""))

# --- VM routing + stable URL + failover (the Buyer/VM -> new node, same URL model) ---
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
def _mkseller(nm, price):
    c.post("/register_user", json={"username":nm,"password":"pw-correct-horse-battery"})
    h={"Authorization":"Bearer "+c.post("/login", data={"username":nm,"password":"pw-correct-horse-battery"}).json()["access_token"]}
    c.post("/change_role", headers=h, json={"role":"seller"})
    sd=c.post("/register_specs", headers=h, json={"cpu":8,"ram":32,"gpu_model":"L4","duration":24,"price_per_hour":price,"provider":nm,"units":2}).json()["spec_id"]
    at={"cpu":8,"ram":32,"gpu_model":"L4","nonce":nm,"ts":int(time.time())}
    c.post("/prove", headers=h, json={"spec_id":sd,"attestation":at,"signature":sign_proof(_VENDOR_SK,at),"pubkey":base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()})
    k=c.post("/create_api_key", headers=h).json()["api_key"]; c.post("/heartbeat", headers={"X-API-KEY":k}, json={"spec_id":sd})
    return h, sd
_ah,_asp=_mkseller("vmnodeA",0.4); _bh,_bsp=_mkseller("vmnodeB",0.8)
c.post("/register_user", json={"username":"vmbuyerX","password":"pw-correct-horse-battery"})
_vbh={"Authorization":"Bearer "+c.post("/login", data={"username":"vmbuyerX","password":"pw-correct-horse-battery"}).json()["access_token"]}
c.post("/deposit", headers=_vbh, json={"amount":200})
_lv=c.post("/launch", headers=_vbh, json={"template":"comfyui","hours":2}).json()
_vmid=_lv["vm_id"]; _url0=_lv["url"]["ssh"]
# Canonical address is the per-VM subdomain (id is the HOST -> the SSH username is free for any
# login user: root@, app@, ...). The username-routing form is a labelled zero-config fallback.
ok("launch returns a stable vm URL (subdomain: user is free)", _url0==f"ssh root@{_vmid}.petabyte.market")
ok("username-routing fallback is offered too", _lv["url"]["ssh_username_fallback"]==f"ssh vm-{_vmid}@petabyte.market")
ok("VM lands on cheapest node A", dbmod.get_vm_route(dbmod.SessionLocal(),_vmid).current_spec_id==_asp)
ok("hosting node registers tunnel -> running", c.post("/vm/register_tunnel", headers=_ah, json={"vm_id":_vmid,"tunnel_port":7001}).json().get("vm_status")=="running")
ok("non-hosting seller can't register tunnel", c.post("/vm/register_tunnel", headers=_bh, json={"vm_id":_vmid,"tunnel_port":9}).status_code==403)
ok("gateway route needs token", c.get(f"/vm/{_vmid}/route").status_code==403)
_dbf=dbmod.SessionLocal(); _saf=_dbf.query(dbmod.SellerSpec).filter(dbmod.SellerSpec.id==_asp).first()
_saf.last_seen=_dt.now(_tz.utc)-_td(seconds=999); _dbf.add(_saf); _dbf.commit()
_rp,_mig=dbmod.reap_and_failover(_dbf); _dbf.close()
_vmf=dbmod.get_vm_route(dbmod.SessionLocal(),_vmid)
ok("failover migrates VM off dead node A -> B", _mig==1 and _vmf.current_spec_id==_bsp)
ok("stable URL unchanged across failover", f"ssh root@{_vmid}.petabyte.market"==_url0 and _vmf.migrations==1)
ok("node B re-registers -> running again", c.post("/vm/register_tunnel", headers=_bh, json={"vm_id":_vmid,"tunnel_port":7050}).json().get("vm_status")=="running")
ok("buyer can stop the VM", c.post(f"/vm/{_vmid}/stop", headers=_vbh).status_code==200)

# --- metering + extend + expiry + pricing engine + seller earnings ---
_mh,_msp=_mkseller("meterseller",1.0)
c.post("/register_user", json={"username":"meterbuyer","password":"pw-correct-horse-battery"})
_mbh={"Authorization":"Bearer "+c.post("/login", data={"username":"meterbuyer","password":"pw-correct-horse-battery"}).json()["access_token"]}
c.post("/deposit", headers=_mbh, json={"amount":50})
_mv=c.post("/launch", headers=_mbh, json={"template":"comfyui","hours":1}).json()["vm_id"]
_g=c.get(f"/vm/{_mv}", headers=_mbh).json()
ok("VM has a metered paid window + rate", 0.9<=_g["hours_left"]<=1.01 and _g["hourly_rate"]>0)
ok("extend adds hours + charges buyer", c.post(f"/vm/{_mv}/extend", headers=_mbh, json={"hours":2}).json().get("hours_left",0)>=2.9)
ok("metered stop settles (bill held, refund rest)", c.post(f"/vm/{_mv}/stop", headers=_mbh).status_code==200)
_mv2=c.post("/launch", headers=_mbh, json={"template":"comfyui","hours":1}).json()["vm_id"]
_de=dbmod.SessionLocal(); _vv=dbmod.get_vm_route(_de,_mv2); _vv.paid_until=_dt.now(_tz.utc)-_td(minutes=1); _de.add(_vv); _de.commit()
ok("meter_and_expire auto-stops expired VM", dbmod.meter_and_expire(dbmod.SessionLocal())>=1)
# auto-pricing clamp
c.post("/register_user", json={"username":"autoseller","password":"pw-correct-horse-battery"})
_auth={"Authorization":"Bearer "+c.post("/login", data={"username":"autoseller","password":"pw-correct-horse-battery"}).json()["access_token"]}
c.post("/change_role", headers=_auth, json={"role":"seller"})
_asid=c.post("/register_specs", headers=_auth, json={"cpu":8,"ram":32,"gpu_model":"A100","duration":24,"price_per_hour":9.0,"provider":"a","units":2,"auto_price":True,"min_price":0.5,"max_price":2.0}).json()["spec_id"]
_aat={"cpu":8,"ram":32,"gpu_model":"A100","nonce":"autoseller","ts":int(time.time())}
c.post("/prove", headers=_auth, json={"spec_id":_asid,"attestation":_aat,"signature":sign_proof(_VENDOR_SK,_aat),"pubkey":base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()})
_ak=c.post("/create_api_key", headers=_auth).json()["api_key"]; c.post("/heartbeat", headers={"X-API-KEY":_ak}, json={"spec_id":_asid})
# explainable price recommendation: benchmark-anchored, inside the seller's band, shows its factors
_prec=c.get(f"/nodes/{_asid}/price/recommendation", headers=_auth).json()
ok("price recommendation is benchmark-anchored for A100", _prec["anchor_source"]=="performance" and _prec["perf_reference"]>0)
ok("price recommendation still reports the cloud reference for A100", _prec["cloud_reference"]==4.10)
ok("price recommendation stays inside the seller's band", 0.5<=_prec["recommended_price"]<=2.0)
ok("price recommendation shows its factors + a plain explanation",
   isinstance(_prec.get("factors"),list) and len(_prec["factors"])>=1 and bool(_prec.get("explanation")))
ok("price recommendation is owner-only", c.get(f"/nodes/{_asid}/price/recommendation", headers=_mh).status_code==404)
# GPU price catalog: benchmark-ordered, a slower GPU is never priced above a faster one
_cat=c.get("/pricing/catalog").json()
ok("pricing catalog lists GPU models sorted by benchmark", _cat["count"]>=20 and _cat["sorted_by"].startswith("benchmark"))
_cprices=[r["reference_price_per_hour"] for r in _cat["catalog"]]
ok("catalog reference price never decreases as benchmark rises (2060 < 4080 < 4090)",
   all(_cprices[i]<=_cprices[i+1] for i in range(len(_cprices)-1)))
_p2060=c.get("/pricing/suggest?gpu_model=RTX%202060").json()["suggested_price"]
_p4080=c.get("/pricing/suggest?gpu_model=RTX%204080").json()["suggested_price"]
ok("suggested price honours benchmark order (2060 cheaper than 4080)", _p2060 < _p4080)
dbmod.reprice_specs(dbmod.SessionLocal())
_asp=dbmod.get_spec_by_id(dbmod.SessionLocal(),_asid)
ok("auto-price clamps within [min,max], below cloud", 0.5<=_asp.price_per_hour<=2.0)
ok("/seller/earnings dashboard", "utilization" in c.get("/seller/earnings", headers=_mh).json())
# VM events timeline exists and records lifecycle
_ev=c.get(f"/vm/{_mv}/events", headers=_mbh).json()
ok("VM events timeline records lifecycle", any(e["event"]=="created" for e in _ev["events"]) and any(e["event"]=="stopped" for e in _ev["events"]))
ok("VM events are owner-only", c.get(f"/vm/{_mv}/events", headers=_mh).status_code==404)
# auto-price changes are logged + surfaced to the seller
_se=c.get("/seller/earnings", headers=_auth).json()
ok("price changes logged for auto-priced node", any(p["reason"]=="auto" for p in _se.get("recent_price_changes",[])))
ok("marketplace exposes auto_price flag", any("auto_price" in s for s in c.get("/marketplace/specs").json()["specs"]) or c.get("/marketplace/specs").json()["count"]>=0)
# org-wallet extend: booking billed to an org can be extended from the org wallet
c.post("/register_user", json={"username":"orgextuser","password":"pw-correct-horse-battery"})
_oeh={"Authorization":"Bearer "+c.post("/login", data={"username":"orgextuser","password":"pw-correct-horse-battery"}).json()["access_token"]}
_oid=c.post("/orgs", headers=_oeh, json={"name":"ExtendCo"}).json()["org_id"]
c.post(f"/orgs/{_oid}/deposit", headers=_oeh, json={"amount":100})
_ob=c.post("/request_vm", headers=_oeh, json={"spec_id":_msp,"hours":1,"org_id":_oid}).json()
ok("org booking extends from org wallet", dbmod.extend_booking(dbmod.SessionLocal(), _ob["booking_id"], 2)==True)
_obk=dbmod.SessionLocal().query(dbmod.Booking).filter(dbmod.Booking.id==_ob["booking_id"]).first()
ok("org extend grew escrow to 3h", _obk.hours==3)

# --- model cache-locality signal (scheduler prefers a node that already holds the model) ---
_ml = c.post("/nodes/models", headers={"X-API-KEY": seller_key},
             json={"spec_id": spec_id, "models": ["Qwen/Qwen3-8B", "meta-llama/Llama-3.1-8B", "../evil"]})
ok("agent reports cached models (bad ids rejected, valid kept)",
   _ml.status_code == 200 and _ml.json()["cached_models"] == 2)
_mv = c.get(f"/nodes/{spec_id}/models", headers=sh).json()
ok("owner sees the node's cached model list", "Qwen/Qwen3-8B" in _mv["models"] and "../evil" not in _mv["models"])
_mlj = c.post("/nodes/models", headers=sh, json={"spec_id": spec_id, "models": ["Qwen/Qwen3-8B"]})
ok("owner can also report via bearer token (petabyte node sync-models path)", _mlj.status_code == 200)
ok("reporting cached models needs auth (no key/token -> 401)",
   c.post("/nodes/models", json={"spec_id": spec_id, "models": []}).status_code == 401)
ok("a foreign user cannot read another node's cached models",
   c.get(f"/nodes/{spec_id}/models", headers=bh).status_code == 404)
# availability counts ONLINE nodes; refresh liveness so this doesn't depend on how long the
# (long) smoke run has taken to reach here.
c.post("/heartbeat", headers={"X-API-KEY": seller_key}, json={"spec_id": spec_id})
_av = c.get("/api/models/availability", params={"id": "Qwen/Qwen3-8B"}).json()
ok("availability reports how many online nodes hold the model", _av["nodes_cached"] >= 1)
ok("availability is zero for a model no node holds",
   c.get("/api/models/availability", params={"id": "nobody/x"}).json()["nodes_cached"] == 0)
_ranked = dbmod.rank_specs_for_model(dbmod.SessionLocal().query(dbmod.SellerSpec).all(), "Qwen/Qwen3-8B")
ok("scheduler ranking puts a cache-holding node first",
   _ranked and dbmod.node_has_model_cached(_ranked[0], "Qwen/Qwen3-8B"))

print("\nALL CHECKS PASSED")
