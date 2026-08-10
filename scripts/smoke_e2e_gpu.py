#!/usr/bin/env python3
"""smoke_e2e_gpu.py — the full chain:

  BUYER LOAD -> PETABYTE API -> ROUTING -> CAPACITY RESERVATION -> SELLER AGENT
  -> ISOLATED CONTAINER -> ACTUAL GPU COMPUTE -> MEASURED GPU UTILIZATION -> RESULT
  -> BUYER -> CORRECT FINAL BOOKING / LEDGER STATE

Runs two real components and merges their evidence into artifacts/SMOKE_E2E_GPU_REPORT.json:
  1. scripts/smoke_load.py  — concurrent buyers through the REAL marketplace path under
     contention (capacity never oversold, ledger balanced, buyer isolation). Postgres for a
     real concurrency claim.
  2. scripts/smoke_gpu.py   — a bounded PyTorch matmul in the SAME container runtime the
     agent uses, with measured GPU utilization.

On a Seller GPU host (Docker + NVIDIA runtime) both run for real. On a runner without a GPU,
the load half still runs and the GPU half is reported EXTERNAL_GPU_TEST_REQUIRED — never a
fake PASS. To PROVE buyer load *causes* GPU load end to end, run smoke_load against a local
API that a REAL seller agent is connected to on the GPU box (see docs/TESTING_EXCHANGE.md):
the agent claims the buyer's job and runs it in a GPU container while smoke_gpu-style
sampling records utilization during the job's running interval.

FINAL PASS = load PASS AND (gpu PASS OR EXTERNAL_GPU_TEST_REQUIRED unless SMOKE_GPU_REQUIRED=1).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS = os.path.join(REPO, "artifacts")
PY = sys.executable


def _run(script):
    print(f"\n===== running {script} =====")
    p = subprocess.run([PY, os.path.join("scripts", script)], cwd=REPO)
    return p.returncode


def _load(name):
    p = os.path.join(ARTIFACTS, name)
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def _clear(name):
    """Remove a stale report so a run can only ever read the report IT produced. Without this,
    a crashed sub-run would leave last run's report on disk and we'd read a false PASS."""
    try:
        os.remove(os.path.join(ARTIFACTS, name))
    except OSError:
        pass


def main():
    # Never trust a report from a previous run: delete both before we start, so a sub-run that
    # crashes without writing leaves NO report and is scored as a failure, not a stale pass.
    os.makedirs(ARTIFACTS, exist_ok=True)
    _clear("SMOKE_LOAD_REPORT.json")
    _clear("SMOKE_GPU_REPORT.json")

    load_rc = _run("smoke_load.py")
    gpu_rc = _run("smoke_gpu.py")
    load = _load("SMOKE_LOAD_REPORT.json")
    gpu = _load("SMOKE_GPU_REPORT.json")

    gpu_status = gpu.get("status", "UNKNOWN")
    gpu_required = os.getenv("SMOKE_GPU_REQUIRED", "0") == "1"
    # A report is only trusted if the sub-run actually produced one THIS run (dict non-empty)
    # AND its exit code agrees. A missing report (crash) or non-zero exit is never a pass.
    load_pass = bool(load) and load.get("final") == "PASS" and load_rc == 0
    gpu_ok = (bool(gpu) and gpu_status == "PASS" and gpu_rc == 0) or \
             (bool(gpu) and gpu_status == "EXTERNAL_GPU_TEST_REQUIRED"
              and gpu_rc == 0 and not gpu_required)
    final = "PASS" if (load_pass and gpu_ok) else "FAIL"

    report = {
        "tool": "smoke_e2e_gpu",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chain": "buyer_load -> api -> routing -> capacity -> seller -> container -> "
                 "gpu_compute -> measured_utilization -> result -> ledger",
        "load": {"final": load.get("final"),
                 "buyer": load.get("buyer"), "seller": load.get("seller"),
                 "invariants": load.get("invariants"), "caveats": load.get("caveats")},
        "gpu": gpu,
        "gpu_hardware_executed": gpu_status == "PASS" and gpu_rc == 0,
        "external_gpu_test_required": gpu_status == "EXTERNAL_GPU_TEST_REQUIRED",
        "exit_codes": {"smoke_load": load_rc, "smoke_gpu": gpu_rc},
        "final": final,
    }
    os.makedirs(ARTIFACTS, exist_ok=True)
    with open(os.path.join(ARTIFACTS, "SMOKE_E2E_GPU_REPORT.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("\n=========== E2E GPU SMOKE ===========")
    print(f"load: {load.get('final')}  ·  gpu: {gpu_status}  ·  FINAL: {final}")
    if gpu_status == "EXTERNAL_GPU_TEST_REQUIRED":
        print("  NOTE: GPU hardware assertion was NOT executed here — run on a Seller GPU box "
              "(EXTERNAL_GPU_TEST_REQUIRED). The load/marketplace half was proven.")
    print("artifacts/SMOKE_E2E_GPU_REPORT.json")
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
