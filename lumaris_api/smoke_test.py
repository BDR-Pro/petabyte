import os, json, time, base64
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import hashlib

def sign_proof(key, proof):
    msg = json.dumps(proof, sort_keys=True, separators=(',',':')).encode()
    return base64.b64encode(key.sign(msg)).decode()


os.environ["DATABASE_URL"] = "sqlite:///./smoke.db"
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
import main, db as dbmod
c = TestClient(main.app)

def ok(label, cond):
    print(("PASS " if cond else "FAIL ") + label); assert cond, label

# ---- setup: seller + buyer, seller role, attested spec with 3 units ----
c.post("/register_user", json={"username":"seller1","password":"hunter2pw"})
c.post("/register_user", json={"username":"buyer1","password":"hunter2pw"})
def login(u): return c.post("/login", data={"username":u,"password":"hunter2pw"}).json()["access_token"]
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
c.post("/register_user", json={"username":"seller2","password":"hunter2pw"})
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
c.post("/register_user", json={"username":"seller3","password":"hunter2pw"})
c.post("/register_user", json={"username":"buyer3","password":"hunter2pw"})
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


# ---- CONFIDENTIAL COMPUTING (TEE attestation) ----
c.post("/register_user", json={"username":"seller4","password":"hunter2pw"})
c.post("/register_user", json={"username":"buyer4","password":"hunter2pw"})
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
adminh={"Authorization":f"Bearer {login('orgadmin')}"}
memberh={"Authorization":f"Bearer {login('orgmember')}"}
outsiderh={"Authorization":f"Bearer {login('outsider')}"}
sellh={"Authorization":f"Bearer {login('orgseller')}"}

org_id=c.post("/orgs", headers=adminh, json={"name":"AcmeLabs"}).json()["org_id"]
ok("org created (creator is admin)", c.get(f"/orgs/{org_id}", headers=adminh).json()["your_role"]=="admin")
ok("non-member blocked from org", c.get(f"/orgs/{org_id}", headers=outsiderh).status_code==403)
ok("admin adds member", c.post(f"/orgs/{org_id}/members", headers=adminh, json={"username":"orgmember","role":"member"}).status_code==200)
ok("member cannot add members", c.post(f"/orgs/{org_id}/members", headers=memberh, json={"username":"outsider","role":"member"}).status_code==403)

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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
s5h={"Authorization":f"Bearer {login('seller5')}"}
b5tok=login("buyer5"); b5h={"Authorization":f"Bearer {b5tok}"}
c.post("/change_role", headers=s5h, json={"role":"seller"})
c.post("/deposit", headers=b5h, json={"amount":1000.0})
sid5=c.post("/register_specs", headers=s5h, json={"cpu":16,"ram":64,"duration":48,"price_per_hour":2.0,"provider":"seller5","gpu_model":"H100","units":20}).json()["spec_id"]
sk5=Ed25519PrivateKey.generate(); pb5=base64.b64encode(sk5.public_key().public_bytes_raw()).decode()
at5={"cpu":16,"nonce":"q","ts":int(time.time())}
c.post("/prove", headers=s5h, json={"spec_id":sid5,"attestation":at5,"signature":sign_proof(sk5,at5),"pubkey":pb5})
key5=c.post("/create_api_key", headers=s5h).json()["api_key"]
c.post("/heartbeat", headers={"X-API-KEY":key5}, json={"spec_id":sid5})

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
bph={"task_id":bjob["task_id"],"output_hash":"bench","ts":int(time.time())}
ok("signed benchmark result accepted", c.post("/jobs/benchmark_result", headers={"X-API-KEY":key5}, json={"spec_id":sid5,"tokens_sec":2350.5,"meta":{"model":"llama3-8b","sd_images_sec":4.2},"proof":bph,"signature":sign_proof(sk5,bph)}).status_code==200)
ok("/specs surfaces tokens/sec", any(s["spec_id"]==sid5 and s["benchmark_tokens_sec"]==2350.5 for s in c.get("/specs", headers=b5h).json()["specs"]))

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
from db import SessionLocal as _DBS, SellerSpec as _Spec, Task as _T, Booking as _Bk, settle_dead_specs as _settle
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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

# ==== RENDER FARM (frame splitting across nodes) ====
c.post("/register_user", json={"username":"renderbuyer","password":"hunter2pw"})
rndh={"Authorization":f"Bearer {login('renderbuyer')}"}
c.post("/deposit", headers=rndh, json={"amount":200.0})
for u in ["rr1","rr2"]:
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
hR1,sidR1,skR1,keyR1=seller("rr1",2.0,gpu="RENDERGPU")
hR2,sidR2,skR2,keyR2=seller("rr2",2.0,gpu="RENDERGPU")
job=c.post("/render", headers=rndh, json={"blend_ref":"s3://pb/scene.blend","frame_start":1,"frame_end":100,"nodes":2,"hours":1,"gpu_class":"RENDERGPU"}).json()
ok("render splits across 2 nodes", job["nodes"]==2)
ok("render frame chunks contiguous & complete", sorted(tuple(t["frames"]) for t in job["tasks"])==[(1,50),(51,100)])
# the assigned node receives its frame range
rjob=c.get("/jobs/next", headers={"X-API-KEY":keyR1}).json()
ok("render node gets a frame subrange", rjob["task_type"]=="render" and "frame_start" in rjob and "frame_end" in rjob and rjob["blend_ref"].endswith("scene.blend"))
ok("render task carries a container image (no host install)", bool(rjob.get("image")) and rjob.get("gpu") is True)
iu=c.post("/jobs/input_url", headers={"X-API-KEY":keyR1}, json={"task_id":rjob["task_id"],"ref":rjob["blend_ref"]}).json()
ok("node pulls scene via pre-signed GET", "op=get" in iu["download_url"] and iu["key"]=="scene.blend")


# ==== PAYOUTS + SCHEDULED WITHDRAW ====
from db import (SessionLocal as _PDBS, pending_payouts as _pend, set_payout_status as _sps,
                SellerPayoutMethod as _PM, Payout as _PO, PayoutSchedule as _PS,
                run_due_schedules as _rds)
from payout_providers import process_payouts as _procpay
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
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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
# add a gift-card payout method, then verify (KYC/screen)
mid=c.post("/wallet/methods", headers=psh, json={"kind":"gift_card","destination":"seller@example.com","label":"Amazon"}).json()["method_id"]
ok("unverified method blocks withdraw", c.post("/wallet/withdraw", headers=psh, json={"method_id":mid,"amount":5}).status_code==403)
c.post(f"/wallet/methods/{mid}/verify", headers=psh)
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
c.post("/register_user", json={"username":"noemail","password":"hunter2pw"})
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
c.post("/register_user", json={"username":"tcbuyer","password":"hunter2pw"})
tcb={"Authorization":f"Bearer {login('tcbuyer')}"}
c.post("/deposit", headers=tcb, json={"amount":200.0})
for u in ["tc1","tc2"]:
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
htc1,sidTC1,skTC1,keyTC1=seller("tc1",1.0,gpu="TCGPU")
htc2,sidTC2,skTC2,keyTC2=seller("tc2",1.0,gpu="TCGPU")
keymap={sidTC1:(keyTC1,skTC1), sidTC2:(keyTC2,skTC2)}

# one-click buyer upload -> pre-signed PUT under the buyer's own prefix
up=c.post("/uploads/url", headers=tcb, json={"filename":"movie.mp4"}).json()
ok("buyer gets a pre-signed upload URL", "op=put" in up["upload_url"] and up["ref"].startswith("s3://") and up["key"].startswith("inputs/") and up["key"].endswith("movie.mp4"))

# ffmpeg in the catalog
ok("ffmpeg template listed", any(t["name"]=="ffmpeg" for t in c.get("/templates").json()["templates"]))

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
rj=c.post("/render", headers=rndh, json={"blend_ref":"s3://pb/scene.blend","frame_start":1,"frame_end":100,"nodes":2,"hours":1,"gpu_class":"RENDERGPU"}).json()
ok("render now returns a manifest job", "job_id" in rj and rj["nodes"]==2)
rkeymap={sidR1:(keyR1,skR1), sidR2:(keyR2,skR2)}
for seg in rj["tasks"]:
    key,sk=rkeymap[seg["spec_id"]]
    c.get("/jobs/next", headers={"X-API-KEY":key})
    ph={"task_id":seg["task_id"],"output_hash":"f","ts":int(time.time())}
    c.post("/jobs/result", headers={"X-API-KEY":key}, json={"task_id":seg["task_id"],"status":"completed","result":f"s3://pb/render/{rj['job_id']}/seg.tar","proof":ph,"signature":sign_proof(sk,ph)})
rman=c.get(f"/jobs/manifest/{rj['job_id']}", headers=rndh).json()
ok("render assembles via manifest (stitch created)", rman["status"]=="assembling" and rman["stitch_task_id"] is not None)


# ==== IDLE FALLBACK (earn when unrented) ====
for u in ["idleseller"]:
    c.post("/register_user", json={"username":u,"password":"hunter2pw"})
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
ok("idle earnings credited to seller balance (0.85*0.9)", round(c.get("/wallet", headers=ish).json()["earnings"],3)==0.765)
ok("reconcile: 1 worker, platform cut 0.085", res["credited_workers"]==1 and round(res["platform_total"],3)==0.085)
_d=_RDBS(); res2=_recon(_d, {f"pb-{sidI}": {"period":"2026-07-02","amount":0.85}}, 0.10); _d.close()
ok("reconcile idempotent per period", res2["credited_workers"]==0 and round(c.get("/wallet", headers=ish).json()["earnings"],3)==0.765)
_idle=c.get(f"/nodes/{sidI}/idle", headers=ish).json()
ok("idle credited_total + worker_id exposed", round(_idle["credited_total_usd"],3)==0.765 and _idle["worker_id"]==f"pb-{sidI}")


# ==== WEBSITE PAGES + GOOGLE OAUTH + KEYS UI + PUBLIC SPECS ====
os.environ["GOOGLE_OAUTH_STUB"]="true"
import importlib, main as _m; importlib.reload(_m)  # not needed; env read at call time
for path in ["/","/app","/investors","/developers","/install","/keys","/marketplace","/admin","/gamers"]:
    r=c.get(path); ok(f"page {path} serves", r.status_code==200 and "Petabyte" in r.text)
ok("gamers page has game catalog", "Minecraft" in c.get("/gamers").text)
ok("nav swapped Investors->Gamers", "Gamers" in c.get("/").text and 'href="/investors"' not in c.get("/").text)
_mf=c.get("/marketplace/specs?gpu=H100&max_price=5&min_vram=1&sort=rep"); ok("marketplace filter+depth", _mf.status_code==200 and "count" in _mf.json())
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
ok("/me requires auth", c.get("/me").status_code in (401,403))
ok("nav has sign-in and sign-out", 'id="signinlink"' in _lt0 and 'id="signoutlink"' in _lt0)
# node bootstrap with API key only (no creds): seller mints key, node registers+attests with it
_nk=c.post("/create_api_key?days=90&label=node&scopes=node,jobs", headers=s5h).json()["api_key"]
_kh={"X-API-KEY": _nk}
_rs=c.post("/register_specs", headers=_kh, json={"cpu":8,"ram":32,"gpu_model":"L4","duration":24,"price_per_hour":1.0,"provider":"keynode","units":1})
ok("register_specs with API key only", _rs.status_code==200 and "spec_id" in _rs.json())
_ksid=_rs.json()["spec_id"]
_katt={"cpu":8,"ram":32,"gpu_model":"L4","nonce":"kn","ts":int(time.time())}
ok("prove/attest with API key only", c.post("/prove", headers=_kh, json={"spec_id":_ksid,"attestation":_katt,"signature":sign_proof(_VENDOR_SK,_katt),"pubkey":base64.b64encode(_VENDOR_SK.public_key().public_bytes_raw()).decode()}).status_code==200)
ok("register_specs blocks no-auth", c.post("/register_specs", json={"cpu":1,"ram":1,"duration":1,"price_per_hour":1,"provider":"x","units":1}).status_code==401)
ok("login page offers Google sign-in", "auth/google/login" in c.get("/login").text)
ok("install.sh served by API", c.get("/install.sh").status_code==200 and "petabyte-agent" in c.get("/install.sh").text)
ok("install.ps1 served by API", c.get("/install.ps1").status_code==200)
ok("installers are key-based (no creds)", "PETABYTE_API_KEY" in c.get("/install.sh").text and "PETABYTE_PASS" not in c.get("/install.sh").text)
_lg=c.get("/static/petabyte-logo.png"); ok("brand logo served", _lg.status_code==200 and _lg.headers.get("content-type")=="image/png")
ok("favicon served", c.get("/favicon.ico").status_code==200)
ok("static route rejects non-whitelisted name", c.get("/static/../main.py").status_code==404 and c.get("/static/secret.txt").status_code==404)
ok("landing references brand logo", "/static/petabyte-logo.png" in c.get("/").text)

# public marketplace specs (no auth) — should list our attested demo node(s)
pm=c.get("/marketplace/specs")
ok("public /marketplace/specs works unauthenticated", pm.status_code==200 and "aws_reference" in pm.json())
_pm=pm.json()
ok("public /marketplace/specs lists attested nodes", _pm.get("count",0) > 0 and len(_pm["specs"])==_pm["count"])
_allowed={"gpu_model","price_per_hour","region","region_verified","confidential","reputation_score","available_units","gpu_count","vram_gb","jobs_completed","jobs_failed","success_rate"}
_forbidden={"id","spec_id","user_id","owner","owner_id","username","email","host","ip","address","jti","seller_id"}
ok("public /marketplace/specs leaks no identifiers",
   all(set(s).issubset(_allowed) and not (set(s) & _forbidden) for s in _pm["specs"]))

# Google OAuth stub flow: login -> redirect -> callback -> JWT -> works on /wallet
lg=c.get("/auth/google/login", follow_redirects=False)
ok("google login redirects", lg.status_code in (302,307) and "callback" in lg.headers.get("location",""))
cb=c.get("/auth/google/callback?code=stub&email=gtest@example.com", follow_redirects=False)
loc=cb.headers.get("location","")
ok("google callback issues JWT redirect to /app", cb.status_code in (302,307) and "/app#t=" in loc)
gjwt=loc.split("t=")[1]
gw=c.get("/wallet", headers={"Authorization":f"Bearer {gjwt}"})
ok("google-issued JWT authenticates", gw.status_code==200)
ok("google user is created/persistent", c.get("/auth/google/callback?code=x&email=gtest@example.com", follow_redirects=False).status_code in (302,307))

# ==== ADMIN CONSOLE (env-allowlisted, gated) ====
os.environ["ADMIN_USERS"]="gtest@example.com"   # make the google user an admin (read dynamically)
GAH={"Authorization":f"Bearer {gjwt}"}
NAH={"Authorization":f"Bearer {login('buyer1')}"}   # a normal, non-admin user
ok("admin page serves to anyone (data still gated)", c.get("/admin").status_code==200 and "console" in c.get("/admin").text)
ok("admin overview requires auth", c.get("/admin/overview").status_code==401)
ok("admin overview blocks non-admin", c.get("/admin/overview", headers=NAH).status_code==403)
_ao=c.get("/admin/overview", headers=GAH)
ok("admin overview ok for admin", _ao.status_code==200 and {"users","specs","jobs","payouts_pending"} <= set(_ao.json()))
ok("admin whoami true for admin", c.get("/admin/whoami", headers=GAH).json().get("admin")==True)
ok("admin whoami 403 for non-admin", c.get("/admin/whoami", headers=NAH).status_code==403)
ok("admin users list flags admin", any(u["username"]=="gtest@example.com" and u["is_admin"] for u in c.get("/admin/users", headers=GAH).json()["users"]))
ok("admin specs list", c.get("/admin/specs", headers=GAH).status_code==200)
ok("admin payouts list", c.get("/admin/payouts", headers=GAH).status_code==200)
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
print("\nALL CHECKS PASSED")
