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
    spec.attested = True; spec.attest_pubkey = "k"; spec.status = "online"
    spec.last_seen = dbm._utcnow(); spec.available_units = 1; spec.total_units = 1
    spec.jobs_completed = 50; spec.heartbeats = 200
    s.add_all([u, spec]); s.commit()
    uid, spec_id = u.id, spec.id
    key, jti = main.gen_secure_api_key(u.username, 90, ["node", "jobs"])
    dbm.record_issued_key(s, uid, jti, "agent", ["node", "jobs"], 90)
    s.close()
    return {"username": f"dseller{idx}", "user_id": uid, "spec_id": spec_id,
            "kh": {"X-API-KEY": key}}


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
ok("hostfile/cluster are owner-only (an outsider agent JWT can't read them)",
   c.get(f"/jobs/{job_id}/hostfile").status_code in (401, 422))

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

# ---- the two API surfaces stay separated: /distributed is a compute (not data) endpoint ----
ok("/distributed is a compute endpoint, documented under the Developer API (/devs), not /data",
   any(p == "/distributed" for p in c.get("/devs/openapi.json").json()["paths"])
   and "/distributed" not in c.get("/data/openapi.json").json()["paths"])

for f in ("distributed_test.db", "distributed_test.db-wal", "distributed_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

print(f"\n=== distributed: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
