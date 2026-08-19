"""Petabyte agent task loop.

Talks to the hardened API:
  - POST /heartbeat        (liveness for the spec this node serves)
  - GET  /jobs/next        (claim a job for hardware we own)
  - POST /jobs/result      (notebook result)
  - POST /jobs/vm_details  (vm connection info)

Auth is the real encrypted API key (X-API-KEY). Heartbeat runs on its own thread
so a long-running job never makes the node look offline (which would get it reaped).
"""
import hashlib
import logging
import os
import threading
import time

import time as _t

import httpx

import crypto
from notebook import run_notebook_code
from vm import launch_vm_task
import agent_telemetry as _tel

try:
    import console as _con                            # pretty seller-facing console feed
except Exception:                                     # noqa: BLE001 — never block the agent
    _con = None


def _safe_ext(v, default="mp4"):
    """Sanitize a buyer-supplied container/extension before it is joined into a HOST path.
    Defense-in-depth: the API validates this too, but the agent runs as root, so a value like
    '../../../etc/cron.d/x' must never reach os.path.join on the seller's filesystem."""
    import os as _o
    import re as _r
    v = _o.path.basename(str(v if v is not None else default)).lstrip(".").lower()
    return v if _r.match(r"^[a-z0-9]{1,8}$", v) else default

# Console output IS the user feed now, so keep the root logger quiet (WARNING+); the pretty
# lines carry the routine story, logging carries problems.
logging.basicConfig(level=logging.WARNING, format="[%(asctime)s] %(levelname)s: %(message)s")
_earn = {"shown": False}                              # latest earnings forecast from heartbeat

# ONE computer == ONE agent process == ONE API key + ONE spec. A single user can run as MANY
# computers as they own: each machine runs its own agent with its OWN PETABYTE_API_KEY (minted
# per machine at /create_api_key) and its OWN PETABYTE_SPEC_ID. The platform treats each spec as a
# distinct machine, so one account's computers can even be gang-scheduled together into one
# distributed cluster (anti_affinity is per-machine — see router.select_plan / /distributed).
API_URL = os.getenv("PETABYTE_API_URL")        # e.g. https://petabyte.market
API_KEY = os.getenv("PETABYTE_API_KEY")        # this machine's encrypted key from POST /create_api_key
SPEC_ID = os.getenv("PETABYTE_SPEC_ID")        # the spec (machine) this agent serves
HEARTBEAT_S = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
POLL_S = int(os.getenv("JOB_POLL_INTERVAL", "5"))

if not API_URL or not API_KEY or not SPEC_ID:
    raise SystemExit("Set PETABYTE_API_URL, PETABYTE_API_KEY and PETABYTE_SPEC_ID")

HEADERS = {"X-API-KEY": API_KEY}


def _set_ui(status=None, task=None, ok=None, fail=None):
    try:
        import ui
        if status is not None:
            ui.agent_status["status"] = status
        if task is not None:
            ui.agent_status["current_task"] = task
        if ok:
            ui.agent_status["tasks_completed"] = ui.agent_status.get("tasks_completed", 0) + 1
        if fail:
            ui.agent_status["tasks_failed"] = ui.agent_status.get("tasks_failed", 0) + 1
    except Exception:
        pass


def heartbeat_loop():
    while True:
        try:
            r = httpx.post(f"{API_URL}/heartbeat", json={"spec_id": int(SPEC_ID)},
                           headers=HEADERS, timeout=10)
            if r.status_code == 200:
                _body = r.json()
                _platform_idle["enabled"] = bool(_body.get("idle_fallback"))
                # Spare-disk rental runs ALONGSIDE paid jobs (disk != GPU) — drive it from the
                # heartbeat, not the job loop. The server sends the current config each beat.
                _apply_disk_cfg(_body.get("disk"))
                # Live earnings forecast: show it once under the banner, and expose it to the
                # desktop dashboard via the shared ui.agent_status dict.
                _e = _body.get("earnings")
                if _e:
                    try:
                        import ui as _ui
                        _ui.agent_status["earnings"] = _e
                    except Exception:
                        pass
                    if _con and not _earn["shown"]:
                        _earn["shown"] = True
                        _con.earnings(_e.get("net_per_hour", 0.0),
                                      _e.get("estimated_daily_usd_low", 0.0),
                                      _e.get("estimated_daily_usd_high", 0.0),
                                      _e.get("idle_mining_daily_usd", 0.0))
                        _con.ready(POLL_S)
                _tel.event(_tel.EVENTS.HEARTBEAT, message="heartbeat ok", status_code=200)
            else:
                logging.warning(f"heartbeat {r.status_code}: {r.text[:200]}")
                _tel.event(_tel.EVENTS.HEARTBEAT_MISSED, message="heartbeat non-200",
                           status_code=r.status_code)
        except Exception as e:                          # noqa: BLE001
            logging.error(f"heartbeat error: {e}")
            _tel.event(_tel.EVENTS.HEARTBEAT_MISSED, message="heartbeat error",
                       reason=str(e)[:120])
        time.sleep(HEARTBEAT_S)


def _submit_signed(tid, output_hash, result=None, status="completed"):
    proof = {"task_id": tid, "output_hash": output_hash, "ts": int(_t.time())}
    httpx.post(f"{API_URL}/jobs/result", headers=HEADERS, timeout=15, json={
        "task_id": tid, "result": result, "status": status,
        "proof": proof, "signature": crypto.sign_proof(proof)})


def _run_notebook(task):
    tid = task["task_id"]
    _set_ui(status="running", task=f"Notebook #{tid}")
    code = task.get("code", "")
    try:
        import json as _json
        code = _json.loads(code).get("code", code) if code.strip().startswith("{") else code
    except Exception:
        pass
    result = run_notebook_code(code, max_runtime_s=task.get("max_runtime_s"))
    try:
        _submit_signed(tid, crypto.sha256_hex(result), result=_to_str(result))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        logging.error(f"submit result error: {e}")
        _set_ui(status="idle", task=None, fail=True)


def _run_test(task):
    """Known-answer test: compute the deterministic hash and submit it signed."""
    tid = task["task_id"]
    _set_ui(status="running", task=f"Test #{tid}")
    try:
        h = crypto.compute_test_hash(int(task["size"]), int(task["seed"]))
        _submit_signed(tid, h)
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        logging.error(f"test error: {e}")
        _set_ui(status="idle", task=None, fail=True)


def _run_vm(task):
    tid = task["task_id"]
    _set_ui(status="running", task=f"VM #{tid}")
    try:
        details = launch_vm_task(task_id=tid, vm_type=task.get("vm_type", "docker"),
                                 cpu=task.get("cpu") or 2, ram=task.get("ram") or 2,
                                 cuda=bool(task.get("cuda")))
        httpx.post(f"{API_URL}/jobs/vm_details", headers=HEADERS, timeout=15, json={
            "task_id": tid, "vm_type": details.get("vm_type", "unknown"),
            "vm_id": details.get("vm_id", ""), "ip_address": details.get("ip_address"),
            "port": details.get("port"), "connection_string": details.get("connection_string"),
            "status": details.get("status", "running")})
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        logging.error(f"vm task error: {e}")
        _set_ui(status="idle", task=None, fail=True)


def _to_str(obj):
    import json
    return obj if isinstance(obj, str) else json.dumps(obj)


def _post(path, payload):
    try:
        httpx.post(f"{API_URL}{path}", headers=HEADERS, json=payload, timeout=15)
    except Exception as e:                              # noqa: BLE001
        logging.error(f"{path} error: {e}")


def report_progress(task_id, percent, message=""):
    _post("/jobs/progress", {"task_id": task_id, "percent": percent, "message": message})


def report_log(task_id, line):
    _post("/jobs/log", {"task_id": task_id, "line": line})


def _restore_volume(volume, restore_ref, task_id):
    """Download via a pre-signed GET URL, VERIFY the signed hash, decrypt, restore."""
    if not restore_ref:
        return
    try:
        import hashlib, subprocess, os as _os
        from cryptography.fernet import Fernet
        g = httpx.post(f"{API_URL}/jobs/restore_url", headers=HEADERS, timeout=15,
                       json={"task_id": task_id, "snapshot_ref": restore_ref}).json()
        enc = httpx.get(g["download_url"], timeout=300).content
        if g.get("content_hash") and hashlib.sha256(enc).hexdigest() != g["content_hash"]:
            report_log(task_id, "RESTORE INTEGRITY CHECK FAILED — aborting")
            return
        data = Fernet(g["enc_key"].encode()).decrypt(enc)      # client-side decrypt
        _os.makedirs(f"/var/lib/petabyte/vol/{volume}", exist_ok=True)
        local = f"/tmp/{volume}-restore.tar"
        open(local, "wb").write(data)
        subprocess.check_call(["tar", "-xf", local, "-C", f"/var/lib/petabyte/vol/{volume}"])
        report_log(task_id, f"restored {volume} from {restore_ref} (verified)")
    except Exception as e:                              # noqa: BLE001
        logging.error(f"restore failed: {e}")


def _backup_once(task, volume):
    """Snapshot -> encrypt -> upload via a one-object pre-signed PUT -> sign checkpoint.
    The node holds NO standing object-storage credentials."""
    tid = task["task_id"]
    try:
        import subprocess, hashlib, time as _tt
        from cryptography.fernet import Fernet
        local = f"/tmp/{volume}-{int(_tt.time())}.tar"
        subprocess.check_call(["tar", "-cf", local,
                               "-C", f"/var/lib/petabyte/vol/{volume}", "."])
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid,
                                 "filename": f"{volume}-{int(_tt.time())}.tar.enc"}).json()
        enc = Fernet(grant["enc_key"].encode()).encrypt(open(local, "rb").read())
        httpx.put(grant["upload_url"], content=enc, timeout=300)
        h = hashlib.sha256(enc).hexdigest()             # hash of the uploaded bytes
        proof = {"task_id": tid, "output_hash": h[:16], "ts": int(_tt.time())}
        _post("/jobs/checkpoint", {"task_id": tid, "snapshot_ref": grant["snapshot_ref"],
                                   "size_bytes": len(enc), "content_hash": h,
                                   "proof": proof, "signature": crypto.sign_proof(proof)})
        report_log(tid, f"backup -> {grant['snapshot_ref']} ({len(enc)} bytes, encrypted)")
    except Exception as e:                              # noqa: BLE001
        logging.error(f"backup failed: {e}")


def _start_backup_thread(task):
    """Periodic backups for a stateful task (recovery point = interval)."""
    if not task.get("backup_enabled"):
        return None
    interval = max(30, int(task.get("backup_interval_s") or 300))
    volume = task.get("volume") or "task-data"
    stop = threading.Event()
    def loop():
        while not stop.wait(interval):
            _backup_once(task, volume)
    threading.Thread(target=loop, daemon=True).start()
    return stop


def _egress_flags(task):
    """Apply the template's egress policy.

    This exists to protect the SELLER, not the buyer. The container runs on someone's
    home connection, behind their IP. If a workload spams, scans, or joins a botnet,
    it is the host who gets the abuse complaint and the host who can lose their
    internet. So the default is NO NETWORK, and a template must explicitly ask for
    more.

      none    -> --network none          (batch work needs nothing)
      limited -> outbound ok, inbound only via the tunnel on the service port
      open    -> unrestricted (highest risk to the host; used only where unavoidable)
    """
    policy = (task.get("egress") or "none").lower()
    if policy == "none":
        return ["--network", "none"]
    if policy == "cluster":
        # A distributed rank must reach the OTHER ranks over the WireGuard mesh (and be reachable
        # on the rendezvous/master port). We share the host network namespace so the container can
        # use the wg0 interface directly. TRADE-OFF: --network host bypasses the DOCKER-USER egress
        # firewall install.sh installs for bridged jobs, so cluster jobs are more trusted than
        # batch jobs. HARDENING ROADMAP: attach the container to a dedicated WG-only docker network
        # (macvlan/ipvlan bound to wg0) so peers are reachable WITHOUT host-LAN exposure. Until
        # then, cluster jobs run on nodes the operator has opted into VPN (AGENT_VPN_ENABLED).
        return ["--network", "host"]
    if policy == "limited":
        # Outbound works for the service; inbound is unreachable because the port is
        # published to 127.0.0.1 only and the ONLY way in is the reverse tunnel we
        # control. The dangerous outbound targets — the cloud metadata endpoint
        # (169.254.169.254, IAM cred theft) and the seller's own LAN (RFC-1918) — are
        # DROPPED by the host firewall installed by install.sh (DOCKER-USER chain).
        # The job cannot undo those rules because _isolation_flags drops NET_ADMIN/RAW.
        # See docs/egress.md.
        return []
    if policy == "open":
        return []
    return ["--network", "none"]               # unknown policy -> closed


def _host_ram_bytes():
    try:
        import os as _o
        return _o.sysconf("SC_PAGE_SIZE") * _o.sysconf("SC_PHYS_PAGES")
    except Exception:                                    # noqa: BLE001
        return 0


def _default_mem_cap():
    """A conservative RAM cap for a job the server didn't size: total host RAM minus a headroom
    reserve, so a runaway container can't OOM-kill the agent/host. None on hosts we can't measure
    (e.g. non-Linux desktop, where Docker Desktop's own VM already bounds container memory)."""
    total = _host_ram_bytes()
    if total <= 0:
        return None
    reserve = 2 * 1024 ** 3                              # keep ~2 GiB for the host + agent
    return str(max(1024 ** 3, total - reserve)) + "b"   # never below 1 GiB


def _default_cpu_cap():
    """Leave the host at least one core so a job can't peg every CPU and starve the agent."""
    try:
        import os as _o
        n = _o.cpu_count() or 1
    except Exception:                                    # noqa: BLE001
        return None
    return str(max(1, n - 1))


def _isolation_flags(task):
    """Hardening flags applied to EVERY buyer container — this protects the SELLER's
    host from the buyer's workload (see docs/isolation-roadmap.md).

    Mirrors the notebook sandbox (notebook.py):
      * --cap-drop ALL              — the job gets NO Linux capabilities, so it cannot
                                       add routes / reconfigure the host firewall
                                       (NET_ADMIN, NET_RAW), load kernel modules
                                       (SYS_MODULE), or otherwise escalate. This is
                                       also what makes the host egress firewall
                                       (install.sh DOCKER-USER rules) un-bypassable
                                       from inside a job.
      * --security-opt no-new-privileges — no setuid escalation.
      * --pids-limit                — fork-bomb cap.
      * --memory/--memory-swap/--cpus — sized to the booking when the server sends them
                                       (never guessed high, so a big legit rental isn't
                                       throttled; absent -> only the pids cap applies).
    gVisor (runsc) is used as a user-space kernel boundary when installed. GPU jobs keep
    device access (the NVIDIA runtime injects the device via cgroups, not capabilities),
    so dropping ALL caps does not break --gpus.

    STRICT ROOTFS (opt-in via the server's AGENT_STRICT_ROOTFS / AGENT_CONTAINER_USER):
      * read_only -> --read-only (immutable rootfs) + a small writable /tmp tmpfs + HOME=/tmp,
        so a workload's own caches (pip, torch/CUDA JIT, ~/.cache) still land somewhere writable
        without persisting to — or tampering with — the image. This is the CIS/PodSecurity
        "restricted" baseline the notebook sandbox (notebook.py) already runs unconditionally.
      * run_as  -> --user, forcing the job non-root.
    Both default OFF: unlike the notebook path (which owns its image), a buyer job runs an
    ARBITRARY image — an s6-overlay server, a cache-writing model server — that may not tolerate a
    read-only rootfs or a forced UID. Operators flip these on once they've validated their image
    mix; the default profile is byte-for-byte the pre-existing hardening.
    """
    import subprocess
    flags = ["--cap-drop", "ALL",
             "--security-opt", "no-new-privileges",
             "--pids-limit", str(task.get("pids") or 1024)]
    # RAM/CPU caps: sized to the booking when the server sends them; otherwise fall back to a
    # CONSERVATIVE host-derived default (never "no cap"). Without this a buyer container could
    # allocate all host RAM and OOM-kill the seller's box + the agent, or pin every CPU (H6).
    mem = task.get("memory") or _default_mem_cap()
    if mem:
        flags += ["--memory", str(mem), "--memory-swap", str(mem)]   # cap RAM; no swap escape
    cpus = task.get("cpus") or _default_cpu_cap()
    if cpus:
        flags += ["--cpus", str(cpus)]
    if task.get("read_only"):
        # Immutable rootfs + a writable scratch. The tmpfs counts against the RAM cap, so keep it
        # modest; HOME=/tmp routes user/CUDA/pip caches onto it instead of the read-only rootfs.
        flags += ["--read-only",
                  "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
                  "-e", "HOME=/tmp"]
    run_as = task.get("run_as")
    if run_as:
        flags += ["--user", str(run_as)]   # force non-root (the image must tolerate the UID)
    try:
        info = subprocess.check_output(["docker", "info", "--format", "{{.Runtimes}}"],
                                       text=True, timeout=5)
        if "runsc" in info:
            flags = ["--runtime", "runsc"] + flags   # gVisor user-space kernel
    except Exception:
        pass
    return flags


def _run_template(task):
    """Launch a one-click stack (Ollama/vLLM/ComfyUI/game server/...) and report it."""
    tid = task["task_id"]
    _set_ui(status="running", task=f"Template {task.get('template')} #{tid}")
    _restore_volume(task.get("volume"), task.get("restore_from"), task["task_id"])
    _start_backup_thread(task)
    image = task.get("image"); port = task.get("port")
    params = task.get("params", {})
    report_progress(tid, 10, f"pulling {image}")
    import shutil, subprocess, uuid as _uuid
    if not shutil.which("docker"):
        _post("/jobs/vm_details", {"task_id": tid, "vm_type": "template", "vm_id": "",
                                   "status": "failed"})
        return
    name = f"pb-{task.get('template')}-{_uuid.uuid4().hex[:8]}"
    cmd = ["docker", "run", "-d", "--name", name]
    if port:                                    # only publish a port for SERVING templates
        cmd += ["-p", f"127.0.0.1:{port}:{port}"]   # (never -p …:0:0 for a batch template)
    cmd += _isolation_flags(task)              # Phase-1 sandbox (gVisor if present)
    cmd += _egress_flags(task)                 # protect the HOST's home internet
    if task.get("gpu"):
        cmd += ["--gpus", "all"]
    if task.get("cache"):
        cmd += ["-v", f"pb-cache-{task.get('template')}:{task['cache']}"]  # model caching
    model = params.get("model")
    if task.get("template") == "ollama" and model:
        cmd += ["-e", f"OLLAMA_MODEL={model}"]
    cmd += [image]
    if task.get("template") == "vllm" and model:
        cmd += ["--model", model]            # HF model id; cached on the named volume
    try:
        cid = subprocess.check_output(cmd, text=True).strip()
        report_progress(tid, 100, "running")
        _post("/jobs/vm_details", {"task_id": tid, "vm_type": "template", "vm_id": cid[:12],
                                   "port": port, "connection_string": f"http://<node-ip>:{port}",
                                   "status": "running"})
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"launch failed: {e}")
        _post("/jobs/vm_details", {"task_id": tid, "vm_type": "template", "vm_id": "",
                                   "status": "failed"})
        _set_ui(status="idle", task=None, fail=True)


def _measure_fp16_tflops():
    """Achieved FP16 dense matmul throughput (TFLOPS) on THIS GPU, server-comparable.

    This is the gamer-style authenticity number: a hardware-invariant a genuine card
    can reach and a weaker card physically cannot. The server compares it to the
    published spec of the CLAIMED gpu_model (gpu_benchmark.classify) to catch a listing
    that over-claims its silicon. Returns None if torch/CUDA is unavailable (older
    agents just omit it — the server then records the number without a verdict)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        n = int(os.getenv("BENCH_MATMUL_N", "8192"))
        a = torch.randn(n, n, device="cuda", dtype=torch.float16)
        b = torch.randn(n, n, device="cuda", dtype=torch.float16)
        for _ in range(3):                      # warm up clocks + cuBLAS autotune
            _c = a @ b
        torch.cuda.synchronize()
        iters = int(os.getenv("BENCH_MATMUL_ITERS", "30"))
        t0 = _t.time()
        for _ in range(iters):
            _c = a @ b
        torch.cuda.synchronize()
        dt = _t.time() - t0
        if dt <= 0:
            return None
        flops = 2.0 * (n ** 3) * iters          # 2*N^3 per matmul
        return round(flops / dt / 1e12, 1)      # TFLOPS
    except Exception:                            # noqa: BLE001 — never crash the agent
        return None


def _measure_blender_score():
    """Blender Open Data score (OptiX, sum of standard-scene samples/min) via the OFFICIAL
    benchmark-launcher-cli when it's installed on the node.

    This is the workload-relevant authenticity number: Petabyte renders Blender, and
    opendata.blender.org publishes a per-GPU public median the server compares against
    (gpu_benchmark 'blender_optix'). Returns None if the CLI isn't present (the server then
    just skips the Blender check) — never crashes the agent."""
    import shutil, subprocess, json as _json
    cli = os.getenv("BLENDER_BENCH_CLI") or shutil.which("benchmark-launcher-cli")
    if not cli:
        return None
    try:
        scenes = [s for s in os.getenv("BLENDER_BENCH_SCENES", "classroom").split(",") if s]
        out = subprocess.run([cli, "benchmark", *scenes, "--device-type", "OPTIX",
                              "--json"], capture_output=True, text=True, timeout=1800)
        rows = _json.loads(out.stdout or "[]")
        total = 0.0
        for row in rows:                             # sum the scene medians -> Open Data score
            spm = (row.get("stats") or {}).get("samples_per_minute")
            if spm:
                total += float(spm)
        return round(total, 1) if total > 0 else None
    except Exception:                                # noqa: BLE001 — never crash the agent
        return None


def _run_benchmark(task):
    """Measure LLM tokens/sec + FP16 matmul TFLOPS + Blender Open Data, submit a SIGNED result.
    Every measured score goes INSIDE the signed proof so the server checks the attributable
    (non-repudiable) number, not a bare unsigned meta field."""
    tid = task["task_id"]
    _set_ui(status="running", task=f"Benchmark #{tid}")
    spec_id = int(os.getenv("PETABYTE_SPEC_ID"))
    report_progress(tid, 40, "benchmarking")
    # tokens/sec: a real node runs a fixed prompt through a local model and counts
    # generated tokens / wall-time. Hook your LLM harness here (env stub for now).
    tokens_sec = float(os.getenv("BENCH_TOKENS_SEC", "0"))
    # FP16 matmul TFLOPS: a hardware-invariant the server checks against the claimed model's
    # datasheet peak (the one metric allowed to freeze payouts on a gross over-claim).
    tflops = _measure_fp16_tflops()
    report_progress(tid, 70, f"fp16 matmul: {tflops} TFLOPS" if tflops else "benchmarking")
    # Blender Open Data: workload-relevant, public per-GPU medians (advisory signal).
    blender = _measure_blender_score()
    report_progress(tid, 90, f"blender: {blender}" if blender else "benchmarking")

    metrics = {}
    if tflops is not None:
        metrics["tflops_fp16"] = tflops
    if blender is not None:
        metrics["blender_optix"] = blender
    meta = {"harness": ",".join(metrics) or "stub", "metrics": list(metrics)}
    # scores live in the SIGNED proof (attributable); meta is freeform display.
    proof = {"task_id": tid, "output_hash": "benchmark", "ts": int(_t.time()), **metrics}
    # Answer the server's FRESH proof-of-work challenge (proves this benchmark is a real,
    # current computation on this node — not a pre-canned or replayed number).
    _seed, _size = task.get("bench_seed"), task.get("bench_size")
    if _seed is not None and _size is not None:
        try:
            proof["challenge_hash"] = crypto.compute_test_hash(int(_size), int(_seed))
        except Exception:                            # noqa: BLE001 — never crash the agent
            pass
    httpx.post(f"{API_URL}/jobs/benchmark_result", headers=HEADERS, timeout=20, json={
        "spec_id": spec_id, "tokens_sec": tokens_sec,
        "meta": meta, "proof": proof, "signature": crypto.sign_proof(proof)})
    _set_ui(status="idle", task=None, ok=True)


def _run_render(task):
    """Render an assigned frame range by launching Blender AS A CONTAINER.
    The seller never installs Blender — the image is pulled on demand and cached;
    the scene streams in and frames stream out via pre-signed URLs. No host binary."""
    tid = task["task_id"]
    fs, fe = task.get("frame_start"), task.get("frame_end")
    image = task.get("image", "linuxserver/blender:latest")
    _set_ui(status="running", task=f"Render #{tid} frames {fs}-{fe}")
    import shutil, subprocess, os as _os, tempfile, tarfile
    if not shutil.which("docker"):
        report_log(tid, "docker not installed; cannot run render sandbox")
        _post("/jobs/result", _signed_result(tid, status="failed"))
        return
    work = tempfile.mkdtemp(prefix=f"render-{tid}-")
    scene = _os.path.join(work, "scene.blend")
    out_dir = _os.path.join(work, "out"); _os.makedirs(out_dir, exist_ok=True)
    _os.chmod(out_dir, 0o777)   # forced non-root container writes frames; the 0700 parent tmpdir
    # keeps this world-writable leaf unreachable by any other host account
    try:
        # 1) pull the scene via a pre-signed GET (no standing creds on the node)
        g = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                       json={"task_id": tid, "ref": task.get("blend_ref", "")}).json()
        open(scene, "wb").write(httpx.get(g["download_url"], timeout=300).content)
        report_progress(tid, 15, f"scene fetched; rendering {fs}-{fe} in {image}")
        # 2) render inside the container (GPU via NVIDIA Container Toolkit).
        # --network none: batch render needs no network -> no exfil / LAN access.
        # _isolation_flags: cap-drop ALL etc. so a malicious .blend (Blender auto-runs
        # embedded Python) cannot escalate or touch the host. --disable-autoexec stops
        # the scene's embedded scripts from running at all.
        cmd = ["docker", "run", "--rm", "--network", "none"]
        cmd += _isolation_flags(task)
        cmd += ["-v", f"{scene}:/scene.blend:ro", "-v", f"{out_dir}:/out"]
        if task.get("gpu"):
            cmd += ["--gpus", "all"]
        cmd += [image, "blender", "-b", "/scene.blend", "--disable-autoexec",
                "-o", "/out/frame_", "-s", str(fs), "-e", str(fe), "-a"]
        # Hard-kill the container at the buyer's AUTHORIZED runtime budget (audit H1): a render
        # can't consume more of the seller's GPU than the buyer paid to authorize. --rm tears the
        # container down when the timed-out client is killed.
        _rt = task.get("max_runtime_s")
        subprocess.run(cmd, check=True, timeout=(int(_rt) if _rt else None))
        report_progress(tid, 85, "uploading frames")
        # 3) tar the frames and upload via a one-object pre-signed PUT
        bundle = _os.path.join(work, f"frames_{fs}_{fe}.tar")
        with tarfile.open(bundle, "w") as tf:
            tf.add(out_dir, arcname="frames")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": f"frames_{fs}_{fe}.tar"}).json()
        from cryptography.fernet import Fernet
        raw = open(bundle, "rb").read()
        enc = Fernet(grant["enc_key"].encode()).encrypt(raw)
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed",
                                             result=f"frames {fs}-{fe} -> {grant['snapshot_ref']}",
                                             content_hash=hashlib.sha256(raw).hexdigest()))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"render failed: {e}")
        _post("/jobs/result", _signed_result(tid, status="failed"))
        _set_ui(status="idle", task=None, fail=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_transcode(task):
    """Transcode an assigned time segment with FFmpeg IN A CONTAINER (NVENC if GPU).
    Seller installs nothing; the image is pulled on demand. Input/output via
    pre-signed URLs."""
    tid = task["task_id"]
    ss, se = task.get("start_time"), task.get("end_time")
    image = task.get("image", "jrottenberg/ffmpeg:6.1-nvidia")
    _set_ui(status="running", task=f"Transcode #{tid} seg {ss}-{se}")
    import shutil, subprocess, os as _os, tempfile
    if not shutil.which("docker"):
        _post("/jobs/result", _signed_result(tid, status="failed")); return
    outer = tempfile.mkdtemp(prefix=f"tc-{tid}-")   # 0700: only the agent user can traverse it
    work = _os.path.join(outer, "work"); _os.makedirs(work)
    # The forced non-root container user (AGENT_CONTAINER_USER) must write /work, so the
    # leaf is 0777 — but it is reachable only through the 0700 parent, so no other host
    # account can read buyer inputs or swap outputs before they are hashed + uploaded.
    _os.chmod(work, 0o777)
    src = _os.path.join(work, "in"); dst = _os.path.join(work, f"out.{_safe_ext(task.get('container'))}")
    try:
        g = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                       json={"task_id": tid, "ref": task.get("input_ref", "")}).json()
        open(src, "wb").write(httpx.get(g["download_url"], timeout=600).content)
        report_progress(tid, 20, "transcoding")
        vcodec = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"} \
            if task.get("gpu") else {"h264": "libx264", "h265": "libx265", "av1": "libaom-av1"}
        args = ["docker", "run", "--rm", "--network", "none"]
        args += _isolation_flags(task)
        args += ["-v", f"{src}:/in:ro", "-v", f"{work}:/work"]
        if task.get("gpu"):
            args += ["--gpus", "all"]
        ff = [image, "-y"]
        # keyframe-aware segment cut (seek before input for speed, re-encode for accuracy)
        if ss is not None and se is not None and se >= 0:
            ff += ["-ss", str(ss), "-to", str(se)]
        ff += ["-i", "/in", "-c:v", vcodec.get(task.get("codec", "h264"), "h264_nvenc")]
        if task.get("resolution"):
            ff += ["-s", task["resolution"]]
        if task.get("crf") is not None:
            ff += ["-crf", str(task["crf"])]
        elif task.get("bitrate"):
            ff += ["-b:v", task["bitrate"]]
        ff += [f"/work/{_os.path.basename(dst)}"]
        # Audit H1: hard-kill at the buyer's authorized runtime budget so a job can never
        # consume more of the seller's GPU than was paid to authorize.
        _rt = task.get("max_runtime_s")
        subprocess.run(args + ff, check=True, timeout=(int(_rt) if _rt else None))
        report_progress(tid, 80, "uploading")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": _os.path.basename(dst)}).json()
        from cryptography.fernet import Fernet
        raw = open(dst, "rb").read()
        enc = Fernet(grant["enc_key"].encode()).encrypt(raw)
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed", result=grant["snapshot_ref"],
                                             content_hash=hashlib.sha256(raw).hexdigest()))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"transcode failed: {e}")
        _post("/jobs/result", _signed_result(tid, status="failed"))
        _set_ui(status="idle", task=None, fail=True)
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def _run_stitch(task):
    """Assemble a fan-out job: concat transcode segments (or collect render frames)
    into one final output, uploaded via a pre-signed PUT."""
    tid = task["task_id"]
    refs = task.get("segment_refs", [])
    image = task.get("image", "jrottenberg/ffmpeg:6.1-nvidia")
    _set_ui(status="running", task=f"Assemble #{tid} ({len(refs)} parts)")
    import shutil, subprocess, os as _os, tempfile
    if not shutil.which("docker"):
        _post("/jobs/result", _signed_result(tid, status="failed")); return
    outer = tempfile.mkdtemp(prefix=f"stitch-{tid}-")   # 0700: only the agent user can traverse it
    work = _os.path.join(outer, "work"); _os.makedirs(work)
    # The forced non-root container user (AGENT_CONTAINER_USER) must write /work, so the
    # leaf is 0777 — but it is reachable only through the 0700 parent, so no other host
    # account can read buyer inputs or swap outputs before they are hashed + uploaded.
    _os.chmod(work, 0o777)
    try:
        # pull each segment via a restore-style GET, concat with ffmpeg
        listfile = _os.path.join(work, "list.txt")
        with open(listfile, "w") as lf:
            for i, ref in enumerate(refs):
                gg = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                                json={"task_id": tid, "ref": ref}).json()
                p = _os.path.join(work, f"seg{i}.{_safe_ext(task.get('container'))}")
                open(p, "wb").write(httpx.get(gg["download_url"], timeout=600).content)
                lf.write(f"file '{p}'\n")
        out = _os.path.join(work, f"final.{_safe_ext(task.get('container'))}")
        if task.get("kind") == "transcode":
            # The agent already fetched every segment to /work, so the concat container
            # needs NO network — close it (previously stitch ran with default egress,
            # exposing ffmpeg-protocol SSRF/exfil on buyer-supplied inputs) and drop caps.
            concat = ["docker", "run", "--rm", "--network", "none"]
            concat += _isolation_flags(task)
            concat += ["-v", f"{work}:/work", image, "-y",
                       "-f", "concat", "-safe", "0", "-i", "/work/list.txt", "-c", "copy",
                       f"/work/{_os.path.basename(out)}"]
            # Audit H1: bound concat to the authorized runtime budget.
            _rt = task.get("max_runtime_s")
            subprocess.run(concat, check=True, timeout=(int(_rt) if _rt else None))
        else:   # render: tar the collected frames
            import tarfile
            with tarfile.open(out, "w") as tf:
                tf.add(work, arcname="frames")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": _os.path.basename(out)}).json()
        from cryptography.fernet import Fernet
        raw = open(out, "rb").read()
        enc = Fernet(grant["enc_key"].encode()).encrypt(raw)
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed", result=grant["snapshot_ref"],
                                             content_hash=hashlib.sha256(raw).hexdigest()))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"assemble failed: {e}")
        _post("/jobs/result", _signed_result(tid, status="failed"))
    finally:
        shutil.rmtree(outer, ignore_errors=True)


def _run_distributed(task):
    """Run ONE rank of a distributed cluster — the seller-side of a multi-node job.

    Closes the execution loop the control plane set up: every rank (1) registers its own
    VPN-reachable address so the whole cluster is addressable, (2) resolves the master (rank 0
    is itself; the others poll rendezvous until rank 0 is up), then (3) EXECUTES —

      * the built-in cluster self-test: a real cross-process all-reduce proving the ranks talk to
        each other and compute the correct global reduction (no GPU / torch / image needed); or
      * a real training run: launch the buyer's container under torchrun wired to the master
        address + this rank + the world size.

    A completed rank submits a signed result (the cluster completes when EVERY rank does); any
    failure submits a signed 'failed' result, which fails the whole gang-scheduled run server-side
    (see main._fail_distributed_if_member). The coordination logic lives in distributed_run.py so
    it stays unit-testable without Docker/network."""
    import distributed_run as _dist
    tid = task["task_id"]
    dist = task.get("distributed") or {}
    rank = int(dist.get("rank", 0))
    world = int(dist.get("world_size", 1))
    job_id = dist.get("job_id")
    backend = dist.get("backend", "nccl")
    _set_ui(status="running", task=f"Distributed rank {rank}/{world} #{tid}")
    # SECURITY (H5): a distributed rank runs with --network host so it can reach peers over the
    # WireGuard mesh — that bypasses the per-job DOCKER-USER egress firewall (metadata/LAN DROP), so
    # it is ONLY safe on a node the operator explicitly opted into VPN isolation. Enforce the gate
    # the design assumed but never checked; refuse otherwise (server gang semantics refund the buyer).
    try:
        import wireguard as _wg
        _vpn_ok = _wg.vpn_enabled()
    except Exception:                                    # noqa: BLE001
        _vpn_ok = False
    if not _vpn_ok:
        report_log(tid, "distributed rank refused: AGENT_VPN_ENABLED is not set on this node "
                        "(--network host for a cluster rank requires VPN isolation)")
        _post("/jobs/result", _signed_result(tid, status="failed"))
        _set_ui(status="idle", task=None, fail=True)
        return
    host = _dist.local_vpn_addr()
    port = int(os.getenv("DIST_RENDEZVOUS_PORT", str(_dist.DEFAULT_RENDEZVOUS_PORT)))
    try:
        # 1) register THIS rank's VPN address so the cluster becomes fully addressable. Rank 0's
        #    registration also elects it master (server-enforced — no other rank can hijack it).
        reg = httpx.post(f"{API_URL}{dist.get('register_url', '/jobs/rendezvous')}",
                         headers=HEADERS, timeout=15,
                         json={"task_id": tid, "host": host, "port": port, "slots": 1}).json()
        report_progress(tid, 15, f"rank {rank}/{world} registered at {host}:{port}")

        # 2) resolve the master (rank 0 is itself; other ranks poll until rank 0 registers).
        # Pass our own task_id so the server returns THIS machine's rank even when one account owns
        # several ranks (a home lab: many computers on one account, each with its own API key).
        rdzv_url = dist.get("rendezvous_url") or f"/jobs/rendezvous/{job_id}"

        def _fetch():
            return httpx.get(f"{API_URL}{rdzv_url}", headers=HEADERS, timeout=15,
                             params={"task_id": tid}).json()

        master = _dist.resolve_master(
            dist, my_host=host, my_port=port, current=reg, fetch=_fetch, sleep=time.sleep,
            timeout_s=int(os.getenv("DIST_RENDEZVOUS_TIMEOUT", "300")))
        maddr, mport = master["master_addr"], int(master["master_port"])
        report_progress(tid, 30, f"cluster formed; master={maddr}:{mport} backend={backend}")

        # 3a) built-in cluster self-test: a genuine cross-process all-reduce over the mesh.
        if _dist.is_selftest(task):
            dim = int(os.getenv("DIST_SELFTEST_DIM", "8"))
            seed = int(job_id or 0)
            out = _dist.run_allreduce_rank(
                rank, world, maddr, mport, dim=dim, seed=seed,
                bind_host=("0.0.0.0" if rank == 0 else None),
                timeout_s=int(os.getenv("DIST_SELFTEST_TIMEOUT", "180")))
            ch = crypto.sha256_hex(out["result"])   # every honest rank -> identical reduced vector
            report_progress(tid, 95, f"all-reduce ok across {out['contributors']} ranks")
            _post("/jobs/result", _signed_result(
                tid, status="completed",
                result=f"allreduce rank {rank}/{world}: sum={out['result']}",
                content_hash=ch))
            if _con:
                _con.line("done", f"cluster self-test rank {rank}/{world} reduced ok")
            _set_ui(status="idle", task=None, ok=True)
            return

        # 3b) real training run: launch the buyer container under torchrun with this rank.
        import shutil, subprocess
        if not shutil.which("docker"):
            report_log(tid, "docker not installed; cannot run distributed rank")
            _post("/jobs/result", _signed_result(tid, status="failed"))
            _set_ui(status="idle", task=None, fail=True)
            return
        argv = _dist.build_torchrun_cmd(
            image=task.get("image"), command=task.get("command"), rank=rank, world_size=world,
            master_addr=maddr, master_port=mport, backend=backend,
            gpu=bool(task.get("gpu")), env=task.get("env") or {},
            isolation_flags=_isolation_flags(task), egress_flags=_egress_flags(task))
        report_progress(tid, 45, f"launching torchrun rank {rank}/{world}")
        # Audit H1 parity: bound the rank to the buyer's authorized runtime budget, like the
        # notebook/render/transcode/stitch paths — a hung or malicious rank can't run the seller's
        # GPU indefinitely.
        _rt = task.get("max_runtime_s")
        subprocess.run(argv, check=True, timeout=(int(_rt) if _rt else None))
        report_progress(tid, 100, f"rank {rank}/{world} finished")
        _post("/jobs/result", _signed_result(
            tid, status="completed", result=f"distributed rank {rank}/{world} complete"))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"distributed rank {rank}/{world} failed: {e}")
        # A failed rank fails the whole gang-scheduled cluster (server-side), so report it.
        _post("/jobs/result", _signed_result(tid, status="failed"))
        _set_ui(status="idle", task=None, fail=True)


def _signed_result(tid, status="completed", result=None, content_hash=None):
    # content_hash is the sha256 of the PLAINTEXT output bytes (deterministic — same work ->
    # same hash), carried INSIDE the signed proof so the seller commits to the actual output,
    # not just the object ref string. It lets the platform re-execute a fraction of real jobs
    # on independent nodes and compare hashes (quorum), instead of trusting a signed ref.
    proof = {"task_id": tid, "output_hash": (result or status)[:32], "ts": int(_t.time())}
    if content_hash:
        proof["content_hash"] = content_hash
    return {"task_id": tid, "status": status, "result": result,
            "proof": proof, "signature": crypto.sign_proof(proof)}



# ---- Idle fallback: earn a trickle via NiceHash when unrented ----
_IDLE_NAME = "petabyte-idle-miner"
_idle_running = {"on": False}
_platform_idle = {"enabled": False}   # updated from heartbeat responses


def _idle_creds():
    """Mine to PETABYTE's NiceHash account under a unique worker id (pb-<spec_id>),
    so earnings auto-attribute to this seller and land in their unified balance.
    No per-seller wallet."""
    addr = os.getenv("NICEHASH_ADDRESS")   # platform mining address (same for all nodes)
    if os.getenv("IDLE_MINING", "").lower() != "true" or not addr:
        return None
    return {"address": addr, "rig": f"pb-{SPEC_ID}",   # worker id == attribution key
            "image": os.getenv("NICEHASH_IMAGE", "nicehash/nicehashminer:latest")}


def start_idle_miner():
    """Start the miner container if opted-in (locally + platform) and not already up."""
    if _idle_running["on"] or not _platform_idle["enabled"]:
        return
    creds = _idle_creds()
    if not creds:
        return
    import shutil, subprocess
    if not shutil.which("docker"):
        return
    try:
        subprocess.run(["docker", "rm", "-f", _IDLE_NAME], capture_output=True)
        subprocess.check_call(
            ["docker", "run", "-d", "--rm", "--name", _IDLE_NAME, "--gpus", "all",
             "-e", f"NICEHASH_ADDRESS={creds['address']}",
             "-e", f"RIG_NAME={creds['rig']}", creds["image"]])
        _idle_running["on"] = True
        if _con:
            _con.line("mine", "idle-mining while unrented (earning a trickle)")
    except Exception as e:                              # noqa: BLE001
        logging.error(f"idle miner start failed: {e}")


def stop_idle_miner():
    """Kill the miner immediately so paid work gets the full GPU."""
    if not _idle_running["on"]:
        return
    import subprocess
    try:
        subprocess.run(["docker", "rm", "-f", _IDLE_NAME], capture_output=True)
    finally:
        _idle_running["on"] = False
        if _con:
            _con.line("idle", "idle-mining stopped (paid work takes the GPU)")


# ---- Spare-disk rental: rent unused disk to a web3/BitTorrent storage network ----
# NOT an idle/fallback mode: it is an EXPLICIT contribution the seller configures (provider + GB
# cap, both required) and it runs INDEPENDENTLY of GPU work — earning whether or not a job is on
# the box. The operator allows it on the MACHINE with DISK_RENTAL_ENABLED=true; the seller then
# configures the node (provider + cap) via the API, delivered on the heartbeat. Each node
# contributes under its unique name (pbdisk-<spec_id>) -> earnings attribute to the seller's
# unified balance. The seller can change the cap, disable, or delete at any time.
_disk_running = {"on": False, "node": None, "alloc": 0, "provider": None}


def _disk_rental_enabled() -> bool:
    """The MACHINE operator must allow disk rental locally — off by default (fail-closed)."""
    return os.getenv("DISK_RENTAL_ENABLED", "").lower() == "true"


def _disk_wallet() -> str:
    """PETABYTE's platform storage wallet (earnings pool centrally, credited per node). Never a
    per-seller wallet."""
    return os.getenv("DISK_PAYOUT_WALLET", "")


def start_disk_node(provider, node_name, alloc_gb):
    """Launch (or re-launch on a changed cap) the storage-node container. Idempotent."""
    import shutil, subprocess
    import disk_node as _dn
    if not shutil.which("docker") or not _dn.provider_supported(provider) or int(alloc_gb) < 1:
        return
    if (_disk_running["on"] and _disk_running["node"] == node_name
            and _disk_running["alloc"] == int(alloc_gb)
            and _disk_running["provider"] == provider):
        return                                   # already running with this exact config
    data_dir = _dn.data_dir_for(node_name)
    try:
        os.makedirs(data_dir, exist_ok=True)
        subprocess.run(["docker", "rm", "-f", _dn.container_name(node_name)], capture_output=True)
        cmd = _dn.build_disk_cmd(provider=provider, node_name=node_name, alloc_gb=int(alloc_gb),
                                 data_dir=data_dir, wallet=_disk_wallet())
        subprocess.check_call(cmd)
        _disk_running.update({"on": True, "node": node_name, "alloc": int(alloc_gb),
                              "provider": provider})
        if _con:
            _con.line("disk", f"renting {alloc_gb} GB to {provider} as {node_name}")
        _report_disk(provider, node_name, int(alloc_gb))
    except Exception as e:                              # noqa: BLE001 — never crash the agent
        logging.error(f"disk node start failed: {e}")


def stop_disk_node(node_name):
    """Stop the storage node (pause earning) but KEEP its data — a disable, not a delete."""
    if not node_name:
        return
    import subprocess
    import disk_node as _dn
    try:
        subprocess.run(["docker", "rm", "-f", _dn.container_name(node_name)], capture_output=True)
    finally:
        if _disk_running["node"] == node_name:
            _disk_running.update({"on": False})


def remove_disk_node(node_name):
    """Cancel + delete: stop the node AND wipe its data dir (the seller deleted the contribution)."""
    if not node_name:
        return
    import shutil
    import disk_node as _dn
    stop_disk_node(node_name)
    try:
        shutil.rmtree(_dn.data_dir_for(node_name), ignore_errors=True)
        if _con:
            _con.line("disk", f"deleted disk contribution {node_name} (data wiped)")
    except Exception as e:                              # noqa: BLE001
        logging.error(f"disk node remove failed: {e}")


def _report_disk(provider, node_name, alloc_gb):
    """Tell the platform the node's usage + an estimated daily trickle (seller visibility)."""
    import disk_node as _dn
    used = _dn.data_dir_bytes_gb(_dn.data_dir_for(node_name))
    ref = float(os.getenv("DISK_REFERENCE_USD_PER_TB_MONTH", "1.5"))
    _post("/nodes/disk_report", {"spec_id": int(SPEC_ID), "provider": provider,
                                 "used_gb": used, "est_daily_usd": _dn.est_daily_usd(alloc_gb, ref)})


def _apply_disk_cfg(cfg):
    """React to the heartbeat's disk config: start / limit / pause / delete the storage node.
    The MACHINE must allow it (DISK_RENTAL_ENABLED=true); otherwise this is a no-op."""
    if not isinstance(cfg, dict) or not _disk_rental_enabled():
        return
    node = cfg.get("node_name")
    if cfg.get("enabled"):
        provider = cfg.get("provider")
        alloc = int(cfg.get("alloc_gb") or 0)
        if provider and alloc >= 1:
            start_disk_node(provider, node, alloc)
    else:
        # disabled (pause, keep data) vs deleted (config cleared -> wipe). The server clears the
        # provider on DELETE, so "no provider" means the seller cancelled the contribution.
        if cfg.get("provider"):
            stop_disk_node(node)
        else:
            remove_disk_node(node)


def job_loop():
    while True:
        try:
            r = httpx.get(f"{API_URL}/jobs/next", headers=HEADERS, timeout=20)
            if r.status_code == 204:
                start_idle_miner()   # unrented -> earn a trickle if opted in
            elif r.status_code == 200:
                task = r.json()
                if _con:
                    _con.line("claim", f"claimed {task.get('task_type')} #{task.get('task_id')}")
                stop_idle_miner()   # PAID WORK PREEMPTS: free the GPU first
                tt = task.get("task_type")
                # Join the SAME trace that started on the platform: the job envelope carries
                # the W3C trace context (added by the API when the job is dispatched).
                carrier = task.get("trace_context") or {}
                _tel.bind(job_id=task.get("task_id"), transaction_id=task.get("transaction_id"))
                # Emit JOB_RECEIVED INSIDE the span so the receipt joins THIS job's trace
                # (the span extracts the platform trace from the carrier). Emitting it before
                # the span would attribute it to the previous job's still-lingering trace_id.
                with _tel.span("gpu.job.execute", carrier=carrier, task_type=str(tt)):
                    _tel.event(_tel.EVENTS.JOB_RECEIVED, message="job claimed",
                               task_type=tt, job_id=task.get("task_id"))
                    _tel.event(_tel.EVENTS.JOB_EXECUTION_STARTED, message="execution started",
                               task_type=tt)
                    try:
                        if tt == "notebook":
                            _run_notebook(task)
                        elif tt == "test":
                            _run_test(task)
                        elif tt == "template":
                            _run_template(task)
                        elif tt == "benchmark":
                            _run_benchmark(task)
                        elif tt == "render":
                            _run_render(task)
                        elif tt == "transcode":
                            _run_transcode(task)
                        elif tt == "stitch":
                            _run_stitch(task)
                        elif tt == "distributed":
                            _run_distributed(task)
                        else:
                            _run_vm(task)
                        _tel.event(_tel.EVENTS.JOB_EXECUTION_COMPLETED,
                                   message="execution completed", task_type=tt)
                        if _con:
                            _con.line("done", f"finished {tt} #{task.get('task_id')}")
                    except Exception as _je:             # noqa: BLE001
                        _tel.event(_tel.EVENTS.JOB_EXECUTION_FAILED,
                                   message="execution failed", task_type=tt,
                                   reason=str(_je)[:200])
                        if _con:
                            _con.line("fail", f"{tt} #{task.get('task_id')} failed: {str(_je)[:80]}")
                        raise
                continue  # immediately poll again after finishing
            else:
                logging.warning(f"/jobs/next {r.status_code}: {r.text[:200]}")
        except Exception as e:                          # noqa: BLE001
            logging.error(f"job poll error: {e}")
        time.sleep(POLL_S)


def run_agent():
    # Telemetry first — degrade-safe: if the collector is unreachable the agent still runs.
    _tel.init(agent_id=SPEC_ID, seller_id=os.getenv("PROVIDER"))
    _tel.event(_tel.EVENTS.STARTUP, message="agent started", api_url=API_URL, spec_id=SPEC_ID)
    if _con:
        _con.banner(API_URL, SPEC_ID, os.getenv("PROVIDER"))
    else:
        logging.warning(f"agent -> {API_URL} (spec {SPEC_ID})")
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    job_loop()


if __name__ == "__main__":
    run_agent()
