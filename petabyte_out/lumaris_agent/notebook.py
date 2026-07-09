"""Sandboxed notebook execution.

Untrusted buyer code is NEVER run on the host. It runs inside a locked-down,
throwaway Docker container: no network, dropped capabilities, no new privileges,
read-only rootfs, a small tmpfs, and hard CPU/RAM/PID limits. Output size is
capped so a malicious notebook can't OOM the host while we read results.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import List, Union

import nbformat

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "jupyter/base-notebook:latest")
WALL_TIMEOUT = int(os.getenv("NB_TIMEOUT", "300"))          # outer hard kill (s)
CELL_TIMEOUT = int(os.getenv("NB_CELL_TIMEOUT", "120"))     # per-cell (s)
MAX_OUTPUT_BYTES = int(os.getenv("NB_MAX_OUTPUT", str(8 * 1024 * 1024)))  # 8 MB


def timed(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            return {"result": result, "duration_seconds": round(time.time() - start, 4)}
        except Exception as e:                       # noqa: BLE001
            logging.exception("Execution failed")
            return {"error": str(e), "duration_seconds": round(time.time() - start, 4)}
    return wrapper


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=10)
        return True
    except Exception:
        return False


@timed
def run_notebook_code(code: Union[str, List[str], dict], cpu: int = 1, ram: int = 2):
    """Execute notebook code in a sandboxed container. Returns a list of outputs."""
    if not _docker_available():
        # SECURITY: never fall back to host execution for untrusted code.
        return [{"type": "error",
                 "value": "Sandbox unavailable: Docker is required to run tasks safely."}]

    # Build the notebook
    if isinstance(code, dict):
        nb = nbformat.from_dict(code)
    else:
        cells = [code] if isinstance(code, str) else list(code)
        nb = nbformat.v4.new_notebook()
        nb.cells = [nbformat.v4.new_code_cell(c) for c in cells]

    workdir = tempfile.mkdtemp(prefix="pb_nb_")
    os.chmod(workdir, 0o777)  # container's unprivileged user must write output here
    in_path = os.path.join(workdir, "input.ipynb")
    out_path = os.path.join(workdir, "output.ipynb")
    with open(in_path, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)

    cmd = [
        "docker", "run", "--rm",
        "--network", "none",                       # no exfiltration / LAN access
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",                              # immutable rootfs
        "--tmpfs", "/tmp:size=256m",
        "--pids-limit", "256",
        "--cpus", str(max(1, cpu)),
        "--memory", f"{max(1, ram)}g",
        "--memory-swap", f"{max(1, ram)}g",         # disable swap escape
        "-v", f"{workdir}:/work:rw",
        "-w", "/work",
        SANDBOX_IMAGE,
        "jupyter", "nbconvert", "--to", "notebook", "--execute",
        f"--ExecutePreprocessor.timeout={CELL_TIMEOUT}",
        "--output", "output.ipynb", "input.ipynb",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=WALL_TIMEOUT)
        if proc.returncode != 0:
            return [{"type": "error", "value": f"Sandbox execution error: {proc.stderr[-2000:]}"}]
    except subprocess.TimeoutExpired:
        return [{"type": "error", "value": "Execution timed out"}]
    finally:
        pass

    if not os.path.exists(out_path) or os.path.getsize(out_path) > MAX_OUTPUT_BYTES * 4:
        shutil.rmtree(workdir, ignore_errors=True)
        return [{"type": "error", "value": "Output notebook missing or too large"}]

    executed = nbformat.read(out_path, as_version=4)
    shutil.rmtree(workdir, ignore_errors=True)

    outputs: List[dict] = []
    total = 0
    for cell in executed.cells:
        for output in cell.get("outputs", []):
            t = output.get("output_type")
            if t == "execute_result":
                val = output["data"].get("text/plain", "")
                outputs.append({"type": "text", "value": val})
            elif t == "stream":
                outputs.append({"type": "text", "value": output.get("text", "")})
            elif t == "error":
                outputs.append({"type": "error", "value": f"{output.get('ename')}: {output.get('evalue')}"})
            elif t == "display_data":
                data = output.get("data", {})
                if "image/png" in data:
                    outputs.append({"type": "image", "mime": "image/png", "base64": data["image/png"]})
                elif "text/html" in data:
                    outputs.append({"type": "html", "value": data["text/html"]})
            total += len(json.dumps(outputs[-1])) if outputs else 0
            if total > MAX_OUTPUT_BYTES:
                outputs.append({"type": "error", "value": "Output truncated (size cap reached)"})
                return outputs
    return outputs
