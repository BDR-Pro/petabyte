"""sandbox_test.py — the buyer-job containers protect the SELLER's machine.

A buyer's workload runs on the seller's hardware. These tests assert the agent launches
EVERY buyer container with the notebook-grade hardening flags (drop all Linux capabilities,
no-new-privileges, pids/mem caps) and the right network posture, so a malicious job cannot
reconfigure the host firewall, escalate, pivot into the LAN, or steal cloud-metadata creds.

Offline: heavy agent deps (crypto/notebook/vm/telemetry) are stubbed so we can import the
real task loop and inspect the exact docker argv it builds. No docker, no network, no GPU.

Run: python sandbox_test.py
"""
import os
import sys
import types
import inspect

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# task_fetcher exits at import unless the node identity is present (it's a real agent).
os.environ.setdefault("PETABYTE_API_URL", "https://test.local")
os.environ.setdefault("PETABYTE_API_KEY", "pk_test")
os.environ.setdefault("PETABYTE_SPEC_ID", "1")

# Stub the heavy/local deps so `import task_fetcher` succeeds without them.
for _name in ("crypto", "notebook", "vm", "agent_telemetry"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["crypto"].sign_proof = lambda p: "sig"
sys.modules["notebook"].run_notebook_code = lambda *a, **k: []
sys.modules["vm"].launch_vm_task = lambda *a, **k: None

import task_fetcher as tf   # noqa: E402  (the real Linux-agent task loop)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


# ---------------------------------------------------------------- _isolation_flags
base = tf._isolation_flags({})
ok("isolation drops ALL capabilities", "--cap-drop" in base and "ALL" in base)
ok("isolation sets no-new-privileges",
   "no-new-privileges" in base and "--security-opt" in base)
ok("isolation caps pids", "--pids-limit" in base)
# Fail-safe: with no server-sized limits, a CONSERVATIVE host-derived default cap is applied
# (never "no cap"), so a buyer container can't OOM-kill the host/agent or pin every CPU (audit H6).
ok("isolation applies a fail-safe memory+cpu cap when the booking sends none",
   "--memory" in base and "--cpus" in base)

sized = tf._isolation_flags({"memory": "8g", "cpus": 2, "pids": 512})
ok("isolation caps memory + disables swap escape when sized",
   sized.count("8g") == 2 and "--memory" in sized and "--memory-swap" in sized)
ok("isolation caps cpus when sized", "--cpus" in sized and "2" in sized)
ok("isolation honours a per-task pids limit", "512" in sized)


# ---------------------------------------------------------------- _egress_flags
ok("egress default is CLOSED (no network)",
   tf._egress_flags({}) == ["--network", "none"])
ok("egress 'none' is closed",
   tf._egress_flags({"egress": "none"}) == ["--network", "none"])
ok("egress unknown policy fails closed",
   tf._egress_flags({"egress": "bogus"}) == ["--network", "none"])
ok("egress 'limited' opens the socket (host firewall blocks metadata/LAN)",
   tf._egress_flags({"egress": "limited"}) == [])


# ---------------------------------------------------------------- per-runner wiring
def src(fn):
    return inspect.getsource(getattr(tf, fn))


for runner in ("_run_render", "_run_transcode", "_run_template"):
    ok(f"{runner} applies the isolation flags", "_isolation_flags(task)" in src(runner))
ok("stitch concat container runs with --network none (no ffmpeg SSRF/exfil)",
   '"--network", "none"' in src("_run_stitch") and "_isolation_flags(task)" in src("_run_stitch"))
ok("render disables Blender embedded-script auto-exec",
   "--disable-autoexec" in src("_run_render"))
ok("template still publishes to loopback only (not 0.0.0.0)",
   '127.0.0.1:{port}' in src("_run_template") or "127.0.0.1" in src("_run_template"))


# ---------------------------------------------------------------- desktop agent parity
desk = open(os.path.join(ROOT, "desktop-app", "task_fetcher.py")).read()
ok("desktop template binds the port to 127.0.0.1 (was 0.0.0.0)", "127.0.0.1:{port}" in desk)
ok("desktop template applies isolation + egress flags",
   "_isolation_flags(task)" in desk and "_egress_flags(task)" in desk)
ok("desktop render/transcode/stitch apply isolation flags",
   desk.count("_isolation_flags(task)") >= 4)
ok("desktop defines the hardening helpers", "def _isolation_flags" in desk and "--cap-drop" in desk)


# ---------------------------------------------------------------- host egress firewall
inst = open(os.path.join(HERE, "install.sh")).read()
ok("install.sh installs a DOCKER-USER egress firewall", "DOCKER-USER" in inst and "PB-EGRESS" in inst)
ok("firewall DROPs the cloud metadata endpoint (169.254.0.0/16)",
   "169.254.0.0/16" in inst and "-j DROP" in inst)
ok("firewall DROPs the seller's private LAN (10/8 + 192.168/16)",
   "10.0.0.0/8" in inst and "192.168.0.0/16" in inst)
ok("egress lockdown is re-applied on boot (survives docker restart)",
   "petabyte-egress.service" in inst and "After=docker.service" in inst)


# ---------------------------------------------------------------- result binds to output bytes
sr = tf._signed_result(7, status="completed", result="s3://b/out.tar", content_hash="a" * 64)
ok("a completed result carries the content_hash INSIDE the signed proof",
   sr["proof"].get("content_hash") == "a" * 64 and "signature" in sr)
ok("content_hash is the sha256 of real output bytes (render/transcode/stitch pass it)",
   src("_run_render").count("hashlib.sha256(raw)") >= 1
   and "hashlib.sha256(raw)" in src("_run_transcode")
   and "hashlib.sha256(raw)" in src("_run_stitch"))
_desk = open(os.path.join(ROOT, "desktop-app", "task_fetcher.py")).read()
ok("desktop agent also binds results to real output bytes",
   "content_hash=hashlib.sha256(raw)" in _desk and _desk.count("hashlib.sha256(raw)") >= 3)


# ---------------------------------------------------------------- benchmark authenticity
ok("agent measures FP16 matmul TFLOPS on-device (not an env stub)",
   hasattr(tf, "_measure_fp16_tflops") and "tflops_fp16" in src("_run_benchmark"))
ok("agent runs the real Blender Open Data benchmark (workload-relevant)",
   hasattr(tf, "_measure_blender_score") and "benchmark-launcher-cli" in src("_measure_blender_score")
   and "blender_optix" in src("_run_benchmark"))
ok("benchmark scores go INSIDE the signed proof (attributable, not bare meta)",
   "**metrics" in src("_run_benchmark") and "crypto.sign_proof(proof)" in src("_run_benchmark"))
ok("agent answers the server's FRESH proof-of-work challenge (anti-fabrication/replay)",
   "bench_seed" in src("_run_benchmark") and "compute_test_hash" in src("_run_benchmark")
   and "challenge_hash" in src("_run_benchmark"))
ok("benchmark measurement never crashes the agent (guarded)",
   all("except Exception" in src(fn) and "return None" in src(fn)
       for fn in ("_measure_fp16_tflops", "_measure_blender_score")))


print(f"\n=== sandbox: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
