"""Petabyte agent task loop.

Talks to the hardened API:
  - POST /heartbeat        (liveness for the spec this node serves)
  - GET  /jobs/next        (claim a job for hardware we own)
  - POST /jobs/result      (notebook result)
  - POST /jobs/vm_details  (vm connection info)

Auth is the real encrypted API key (X-API-KEY). Heartbeat runs on its own thread
so a long-running job never makes the node look offline (which would get it reaped).
"""
import logging
import os
import threading
import time

import time as _t

import httpx

import crypto
from notebook import run_notebook_code
from vm import launch_vm_task

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

API_URL = os.getenv("PETABYTE_API_URL")        # e.g. https://petabyte.market
API_KEY = os.getenv("PETABYTE_API_KEY")        # encrypted key from POST /create_api_key
SPEC_ID = os.getenv("PETABYTE_SPEC_ID")        # the spec this node serves
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
                _platform_idle["enabled"] = bool(r.json().get("idle_fallback"))
                logging.debug("heartbeat ok")
            else:
                logging.warning(f"heartbeat {r.status_code}: {r.text[:200]}")
        except Exception as e:                          # noqa: BLE001
            logging.error(f"heartbeat error: {e}")
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
    result = run_notebook_code(code)
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
    cmd = ["docker", "run", "-d", "--name", name, "-p", f"{port}:{port}"]
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


def _run_benchmark(task):
    """Measure LLM tokens/sec (+ optional extras) and submit a SIGNED result."""
    tid = task["task_id"]
    _set_ui(status="running", task=f"Benchmark #{tid}")
    spec_id = int(os.getenv("PETABYTE_SPEC_ID"))
    report_progress(tid, 50, "benchmarking")
    # Placeholder measurement: a real node runs a fixed prompt through a local
    # model and counts generated tokens / wall-time. Hook your harness here.
    tokens_sec = float(os.getenv("BENCH_TOKENS_SEC", "0"))
    proof = {"task_id": tid, "output_hash": "benchmark", "ts": int(_t.time())}
    httpx.post(f"{API_URL}/jobs/benchmark_result", headers=HEADERS, timeout=20, json={
        "spec_id": spec_id, "tokens_sec": tokens_sec,
        "meta": {"harness": "stub"}, "proof": proof, "signature": crypto.sign_proof(proof)})
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
    try:
        # 1) pull the scene via a pre-signed GET (no standing creds on the node)
        g = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                       json={"task_id": tid, "ref": task.get("blend_ref", "")}).json()
        open(scene, "wb").write(httpx.get(g["download_url"], timeout=300).content)
        report_progress(tid, 15, f"scene fetched; rendering {fs}-{fe} in {image}")
        # 2) render inside the container (GPU via NVIDIA Container Toolkit)
        cmd = ["docker", "run", "--rm", "--network", "none",
               "-v", f"{scene}:/scene.blend:ro", "-v", f"{out_dir}:/out"]
        if task.get("gpu"):
            cmd += ["--gpus", "all"]
        cmd += [image, "blender", "-b", "/scene.blend", "-o", "/out/frame_",
                "-s", str(fs), "-e", str(fe), "-a"]
        subprocess.check_call(cmd)
        report_progress(tid, 85, "uploading frames")
        # 3) tar the frames and upload via a one-object pre-signed PUT
        bundle = _os.path.join(work, f"frames_{fs}_{fe}.tar")
        with tarfile.open(bundle, "w") as tf:
            tf.add(out_dir, arcname="frames")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": f"frames_{fs}_{fe}.tar"}).json()
        from cryptography.fernet import Fernet
        enc = Fernet(grant["enc_key"].encode()).encrypt(open(bundle, "rb").read())
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed",
                                             result=f"frames {fs}-{fe} -> {grant['snapshot_ref']}"))
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
    work = tempfile.mkdtemp(prefix=f"tc-{tid}-")
    src = _os.path.join(work, "in"); dst = _os.path.join(work, f"out.{task.get('container','mp4')}")
    try:
        g = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                       json={"task_id": tid, "ref": task.get("input_ref", "")}).json()
        open(src, "wb").write(httpx.get(g["download_url"], timeout=600).content)
        report_progress(tid, 20, "transcoding")
        vcodec = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"} \
            if task.get("gpu") else {"h264": "libx264", "h265": "libx265", "av1": "libaom-av1"}
        args = ["docker", "run", "--rm", "--network", "none",
                "-v", f"{src}:/in:ro", "-v", f"{work}:/work"]
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
        subprocess.check_call(args + ff)
        report_progress(tid, 80, "uploading")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": _os.path.basename(dst)}).json()
        from cryptography.fernet import Fernet
        enc = Fernet(grant["enc_key"].encode()).encrypt(open(dst, "rb").read())
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed", result=grant["snapshot_ref"]))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"transcode failed: {e}")
        _post("/jobs/result", _signed_result(tid, status="failed"))
        _set_ui(status="idle", task=None, fail=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
    work = tempfile.mkdtemp(prefix=f"stitch-{tid}-")
    try:
        # pull each segment via a restore-style GET, concat with ffmpeg
        listfile = _os.path.join(work, "list.txt")
        with open(listfile, "w") as lf:
            for i, ref in enumerate(refs):
                gg = httpx.post(f"{API_URL}/jobs/input_url", headers=HEADERS, timeout=15,
                                json={"task_id": tid, "ref": ref}).json()
                p = _os.path.join(work, f"seg{i}.{task.get('container','mp4')}")
                open(p, "wb").write(httpx.get(gg["download_url"], timeout=600).content)
                lf.write(f"file '{p}'\n")
        out = _os.path.join(work, f"final.{task.get('container','mp4')}")
        if task.get("kind") == "transcode":
            subprocess.check_call([image, "-y", "-f", "concat", "-safe", "0",
                                   "-i", listfile, "-c", "copy", out]) \
                if False else subprocess.check_call(
                ["docker", "run", "--rm", "-v", f"{work}:/work", image, "-y",
                 "-f", "concat", "-safe", "0", "-i", "/work/list.txt", "-c", "copy",
                 f"/work/{_os.path.basename(out)}"])
        else:   # render: tar the collected frames
            import tarfile
            with tarfile.open(out, "w") as tf:
                tf.add(work, arcname="frames")
        grant = httpx.post(f"{API_URL}/jobs/backup_url", headers=HEADERS, timeout=15,
                           json={"task_id": tid, "filename": _os.path.basename(out)}).json()
        from cryptography.fernet import Fernet
        enc = Fernet(grant["enc_key"].encode()).encrypt(open(out, "rb").read())
        httpx.put(grant["upload_url"], content=enc, timeout=600)
        _post("/jobs/result", _signed_result(tid, status="completed", result=grant["snapshot_ref"]))
        _set_ui(status="idle", task=None, ok=True)
    except Exception as e:                              # noqa: BLE001
        report_log(tid, f"assemble failed: {e}")
        _post("/jobs/result", _signed_result(tid, status="failed"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _signed_result(tid, status="completed", result=None):
    proof = {"task_id": tid, "output_hash": (result or status)[:32], "ts": int(_t.time())}
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
        logging.info("idle miner started (unrented)")
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
        logging.info("idle miner stopped (paid work / disabled)")


def job_loop():
    while True:
        try:
            r = httpx.get(f"{API_URL}/jobs/next", headers=HEADERS, timeout=20)
            if r.status_code == 204:
                start_idle_miner()   # unrented -> earn a trickle if opted in
            elif r.status_code == 200:
                task = r.json()
                logging.info(f"claimed task {task.get('task_id')} ({task.get('task_type')})")
                stop_idle_miner()   # PAID WORK PREEMPTS: free the GPU first
                tt = task.get("task_type")
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
                else:
                    _run_vm(task)
                continue  # immediately poll again after finishing
            else:
                logging.warning(f"/jobs/next {r.status_code}: {r.text[:200]}")
        except Exception as e:                          # noqa: BLE001
            logging.error(f"job poll error: {e}")
        time.sleep(POLL_S)


def run_agent():
    logging.info(f"agent -> {API_URL} (spec {SPEC_ID})")
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    job_loop()


if __name__ == "__main__":
    run_agent()
