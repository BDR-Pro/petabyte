#!/usr/bin/env python3
"""Provision this machine as a Petabyte node using ONLY an API key (no creds):
detect hardware, register the spec, attest it (Ed25519), and write the agent env.

The node authenticates every call with X-API-KEY, so no username/password ever
lives on the machine. Create the key on the /install page (that button also makes
your account a seller). The key's account must already be a seller.

Env:
  PETABYTE_API_URL, PETABYTE_API_KEY               (required)
  PRICE_PER_HOUR (unset => auto-priced from this GPU's benchmark), UNITS (1), MAX_HOURS (24)
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
import cli_ui


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


def _fail(title, **kw):
    """Readable error to stderr, then exit non-zero (keeps the old exit contract)."""
    cli_ui.err.error(title, **kw)
    raise SystemExit(1)


def resolve_price(client, gpu_model):
    """Decide the hourly listing price for this node.

    The seller's explicit PRICE_PER_HOUR always wins. When it is unset — the common
    case, because onboarding is meant to be one command — we do NOT guess a flat rate.
    We ask the server for a fair, benchmark-anchored suggestion for the GPU we just
    detected (the same number the /install page shows), so a 4090 never lists at the
    same price as a 2060. Only if that call cannot be reached do we fall back to a
    labelled placeholder, and we say so out loud.

    Returns (price: float, basis: str).
    """
    raw = (os.getenv("PRICE_PER_HOUR") or "").strip()
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v, "seller-set"
        except ValueError:
            pass
        print(f"PRICE_PER_HOUR={raw!r} is not a positive number — ignoring it and auto-pricing.")
    try:
        r = client.get("/pricing/suggest", params={"gpu_model": gpu_model or ""})
        if r.status_code == 200:
            body = r.json()
            p = float(body.get("suggested_price") or 0)
            if p > 0:
                return p, "auto: " + str(body.get("basis") or "benchmark-anchored")
    except Exception as e:  # network/parse — never let pricing block onboarding
        print(f"could not fetch a benchmark-anchored price ({e}); using a placeholder.")
    print("WARNING: no price set and the pricing service was unreachable — listing at "
          "$1.00/hr as a placeholder. Set PRICE_PER_HOUR or edit your listing to fix it.")
    return 1.0, "fallback (pricing service unreachable)"


def main():
    ui = cli_ui.out
    ui.heading("Provision this machine as a Petabyte node")
    API = os.environ.get("PETABYTE_API_URL")
    KEY = os.environ.get("PETABYTE_API_KEY")
    if not API:
        _fail("PETABYTE_API_URL is not set",
              reason="The node needs to know which Petabyte API to register with.",
              run="export PETABYTE_API_URL=https://petabyte.market")
    if not KEY:
        _fail("PETABYTE_API_KEY is not set",
              reason="The node authenticates with an API key (no username/password).",
              checks=["create one on the /install page (that button also makes you a seller)"],
              run="export PETABYTE_API_KEY=<your node key>")

    cpu, ram, gpu, gc, vram = detect()
    ui.step("Detected hardware", done=True)
    ui.panel("", [
        ("CPU", f"{cpu} cores"),
        ("RAM", f"{ram} GB"),
        ("GPU", (f"{gpu} x{gc}" if gpu else "none (CPU-only node)")),
        ("VRAM", (f"{vram} GB" if vram else "—")),
    ], label_width=5)

    h = {"X-API-KEY": KEY}
    provider = os.getenv("PROVIDER", socket.gethostname() or "petabyte-node")
    with httpx.Client(base_url=API, timeout=20) as c:
        price, price_basis = resolve_price(c, gpu)
        ui.step(f"Registering spec with {API} …")
        spec = c.post("/register_specs", headers=h, json={
            "cpu": cpu, "ram": ram, "duration": int(os.getenv("MAX_HOURS", "24")),
            "price_per_hour": price,
            "provider": provider, "gpu_model": gpu, "gpu_count": gc, "vram_gb": vram,
            "units": int(os.getenv("UNITS", "1"))})
        if spec.status_code == 403:
            _fail("This API key's account is not a seller",
                  reason="register_specs returned HTTP 403 (not a seller account).",
                  checks=["re-create the key from the /install page — that button makes "
                          "your account a seller"])
        if spec.status_code == 401:
            _fail("API key rejected (invalid or revoked)",
                  reason="register_specs returned HTTP 401.",
                  checks=["create a fresh node key on the /install page"])
        if spec.status_code >= 400:
            _fail("Could not register this node",
                  detail=f"HTTP {spec.status_code}: {spec.text[:200]}")
        spec_id = spec.json()["spec_id"]
        ui.step(f"Registered spec #{spec_id}", done=True)

        ui.step("Attesting node identity (Ed25519) …")
        att = {"cpu": cpu, "ram": ram, "gpu_model": gpu,
               "nonce": base64.b64encode(os.urandom(9)).decode(), "ts": int(time.time())}
        pr = c.post("/prove", headers=h, json={
            "spec_id": spec_id, "attestation": att,
            "signature": crypto.sign_proof(att), "pubkey": crypto.public_key_b64()})
        if pr.status_code >= 400:
            _fail("Attestation failed", detail=f"HTTP {pr.status_code}: {pr.text[:200]}")
        ui.step("Attestation accepted", done=True)

    key_path = os.getenv("PETABYTE_AGENT_KEY", crypto.KEY_PATH)
    env_path = os.getenv("AGENT_ENV", "/etc/petabyte/agent.env")
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(env_path, "w") as f:
        f.write(f"PETABYTE_API_URL={API}\n"
                f"PETABYTE_API_KEY={KEY}\n"
                f"PETABYTE_SPEC_ID={spec_id}\n"
                f"PETABYTE_AGENT_KEY={key_path}\n")
    os.chmod(env_path, 0o600)
    ui.blank()
    ui.success("Node provisioned and online", **{
        "Spec": f"#{spec_id}",
        "GPU": (f"{gpu} x{gc}" if gpu else "CPU-only"),
        "Price": f"${price:.2f}/hour ({price_basis})",
        "Env": env_path,
        "Next": "python main.py   (or start the petabyte-agent service)",
    })


if __name__ == "__main__":
    main()
