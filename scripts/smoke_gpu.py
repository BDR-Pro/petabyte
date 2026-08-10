#!/usr/bin/env python3
"""smoke_gpu.py — REAL GPU load assertion for a seller GPU machine.

Proves genuine GPU work — not that `nvidia-smi` merely exists:
  1. detect an NVIDIA GPU on the host (nvidia-smi),
  2. verify the GPU is visible INSIDE the SAME container runtime Petabyte uses for customer
     workloads (docker run --gpus all --cap-drop ALL --security-opt no-new-privileges) —
     host-only detection is NOT accepted,
  3. run a BOUNDED PyTorch matmul loop in that container long enough for monitoring to catch
     multiple samples (explicit timeout, memory limit, --rm cleanup, NO host fallback),
  4. sample nvidia-smi utilization repeatedly DURING the workload,
  5. assert peak utilization exceeds SMOKE_MIN_GPU_UTILIZATION (default 20),
  6. confirm the container did not leak after completion.

If no GPU / Docker / NVIDIA runtime is available this does NOT fake PASS: it reports
EXTERNAL_GPU_TEST_REQUIRED and exits 0 — UNLESS SMOKE_GPU_REQUIRED=1 (a seller box that is
configured for GPU), in which case a missing/unusable GPU is a hard FAIL.

Config (env):
  SMOKE_MIN_GPU_UTILIZATION=20   SMOKE_GPU_WORKLOAD_S=8   SMOKE_GPU_TIMEOUT_S=180
  SMOKE_GPU_MATRIX=4096   SMOKE_GPU_MEM_LIMIT=4g   SMOKE_GPU_REQUIRED=0
  SMOKE_GPU_IMAGE=pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(REPO, "artifacts")
NAME = "pb-smoke-gpu"

CFG = {
    "min_util": float(os.getenv("SMOKE_MIN_GPU_UTILIZATION", "20")),
    "workload_s": float(os.getenv("SMOKE_GPU_WORKLOAD_S", "8")),
    "timeout_s": float(os.getenv("SMOKE_GPU_TIMEOUT_S", "180")),
    "matrix": int(os.getenv("SMOKE_GPU_MATRIX", "4096")),
    "mem_limit": os.getenv("SMOKE_GPU_MEM_LIMIT", "4g"),
    "required": os.getenv("SMOKE_GPU_REQUIRED", "0") == "1",
    "image": os.getenv("SMOKE_GPU_IMAGE", "pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime"),
}


def _run(cmd, timeout=30):
    """Run a command, but NEVER raise on timeout/missing-binary. A cold multi-GB image pull
    can exceed the timeout; letting subprocess.TimeoutExpired propagate would abort the smoke
    run before any report is written. Surface it instead as a non-zero result the callers
    already handle, so a report is always produced."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.output.decode() if isinstance(e.output, bytes) else (e.output or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return subprocess.CompletedProcess(
            cmd, 124, out, (err + f"\n[command timed out after {timeout}s]").strip())
    except (FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _have(bin_):
    return shutil.which(bin_) is not None


def host_gpu():
    if not _have("nvidia-smi"):
        return None
    try:
        r = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                  "--format=csv,noheader,nounits"])
        if r.returncode != 0 or not r.stdout.strip():
            return None
        gpus = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
        return gpus
    except Exception:
        return None


def container_sees_gpu():
    """Verify the GPU is visible INSIDE the Petabyte workload runtime (not host-only).
    Returns (ok, detail); detail surfaces a pull timeout / toolkit error for the report."""
    r = _run(["docker", "run", "--rm", "--gpus", "all",
              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
              CFG["image"], "nvidia-smi", "-L"], timeout=CFG["timeout_s"])
    ok = r.returncode == 0 and "GPU" in (r.stdout or "")
    detail = "" if ok else (r.stderr or r.stdout or "")[-300:]
    return ok, detail


_WORKLOAD = (
    "import torch, time\n"
    "assert torch.cuda.is_available(), 'CUDA not visible in container'\n"
    "n=%d; dur=%f\n"
    "a=torch.randn(n,n,device='cuda'); b=torch.randn(n,n,device='cuda')\n"
    "t=time.time(); it=0\n"
    "while time.time()-t < dur:\n"
    "    c=a@b; torch.cuda.synchronize(); it+=1\n"
    "print('iters', it)\n"
)


def sample_gpu(stop_at, out):
    """Sample utilization.gpu + memory.used while the workload runs (host-side)."""
    while time.time() < stop_at and not out["done"]:
        try:
            r = _run(["nvidia-smi",
                      "--query-gpu=utilization.gpu,memory.used,memory.total",
                      "--format=csv,noheader,nounits"], timeout=5)
            for ln in (r.stdout or "").strip().splitlines():
                parts = [p.strip() for p in ln.split(",")]
                if len(parts) >= 2:
                    out["util"].append(float(parts[0]))
                    out["mem_used"].append(float(parts[1]))
        except Exception:
            pass
        time.sleep(0.5)


def run_gpu_workload():
    import threading
    # start the bounded workload as a named container (so we can sample + verify cleanup)
    cmd = ["docker", "run", "-d", "--name", NAME, "--gpus", "all",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--network", "none", "--memory", CFG["mem_limit"],
           CFG["image"], "python", "-c", _WORKLOAD % (CFG["matrix"], CFG["workload_s"])]
    start = time.time()
    r = _run(cmd, timeout=CFG["timeout_s"])
    if r.returncode != 0:
        return {"error": "container failed to start", "detail": (r.stderr or "")[-300:]}
    samples = {"util": [], "mem_used": [], "done": False}
    deadline = start + CFG["timeout_s"]
    th = threading.Thread(target=sample_gpu, args=(deadline, samples), daemon=True)
    th.start()
    # wait for the container to finish (bounded)
    exit_code, timed_out = None, False
    while time.time() < deadline:
        insp = _run(["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", NAME])
        st = (insp.stdout or "").strip().split()
        if st and st[0] == "false":
            exit_code = int(st[1]) if len(st) > 1 and st[1].isdigit() else None
            break
        time.sleep(0.5)
    else:
        timed_out = True
    samples["done"] = True
    th.join(timeout=3)
    duration = round(time.time() - start, 1)
    logs = _run(["docker", "logs", NAME]).stdout if not timed_out else ""
    # cleanup — remove the container and assert it does not leak
    _run(["docker", "rm", "-f", NAME])
    leaked = NAME in (_run(["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout or "")
    util = samples["util"]
    mem = samples["mem_used"]
    return {
        "duration_s": duration, "timed_out": timed_out, "exit_code": exit_code,
        "samples": len(util),
        "max_util": max(util) if util else 0.0,
        "avg_util": round(sum(util) / len(util), 1) if util else 0.0,
        "peak_mem_used_mib": max(mem) if mem else 0.0,
        "container_leaked": leaked, "logs_tail": (logs or "")[-200:],
    }


def _write(report):
    os.makedirs(ARTIFACTS, exist_ok=True)
    with open(os.path.join(ARTIFACTS, "SMOKE_GPU_REPORT.json"), "w") as f:
        json.dump(report, f, indent=2)


def main():
    report = {"tool": "smoke_gpu", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "min_util_threshold": CFG["min_util"], "image": CFG["image"]}
    try:
        return _execute(report)
    except Exception as e:  # noqa: BLE001 — never exit without a report on disk
        report.update({"status": "FAIL", "reason": f"unexpected error: {type(e).__name__}: {e}"})
        _write(report)
        print(f"FAIL: unexpected error: {type(e).__name__}: {e}")
        return 1


def _execute(report):
    gpus = host_gpu()
    docker_ok = _have("docker")
    # ---- honest skip when hardware/runtime is absent ----
    if not gpus or not docker_ok:
        reason = ("no NVIDIA GPU detected (nvidia-smi)" if not gpus
                  else "docker not available")
        report.update({"status": "EXTERNAL_GPU_TEST_REQUIRED", "reason": reason,
                       "gpu_detected": bool(gpus), "docker": docker_ok})
        _write(report)
        print(f"EXTERNAL_GPU_TEST_REQUIRED: {reason}")
        print("  This must be run on a Seller GPU machine with Docker + the NVIDIA "
              "container runtime. Not faking PASS.")
        if CFG["required"]:
            print("  SMOKE_GPU_REQUIRED=1 but no usable GPU -> FAIL")
            return 1
        return 0

    report["gpu_models"] = gpus
    report["gpu_count"] = len(gpus)
    print(f"host GPUs: {gpus}")

    # ---- GPU must be visible INSIDE the Petabyte workload runtime (no host-only) ----
    sees, sees_detail = container_sees_gpu()
    if not sees:
        report.update({"status": "FAIL", "reason": "GPU not visible inside the container "
                       "runtime (nvidia container toolkit missing / --gpus not honored / "
                       "image pull timed out)", "detail": sees_detail})
        _write(report)
        print("FAIL: GPU not visible inside the container runtime (no host fallback).")
        if sees_detail:
            print(f"  detail: {sees_detail}")
        return 1
    print("GPU visible inside the container runtime (--gpus all).")

    # ---- bounded in-container workload + live utilization sampling ----
    res = run_gpu_workload()
    report.update(res)
    if res.get("error"):
        report["status"] = "FAIL"
        _write(report)
        print(f"FAIL: {res['error']}: {res.get('detail','')}")
        return 1

    reasons = []
    if res["timed_out"]:
        reasons.append("workload timed out")
    if res["exit_code"] not in (0, None):
        reasons.append(f"workload exited unexpectedly (code {res['exit_code']})")
    if res["samples"] < 2:
        reasons.append("did not capture enough GPU samples")
    if res["max_util"] < CFG["min_util"]:
        reasons.append(f"peak GPU utilization {res['max_util']}% < {CFG['min_util']}% "
                       "(no genuine GPU work)")
    if res["container_leaked"]:
        reasons.append("workload container leaked after completion")

    report["status"] = "PASS" if not reasons else "FAIL"
    report["fail_reasons"] = reasons
    _write(report)
    print(f"\n=== GPU SMOKE {report['status']} ===")
    print(f"peak util={res['max_util']}%  avg util={res['avg_util']}%  "
          f"peak mem={res['peak_mem_used_mib']}MiB  duration={res['duration_s']}s  "
          f"samples={res['samples']}")
    for r in reasons:
        print(f"  FAIL: {r}")
    print("artifacts/SMOKE_GPU_REPORT.json")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
