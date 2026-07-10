#!/usr/bin/env python3
"""Provision this machine as a Petabyte node using ONLY an API key (no creds):
detect hardware, register the spec, attest it (Ed25519), and write the agent env.

The node authenticates every call with X-API-KEY, so no username/password ever
lives on the machine. Create the key on the /install page (that button also makes
your account a seller). The key's account must already be a seller.

Env:
  PETABYTE_API_URL, PETABYTE_API_KEY               (required)
  PRICE_PER_HOUR (default 1.0), UNITS (1), MAX_HOURS (24)
  GPU_MODEL/GPU_COUNT/VRAM_GB                       (override auto-detect)
  AGENT_ENV (default /etc/petabyte/agent.env), PETABYTE_AGENT_KEY
"""
import base64
import os
import socket
import subprocess
import time

import httpx
import crypto


def detect():
    cpu = os.cpu_count() or 1
    try:
        kb = int(next(l for l in open("/proc/meminfo") if l.startswith("MemTotal")).split()[1])
        ram = max(1, kb // 1024 // 1024)
    except Exception:
        ram = 1
    gpu_model = os.getenv("GPU_MODEL")
    gpu_count = int(os.getenv("GPU_COUNT", "0"))
    vram = int(os.getenv("VRAM_GB", "0"))
    if not gpu_model:
        try:
            rows = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"], text=True).strip().splitlines()
            if rows:
                gpu_count = len(rows)
                name, mem = rows[0].split(",")
                gpu_model = name.strip()
                vram = int(float(mem)) // 1024
        except Exception:
            pass
    return cpu, ram, gpu_model, gpu_count, vram


def main():
    API = os.environ["PETABYTE_API_URL"]
    try:
        KEY = os.environ["PETABYTE_API_KEY"]
    except KeyError:
        raise SystemExit("Set PETABYTE_API_KEY (create one on the /install page).")
    cpu, ram, gpu, gc, vram = detect()
    h = {"X-API-KEY": KEY}
    provider = os.getenv("PROVIDER", socket.gethostname() or "petabyte-node")
    with httpx.Client(base_url=API, timeout=20) as c:
        spec = c.post("/register_specs", headers=h, json={
            "cpu": cpu, "ram": ram, "duration": int(os.getenv("MAX_HOURS", "24")),
            "price_per_hour": float(os.getenv("PRICE_PER_HOUR", "1.0")),
            "provider": provider, "gpu_model": gpu, "gpu_count": gc, "vram_gb": vram,
            "units": int(os.getenv("UNITS", "1"))})
        if spec.status_code == 403:
            raise SystemExit("This API key's account is not a seller. Re-create the "
                             "key from the /install page (that button makes you a seller).")
        if spec.status_code == 401:
            raise SystemExit("API key rejected (invalid or revoked). Create a fresh one.")
        spec.raise_for_status()
        spec_id = spec.json()["spec_id"]
        att = {"cpu": cpu, "ram": ram, "gpu_model": gpu,
               "nonce": base64.b64encode(os.urandom(9)).decode(), "ts": int(time.time())}
        pr = c.post("/prove", headers=h, json={
            "spec_id": spec_id, "attestation": att,
            "signature": crypto.sign_proof(att), "pubkey": crypto.public_key_b64()})
        pr.raise_for_status()

    key_path = os.getenv("PETABYTE_AGENT_KEY", crypto.KEY_PATH)
    env_path = os.getenv("AGENT_ENV", "/etc/petabyte/agent.env")
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w") as f:
        f.write(f"PETABYTE_API_URL={API}\n"
                f"PETABYTE_API_KEY={KEY}\n"
                f"PETABYTE_SPEC_ID={spec_id}\n"
                f"PETABYTE_AGENT_KEY={key_path}\n")
    os.chmod(env_path, 0o600)
    print(f"provisioned spec {spec_id} (gpu={gpu} x{gc}, {cpu}cpu/{ram}gb); env -> {env_path}")


if __name__ == "__main__":
    main()
