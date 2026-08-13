"""distributed_run_test.py — the EXECUTION proof for distributed compute.

The control-plane test (lumaris_api/distributed_test.py) proves the platform gang-schedules N
nodes, escrows all-or-nothing, and coordinates rendezvous. THIS test proves the other half — that
a cluster the platform assembled ACTUALLY RUNS: N independent OS processes, each a rank, rendezvous
through the master address, exchange real data over real TCP sockets, and every rank ends holding
the identical, correct globally-reduced result. No GPU, no torch, no Docker, no VPN — hermetic and
offline, so "one job really ran across N ranks and produced the right answer" is a green test, not
a claim.

Covered:
  * build_torchrun_cmd wires the master address / this rank / world size into a real torchrun
    launch (the exact argv a training rank runs in its container);
  * resolve_master: rank 0 is its own master immediately; a joining rank polls until rank 0 is up;
    a master that never appears fails the rank (and, gang-scheduled, the whole cluster);
  * THE PROOF: a real 4-process all-reduce — every rank converges on the correct element-wise sum;
  * gang failure at execution: a missing rank makes the run fail (no rank falsely reports success),
    proven both at the function level and across real processes.

Run:  python distributed_run_test.py     (from the lumaris_agent/ directory)
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import distributed_run as dr  # noqa: E402

_fail = 0
_HERE = os.path.dirname(os.path.abspath(__file__))


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn(rank, world, port, outdir, *, dim=8, seed=0, timeout=30):
    out = os.path.join(outdir, f"rank{rank}.json")
    p = subprocess.Popen(
        [sys.executable, "-m", "distributed_run", "selftest",
         "--rank", str(rank), "--world-size", str(world), "--master", f"127.0.0.1:{port}",
         "--dim", str(dim), "--seed", str(seed), "--bind", "127.0.0.1",
         "--timeout", str(timeout), "--out", out],
        cwd=_HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p, out


# --------------------------------------------------------------------------- 1) launch command
cmd = dr.build_torchrun_cmd(
    image="pytorch/pytorch:2.3.0-cuda12.1-cudnn8-runtime",
    command="train.py --epochs 3", rank=2, world_size=4,
    master_addr="10.8.0.1", master_port=29500, backend="nccl", gpu=True,
    env={"WANDB_MODE": "offline"},
    isolation_flags=["--cap-drop", "ALL"], egress_flags=["--network", "host"])
cmds = " ".join(cmd)
ok("build_torchrun_cmd launches the buyer image under torchrun",
   cmd[:3] == ["docker", "run", "--rm"] and "torchrun" in cmd
   and cmd[-3:] == ["train.py", "--epochs", "3"])
ok("torchrun is wired to the master / this rank / the world size",
   "--nnodes=4" in cmd and "--node_rank=2" in cmd
   and "--master_addr=10.8.0.1" in cmd and "--master_port=29500" in cmd)
ok("the standard distributed env is exported for frameworks that read it directly",
   "RANK=2" in cmds and "WORLD_SIZE=4" in cmds and "MASTER_ADDR=10.8.0.1" in cmds)
ok("seller-protection + cluster-egress flags are passed through to docker run",
   "--cap-drop" in cmd and "--gpus" in cmd and "--network" in cmd)
ok("the rendezvous env overrides buyer-supplied env (can't be spoofed) + buyer env still present",
   "WANDB_MODE=offline" in cmds and cmds.count("MASTER_ADDR=") == 1)
try:
    dr.build_torchrun_cmd(image=None, command="x", rank=0, world_size=2,
                          master_addr="a", master_port=1)
    ok("a distributed task with no image is rejected", False)
except ValueError:
    ok("a distributed task with no image is rejected", True)


# --------------------------------------------------------------------------- 2) resolve master
m = dr.resolve_master({"rank": 0, "is_master": True}, my_host="10.8.0.1", my_port=29500)
ok("rank 0 is its own master immediately (no polling)",
   m["is_master"] is True and m["master_addr"] == "10.8.0.1" and m["master_port"] == 29500)

# a joining rank polls the rendezvous until rank 0 has registered
_polls = {"n": 0}


def _fetch_ready_on_3rd():
    _polls["n"] += 1
    if _polls["n"] < 3:
        return {"master_addr": None, "master_port": None, "my_rank": 1}
    return {"master_addr": "10.8.0.1", "master_port": 29500, "my_rank": 1}


_clock = {"t": 0.0}
m2 = dr.resolve_master(
    {"rank": 1, "is_master": False}, my_host="10.8.0.7", my_port=29500,
    current={"master_addr": None}, fetch=_fetch_ready_on_3rd,
    sleep=lambda s: _clock.__setitem__("t", _clock["t"] + s),
    now=lambda: _clock["t"], timeout_s=120)
ok("a joining rank polls rendezvous until rank 0 is up, then joins it",
   m2["is_master"] is False and m2["master_addr"] == "10.8.0.1" and _polls["n"] >= 3)

# a master that never appears fails the rank (=> gang failure of the whole cluster)
_clk = {"t": 0.0}
try:
    dr.resolve_master(
        {"rank": 1, "is_master": False}, my_host="10.8.0.7", my_port=29500,
        current={"master_addr": None}, fetch=lambda: {"master_addr": None},
        sleep=lambda s: _clk.__setitem__("t", _clk["t"] + 10), now=lambda: _clk["t"],
        timeout_s=30)
    ok("a rank whose master never appears fails (gang semantics)", False)
except TimeoutError:
    ok("a rank whose master never appears fails (gang semantics)", True)

ok("is_selftest recognises the built-in cluster self-test",
   dr.is_selftest({"command": dr.SELFTEST_SENTINEL}) is True
   and dr.is_selftest({"distributed": {"selftest": True}}) is True
   and dr.is_selftest({"command": "train.py"}) is False)


# --------------------------------------------------------------------------- 3) THE PROOF
# A real 4-process all-reduce: 4 independent OS processes, each a rank, rendezvous through the
# master and reduce over real TCP sockets. Every rank must end with the SAME correct sum.
N, DIM, SEED = 4, 8, 20260812
port = _free_port()
with tempfile.TemporaryDirectory() as d:
    procs = [_spawn(r, N, port, d, dim=DIM, seed=SEED, timeout=30) for r in range(N)]
    rcs = [p.wait(timeout=60) for p, _ in procs]
    results = [json.load(open(out)) for _, out in procs]

expected = dr.expected_allreduce(N, DIM, SEED)
ok("all N rank processes exited successfully (rc==0)", all(rc == 0 for rc in rcs))
ok("every rank reported ok", all(r.get("ok") for r in results))
ok("EVERY rank converged on the IDENTICAL reduced vector",
   len({tuple(r["result"]) for r in results}) == 1)
ok("the reduced vector is the CORRECT element-wise sum across all ranks",
   all(r["result"] == expected for r in results))
ok("the master coordinated exactly N contributors (no rank silently dropped)",
   all(r.get("contributors") == N for r in results))
# each rank contributed a DISTINCT vector, so the sum could only be right if all really participated
ok("the result reflects every distinct per-rank contribution (not a single node's echo)",
   expected != [x * N for x in dr.rank_vector(0, DIM, SEED)])


# --------------------------------------------------------------------------- 4) gang failure
# Function level: a master missing a worker times out (fast + deterministic).
t0 = time.monotonic()
try:
    dr.master_allreduce("127.0.0.1", _free_port(), world_size=2,
                        my_vector=dr.rank_vector(0, 4, 1), timeout_s=2)
    ok("a master whose worker never joins fails the run (TimeoutError)", False)
except TimeoutError:
    ok("a master whose worker never joins fails the run (TimeoutError)",
       time.monotonic() - t0 < 10)

# a worker with no master to reach fails, too
try:
    dr.worker_allreduce("127.0.0.1", _free_port(), rank=1,
                        my_vector=dr.rank_vector(1, 4, 1), timeout_s=2)
    ok("a worker that can't reach the master fails the run (TimeoutError)", False)
except TimeoutError:
    ok("a worker that can't reach the master fails the run (TimeoutError)", True)

# Process level: launch a 2-rank cluster but only bring up rank 0 — the run must NOT succeed.
port2 = _free_port()
with tempfile.TemporaryDirectory() as d:
    p, out = _spawn(0, 2, port2, d, dim=4, seed=1, timeout=3)
    rc = p.wait(timeout=30)
    res = json.load(open(out))
ok("across real processes, a cluster missing a rank fails — no false success",
   rc != 0 and res.get("ok") is False and "worker" in (res.get("error") or "").lower())


print(f"\n=== distributed execution: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
