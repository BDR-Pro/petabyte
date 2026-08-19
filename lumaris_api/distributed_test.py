"""distributed_test.py — distributed compute: ONE job across N GPUs on DIFFERENT machines,
wired into a single cluster over the VPN. Hermetic (TestClient), offline.

Proves the control plane the product promises:
  * /distributed gang-schedules N nodes across DISTINCT providers (never two ranks on one PC),
    escrows all of them, and assigns ranks 0..N-1 with rank 0 the master;
  * it is all-or-nothing — a cluster that can't fully book is REFUSED and every booked rank is
    refunded (the buyer is charged nothing for a cluster that never formed);
  * rendezvous: rank 0 registers its VPN address, the other ranks fetch it to join, and only
    rank 0 may register;
  * the job completes when every rank finishes (no stitch step), and a dead rank fails the whole
    run (gang semantics).

Run: python distributed_test.py
"""
import os

os.environ["SECRET_KEY"] = "t"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///./distributed_test.db"
os.environ["GOOGLE_OAUTH_STUB"] = "true"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ.setdefault("WG_PUBLIC_KEY", "x"); os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ["REAPER_DISABLED"] = "true"

for f in ("distributed_test.db", "distributed_test.db-wal", "distributed_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import base64  # noqa: E402
import hashlib  # noqa: E402
import json as _json  # noqa: E402
import time as _time  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import db as dbm  # noqa: E402

c = TestClient(main.app)
_fail = 0

# A real Ed25519 attestation key shared by the execution-slice sellers, so each rank can submit a
# GENUINELY SIGNED /jobs/result the server verifies against the spec's attested pubkey (the real
# execution path — not the internal _advance_manifest shortcut the control-plane checks use).
_EXEC_KEY = Ed25519PrivateKey.generate()
_EXEC_PUB = base64.b64encode(_EXEC_KEY.public_key().public_bytes_raw()).decode()


def _sign(proof: dict) -> str:
    msg = _json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(_EXEC_KEY.sign(msg)).decode()


def _signed_result_body(task_id, status="completed", result=None, content_hash=None):
    """The exact body the agent's task_fetcher._signed_result builds for a distributed rank."""
    proof = {"task_id": task_id, "output_hash": (result or status)[:32], "ts": int(_time.time())}
    if content_hash:
        proof["content_hash"] = content_hash
    return {"task_id": task_id, "status": status, "result": result,
            "proof": proof, "signature": _sign(proof)}


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _code(r):
    # The app wraps HTTPException(detail={"code": ...}) as {"error": {"code": ...}, "detail": "<msg>"}.
    try:
        j = r.json()
        return ((j.get("error") or {}).get("code")
                or (j.get("detail", {}).get("code") if isinstance(j.get("detail"), dict) else None))
    except Exception:
        return None


def make_seller(idx, price=1.0):
    """A distinct, bookable, attested node (one per PC) + an agent API key for it."""
    s = dbm.SessionLocal()
    u = dbm.create_user(s, f"dseller{idx}", "pw-correct-horse-1")
    dbm.set_role(s, u.username, "seller")
    u.can_accept_paid_jobs = True
    spec = dbm.save_specs(s, u, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": price,
                                 "provider": f"dseller{idx}", "gpu_model": "RTX 4090",
                                 "gpu_count": 1, "vram_gb": 24, "units": 1})
    # Attest with the REAL shared Ed25519 pubkey so ANY booked rank can submit a signature the
    # server verifies (the execution slice signs with the matching _EXEC_KEY). Harmless to the
    # control-plane checks, which never submit a real signed result.
    spec.attested = True; spec.attest_pubkey = _EXEC_PUB; spec.status = "online"
    spec.last_seen = dbm._utcnow(); spec.available_units = 1; spec.total_units = 1
    spec.jobs_completed = 50; spec.heartbeats = 200
    s.add_all([u, spec]); s.commit()
    uid, spec_id = u.id, spec.id
    key, jti = main.gen_secure_api_key(u.username, 90, ["node", "jobs"])
    dbm.record_issued_key(s, uid, jti, "agent", ["node", "jobs"], 90)
    s.close()
    sv = {"username": f"dseller{idx}", "user_id": uid, "spec_id": spec_id,
          "kh": {"X-API-KEY": key}}
    ALL_SELLERS_BY_SPEC[spec_id] = sv     # global registry: sign for whichever spec the router books
    return sv


# Every seller ever created, keyed by spec id — the execution slice signs a result for whichever
# nodes the router actually gang-schedules (it picks the best-scored distinct owners, not just the
# freshest sellers), and each is attested with _EXEC_PUB so any of them can produce a valid result.
ALL_SELLERS_BY_SPEC = {}


def _bal(username):
    s = dbm.SessionLocal(); b = float(dbm.get_user_by_username(s, username).balance); s.close()
    return b


# a funded buyer
c.post("/register_user", json={"username": "dbuyer", "password": "pw-correct-horse-1"})
_bt = c.post("/login", data={"username": "dbuyer", "password": "pw-correct-horse-1"}).json()["access_token"]
BH = {"Authorization": "Bearer " + _bt}
_s = dbm.SessionLocal(); dbm.deposit(_s, dbm.get_user_by_username(_s, "dbuyer"), 100.0); _s.commit(); _s.close()

# three distinct nodes on three different machines, $1/hr each
N = 3
sellers = [make_seller(i, 1.0) for i in range(N)]
by_spec = {sv["spec_id"]: sv for sv in sellers}

# ---- gang-schedule a 3-GPU cluster ----
bal0 = _bal("dbuyer")
r = c.post("/distributed", headers=BH, json={"image": "pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime",
           "command": "torchrun train.py --epochs 3", "world_size": N, "hours": 1, "backend": "nccl"})
j = r.json()
ok("POST /distributed forms an N-GPU cluster (200, world_size=N, one rank each)",
   r.status_code == 200 and j.get("world_size") == N and len(j.get("ranks", [])) == N)
ok("exactly one master (rank 0) is designated",
   sum(1 for rk in j["ranks"] if rk["is_master"]) == 1 and j["ranks"][0]["rank"] == 0)
spec_ids = [rk["spec_id"] for rk in j["ranks"]]
ok("ANTI-AFFINITY: every rank lands on a DISTINCT node (never two ranks on the same PC)",
   len(set(spec_ids)) == N)
owner_ids = [by_spec[sid]["user_id"] for sid in spec_ids]
ok("the nodes are on DIFFERENT machines (distinct providers, not one box)",
   len(set(owner_ids)) == N)
ok("all N GPUs are escrowed up-front (buyer charged N x price x hours = $3)",
   abs((bal0 - _bal("dbuyer")) - 3.0) < 1e-9)
ok("estimated_cost is reported honestly ($3)", abs(float(j["estimated_cost"]) - 3.0) < 1e-9)

job_id = j["job_id"]
_man = c.get(f"/jobs/manifest/{job_id}", headers=BH).json()
ok("the cluster manifest reports kind=distributed, world_size, backend, and per-rank status",
   _man["kind"] == "distributed" and _man["world_size"] == N and _man["backend"] == "nccl"
   and _man["rendezvous_ready"] is False and len(_man["ranks"]) == N)

# map rank -> owning seller (for agent-authenticated rendezvous calls)
rank_seller = {rk["rank"]: by_spec[rk["spec_id"]] for rk in j["ranks"]}
rank0, rank1 = rank_seller[0], rank_seller[1]
task0 = next(rk["task_id"] for rk in j["ranks"] if rk["rank"] == 0)
task1 = next(rk["task_id"] for rk in j["ranks"] if rk["rank"] == 1)

# ---- rendezvous: every rank registers its own VPN address; only rank 0 becomes master ----
task2 = next(rk["task_id"] for rk in j["ranks"] if rk["rank"] == 2)
rank2 = rank_seller[2]
# an agent can only register a rank it OWNS (can't touch another rank's task)
rhijack = c.post("/jobs/rendezvous", headers=rank1["kh"], json={"task_id": task0, "host": "10.8.0.9", "port": 29500})
ok("an agent cannot register a rank it does not own (no master hijack, 404)", rhijack.status_code == 404)
# a non-zero rank registers its OWN address — allowed, but it does NOT become the master
rr1 = c.post("/jobs/rendezvous", headers=rank1["kh"], json={"task_id": task1, "host": "10.8.0.12", "port": 29500, "slots": 1})
ok("a non-master rank registers its own address (200) but is NOT the master",
   rr1.status_code == 200 and rr1.json()["is_master"] is False)
ok("a non-master registration does NOT set the cluster master",
   c.get(f"/jobs/rendezvous/{job_id}", headers=rank1["kh"]).json()["master_addr"] is None)
# rank 0 registers -> it becomes the master
rreg = c.post("/jobs/rendezvous", headers=rank0["kh"], json={"task_id": task0, "host": "10.8.0.1", "port": 29500})
ok("rank 0's registration sets the cluster master (its VPN host:port)",
   rreg.status_code == 200 and rreg.json()["is_master"] is True and rreg.json()["master_addr"] == "10.8.0.1")
# a joining rank fetches the master to join
rget = c.get(f"/jobs/rendezvous/{job_id}", headers=rank1["kh"]).json()
ok("a joining rank fetches the master address + its own rank over the VPN",
   rget["master_addr"] == "10.8.0.1" and rget["my_rank"] == 1
   and rget["is_master"] is False and rget["world_size"] == N)
# register the last rank so the whole cluster is addressable
c.post("/jobs/rendezvous", headers=rank2["kh"], json={"task_id": task2, "host": "10.8.0.13", "port": 29500, "slots": 1})
# an agent with no rank in this job cannot read the rendezvous
outsider = make_seller(99, 1.0)
ro = c.get(f"/jobs/rendezvous/{job_id}", headers=outsider["kh"])
ok("an agent with no rank in the job cannot read its rendezvous (404)", ro.status_code == 404)
ok("the manifest now shows rendezvous is ready",
   c.get(f"/jobs/manifest/{job_id}", headers=BH).json()["rendezvous_ready"] is True)

# ---- Petabyte is just another provider: export the cluster to the tools an org already runs ----
hf = c.get(f"/jobs/{job_id}/hostfile", headers=BH)
hbody = hf.text
ok("the cluster exports as an MPI/torchrun HOSTFILE (every node's VPN addr + slots)",
   hf.status_code == 200 and "10.8.0.1 slots=1" in hbody
   and "10.8.0.12 slots=1" in hbody and "10.8.0.13 slots=1" in hbody)
cl = c.get(f"/jobs/{job_id}/cluster", headers=BH).json()
ok("the cluster spec lists every node and is marked ready once all ranks registered",
   cl["ready"] is True and len(cl["nodes"]) == N and cl["master"]["host"] == "10.8.0.1")
ok("the cluster spec hands back ready-to-run launch commands for the standard schedulers",
   "mpirun" in cl["launch"] and "torchrun" in cl["launch"] and "ray_worker" in cl["launch"]
   and "10.8.0.1" in cl["launch"]["torchrun"])
# unauthenticated = no Bearer AND no session cookie; the shared client `c` holds a session
# cookie (a cookie is a valid session now), so a fresh client models the true "no auth" case.
ok("hostfile/cluster reject an unauthenticated caller (no Bearer, no session cookie)",
   TestClient(main.app).get(f"/jobs/{job_id}/hostfile").status_code in (401, 422))

# ---- completion: the job is done when EVERY rank finishes (no stitch step) ----
_s = dbm.SessionLocal()
for rk in j["ranks"]:
    t = _s.query(dbm.Task).filter(dbm.Task.id == rk["task_id"]).first()
    main._advance_manifest(_s, t, f"dist/{job_id}/rank{rk['rank']}")
_job = dbm.get_multinode_job(_s, job_id)
ok("the cluster completes only when ALL ranks finish", _job.status == "complete")
ok("a distributed job has NO stitch step (it is not a fan-out/reduce job)", _job.stitch_task_id is None)
_s.close()

# ---- insufficient distinct nodes: a cluster that can't span N machines is refused ----
rfew = c.post("/distributed", headers=BH, json={"image": "pytorch/pytorch:2.3.0",
              "command": "torchrun train.py", "world_size": N + 5, "hours": 1})
ok("a cluster needing more machines than exist is REFUSED (409), nothing charged",
   rfew.status_code == 409 and _code(rfew) == "INSUFFICIENT_DISTINCT_NODES")

# ---- all-or-nothing: if any rank can't be booked, every booked rank is refunded ----
c.post("/register_user", json={"username": "poorb", "password": "pw-correct-horse-1"})
_pt = c.post("/login", data={"username": "poorb", "password": "pw-correct-horse-1"}).json()["access_token"]
PH = {"Authorization": "Bearer " + _pt}
_s = dbm.SessionLocal(); dbm.deposit(_s, dbm.get_user_by_username(_s, "poorb"), 2.0); _s.commit(); _s.close()
# three fresh nodes so capacity is available; buyer can only afford 2 of the 3 ranks
poor_sellers = [make_seller(10 + i, 1.0) for i in range(3)]  # noqa: F841 (seeds capacity)
pbal0 = _bal("poorb")
rpoor = c.post("/distributed", headers=PH, json={"image": "pytorch/pytorch:2.3.0",
               "command": "torchrun train.py", "world_size": 3, "hours": 1})
ok("a cluster that can't fully book is REFUSED (402), not run half-formed",
   rpoor.status_code == 402 and _code(rpoor) == "CLUSTER_BOOKING_FAILED")
ok("all-or-nothing: the buyer is refunded in full (charged nothing for a cluster that never formed)",
   abs(_bal("poorb") - pbal0) < 1e-9)

# ---- gang semantics: a dead rank fails the whole run ----
r2 = c.post("/distributed", headers=BH, json={"image": "pytorch/pytorch:2.3.0",
            "command": "torchrun train.py", "world_size": N, "hours": 1}).json()
_s = dbm.SessionLocal()
_t = _s.query(dbm.Task).filter(dbm.Task.id == r2["ranks"][1]["task_id"]).first()
main._fail_distributed_if_member(_s, _t)
ok("a single dead rank fails the entire cluster (gang scheduling)",
   dbm.get_multinode_job(_s, r2["job_id"]).status == "failed")
_s.close()

# ---- buyer chooses VPN: a WireGuard client tunnel into the cluster's private network ----
vpn_sellers = [make_seller(20 + i, 1.0) for i in range(2)]  # noqa: F841 (fresh capacity)
rv = c.post("/distributed", headers=BH, json={"image": "pytorch/pytorch:2.3.0",
            "command": "torchrun train.py", "world_size": 2, "hours": 1, "vpn": True})
rvj = rv.json()
ok("a buyer can launch a cluster WITH a private VPN (vpn flag + config url returned)",
   rv.status_code == 200 and rvj.get("vpn") is True and rvj.get("vpn_config_url"))
vc = c.get(rvj["vpn_config_url"], headers=BH)
ok("the buyer downloads a real WireGuard CLIENT config for the cluster",
   vc.status_code == 200 and "[Interface]" in vc.text and "PrivateKey" in vc.text and "[Peer]" in vc.text)
# a cluster launched WITHOUT vpn refuses to issue a config
nov = [make_seller(30 + i, 1.0) for i in range(2)]  # noqa: F841
rn = c.post("/distributed", headers=BH, json={"image": "x/y:1", "command": "z",
            "world_size": 2, "hours": 1}).json()
ok("a non-VPN cluster refuses to hand out a VPN config (400)",
   c.get(f"/jobs/{rn['job_id']}/vpn_config", headers=BH).status_code == 400)

# ---- EXECUTION LOOP: a real cluster completes via SIGNED /jobs/result (not the internal shortcut) ----
# The checks above drive completion through main._advance_manifest directly. This slice proves the
# REAL seller-side execution path: each rank submits a genuinely Ed25519-signed result to the live
# /jobs/result endpoint (verified against the spec's attested pubkey), and the cluster completes only
# once EVERY rank has reported — exactly what task_fetcher._run_distributed does on a node.
[make_seller(40 + i, 1.0) for i in range(N)]     # fresh capacity for the execution slice
rex = c.post("/distributed", headers=BH, json={"world_size": N, "hours": 1, "selftest": True})
rexj = rex.json()
ok("a buyer can launch the built-in cluster SELF-TEST (no image/command required)",
   rex.status_code == 200 and rexj.get("world_size") == N and len(rexj.get("ranks", [])) == N)
exec_ranks = rexj["ranks"]
exec_rank_seller = {rk["rank"]: ALL_SELLERS_BY_SPEC[rk["spec_id"]] for rk in exec_ranks}
# every honest rank of an all-reduce ends holding the IDENTICAL reduced vector -> identical hash
_shared_hash = hashlib.sha256(b"reduced-vector-abc").hexdigest()
job_ex = rexj["job_id"]
# all but the last rank report completed: the cluster must NOT be complete yet (gang: needs ALL)
statuses = []
for rk in exec_ranks[:-1]:
    sv = exec_rank_seller[rk["rank"]]
    rr = c.post("/jobs/result", headers=sv["kh"],
                json=_signed_result_body(rk["task_id"], "completed",
                                         result=f"allreduce rank {rk['rank']}", content_hash=_shared_hash))
    statuses.append(rr.status_code)
ok("each rank's SIGNED result is accepted by the real /jobs/result endpoint (200)",
   all(sc == 200 for sc in statuses))
mid = c.get(f"/jobs/manifest/{job_ex}", headers=BH).json()
ok("the cluster is NOT complete until EVERY rank reports (gang completion, real endpoint)",
   mid["status"] == "running")
# the final rank reports -> the whole cluster completes, through the signed path
last = exec_ranks[-1]
rr_last = c.post("/jobs/result", headers=exec_rank_seller[last["rank"]]["kh"],
                 json=_signed_result_body(last["task_id"], "completed",
                                          result=f"allreduce rank {last['rank']}", content_hash=_shared_hash))
fin = c.get(f"/jobs/manifest/{job_ex}", headers=BH).json()
ok("once the LAST rank submits its signed result, the cluster completes (real execution path)",
   rr_last.status_code == 200 and fin["status"] == "complete")

# a FORGED signature is rejected and the run does not complete (binds result -> attested hardware)
[make_seller(50 + i, 1.0) for i in range(N)]     # fresh capacity
rex2 = c.post("/distributed", headers=BH, json={"world_size": N, "hours": 1, "selftest": True}).json()
frank = rex2["ranks"][0]
fspec_sv = ALL_SELLERS_BY_SPEC[frank["spec_id"]]
forged = _signed_result_body(frank["task_id"], "completed", result="forged")
forged["signature"] = base64.b64encode(b"\x00" * 64).decode()   # not a valid signature
rf = c.post("/jobs/result", headers=fspec_sv["kh"], json=forged)
ok("a forged result signature is rejected (401) — results are bound to attested hardware",
   rf.status_code == 401)

# gang failure via the REAL endpoint: one rank reports FAILED -> the whole cluster fails
[make_seller(60 + i, 1.0) for i in range(N)]     # fresh capacity
rex3 = c.post("/distributed", headers=BH, json={"world_size": N, "hours": 1, "selftest": True}).json()
drank = rex3["ranks"][1]
dsv = ALL_SELLERS_BY_SPEC[drank["spec_id"]]
rd = c.post("/jobs/result", headers=dsv["kh"],
            json=_signed_result_body(drank["task_id"], "failed"))
fj = c.get(f"/jobs/manifest/{rex3['job_id']}", headers=BH).json()
ok("a single rank reporting FAILED (signed, real endpoint) fails the entire cluster (gang)",
   rd.status_code == 200 and fj["status"] == "failed")

# ---- ONE ACCOUNT, MANY COMPUTERS: a home lab (multiple specs + multiple API keys) forms a cluster ----
# A single user can run several computers — each its own agent with its OWN API key + spec — and the
# platform gang-schedules them together. Anti-affinity is per MACHINE, not per account.
_s = dbm.SessionLocal()
lab = dbm.create_user(_s, "labowner", "pw-correct-horse-1")
dbm.set_role(_s, lab.username, "seller"); lab.can_accept_paid_jobs = True
for i in range(2):                                   # two computers on ONE account
    sp = dbm.save_specs(_s, lab, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 0.5,
                                  "provider": f"labowner-pc{i}", "gpu_model": "LabGPU X1",
                                  "gpu_count": 1, "vram_gb": 24, "units": 1})
    sp.attested = True; sp.attest_pubkey = _EXEC_PUB; sp.status = "online"
    sp.last_seen = dbm._utcnow(); sp.available_units = 1; sp.total_units = 1
    sp.jobs_completed = 50; sp.heartbeats = 200
    _s.add(sp)
_s.add(lab); _s.commit()
lab_id = lab.id
lab_spec_ids = [sp.id for sp in _s.query(dbm.SellerSpec).filter(dbm.SellerSpec.user_id == lab_id).all()]
lab_keys = []                                        # one distinct API key per computer, same account
for i in range(2):
    k, jti = main.gen_secure_api_key("labowner", 90, ["node", "jobs"])
    dbm.record_issued_key(_s, lab_id, jti, f"pc{i}", ["node", "jobs"], 90)
    lab_keys.append(k)
_s.close()
ok("one account can hold MANY distinct API keys (one per computer)", len(set(lab_keys)) == 2)
avl = c.get("/distributed/availability?gpu_class=LabGPU X1").json()
ok("availability counts a user's multiple computers as multiple bookable nodes (per-machine)",
   avl["available_nodes"] == 2)

# Differential (before booking, both machines free): distributed spreads by MACHINE, fan-out by OWNER.
import router as _rtr
_sd = dbm.SessionLocal()
sel_spec = _rtr.select_plan(_sd, {"workload": "distributed", "redundancy": 5,
                            "gpu_class": "LabGPU X1", "anti_affinity": "spec"})["selected"]
sel_owner = _rtr.select_plan(_sd, {"workload": "render", "redundancy": 5,
                             "gpu_class": "LabGPU X1"})["selected"]   # default = owner-level
_sd.close()
ok("distributed anti-affinity is per-MACHINE: both of one account's computers are selectable",
   len(sel_spec) == 2)
ok("fan-out redundancy stays per-OWNER: one account collapses to a single replica (unchanged)",
   len(sel_owner) == 1)

c.post("/register_user", json={"username": "labbuyer", "password": "pw-correct-horse-1"})
_lbt = c.post("/login", data={"username": "labbuyer", "password": "pw-correct-horse-1"}).json()["access_token"]
LBH = {"Authorization": "Bearer " + _lbt}
_s = dbm.SessionLocal(); dbm.deposit(_s, dbm.get_user_by_username(_s, "labbuyer"), 20.0); _s.commit(); _s.close()
rlab = c.post("/distributed", headers=LBH,
              json={"world_size": 2, "hours": 1, "gpu_class": "LabGPU X1", "selftest": True})
rlabj = rlab.json()
lab_rank_spec = [rk["spec_id"] for rk in rlabj.get("ranks", [])]
ok("one user's TWO computers form a 2-node distributed cluster (distinct MACHINES, one account)",
   rlab.status_code == 200 and len(set(lab_rank_spec)) == 2
   and all(sid in lab_spec_ids for sid in lab_rank_spec))
_s = dbm.SessionLocal()
rank_owners = {_s.query(dbm.SellerSpec).filter(dbm.SellerSpec.id == sid).first().user_id
               for sid in lab_rank_spec}
_s.close()
ok("both ranks are the SAME account's machines (multi-computer single account, not two accounts)",
   rank_owners == {lab_id})

# each computer registers its OWN rank with its OWN key; task_id disambiguates same-owner ranks
lab_rank_task = {rk["rank"]: rk["task_id"] for rk in rlabj["ranks"]}
job_lab = rlabj["job_id"]
r0 = c.post("/jobs/rendezvous", headers={"X-API-KEY": lab_keys[0]},
            json={"task_id": lab_rank_task[0], "host": "10.9.0.1", "port": 29500})
r1 = c.post("/jobs/rendezvous", headers={"X-API-KEY": lab_keys[1]},
            json={"task_id": lab_rank_task[1], "host": "10.9.0.2", "port": 29500})
ok("each computer registers its OWN rank with its OWN key (same account, distinct keys)",
   r0.status_code == 200 and r1.status_code == 200
   and r0.json()["is_master"] is True and r1.json()["is_master"] is False)
g_dis = c.get(f"/jobs/rendezvous/{job_lab}?task_id={lab_rank_task[1]}",
              headers={"X-API-KEY": lab_keys[1]}).json()
ok("task_id makes the rendezvous return THIS machine's exact rank when one account owns several",
   g_dis["my_rank"] == 1 and g_dis["master_addr"] == "10.9.0.1")

# ---- the two API surfaces stay separated: /distributed is a compute (not data) endpoint ----
ok("/distributed is a compute endpoint, documented under the Developer API (/devs), not /data",
   any(p == "/distributed" for p in c.get("/devs/openapi.json").json()["paths"])
   and "/distributed" not in c.get("/data/openapi.json").json()["paths"])

for f in ("distributed_test.db", "distributed_test.db-wal", "distributed_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== distributed: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
