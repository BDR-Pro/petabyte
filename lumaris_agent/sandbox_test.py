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
ok("isolation adds NO memory/cpu cap when the booking sends none",
   "--memory" not in base and "--cpus" not in base)

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


print(f"\n=== sandbox: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
