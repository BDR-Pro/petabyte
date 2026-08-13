#!/usr/bin/env python3
"""Petabyte CLI — book GPU compute and run a notebook in one command.

  petabyte register -u alice -p secret
  petabyte login    -u alice -p secret
  petabyte deposit 100
  petabyte specs
  petabyte run notebook.ipynb --gpu H100 --hours 1
  petabyte wallet
"""
import argparse
import json
import os
import sys
import time

import httpx
import os as _os

# The model hub (discover/pull/manage models) lives in the sibling `modelhub` package. Make it
# importable whether the CLI is run as `python cli/petabyte.py` or installed as `petabyte`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from modelhub import cli as mh_cli
except Exception:  # noqa: BLE001 — model commands are optional; the compute CLI still works without
    mh_cli = None

_TTY = hasattr(__import__("sys").stdout, "isatty") and __import__("sys").stdout.isatty() and not _os.getenv("NO_COLOR")
def _c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if _TTY else txt
def _amber(t): return _c(t, "38;5;214")
def _cyan(t): return _c(t, "38;5;44")
def _green(t): return _c(t, "38;5;42")
def _dim(t): return _c(t, "2")
def _bold(t): return _c(t, "1")

CONFIG = os.path.expanduser("~/.petabyte/cli.json")
DEFAULT_API = os.getenv("PETABYTE_API_URL", "http://localhost:8000")


def _cfg():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {"api_url": DEFAULT_API, "token": None}


def _save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    json.dump(cfg, open(CONFIG, "w"))


def _client(cfg, auth=True):
    headers = {}
    if auth and cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    return httpx.Client(base_url=cfg["api_url"], headers=headers, timeout=30)


def _die(msg, r=None):
    if r is not None:
        msg += f" ({r.status_code}: {r.text[:200]})"
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def cmd_register(a, cfg):
    with _client(cfg, auth=False) as c:
        r = c.post("/register_user", json={"username": a.username, "password": a.password})
    print("registered" if r.status_code == 200 else _die("register failed", r))


def cmd_login(a, cfg):
    with _client(cfg, auth=False) as c:
        r = c.post("/login", data={"username": a.username, "password": a.password})
    if r.status_code != 200:
        _die("login failed", r)
    cfg["token"] = r.json()["access_token"]
    _save(cfg)
    print("logged in")


def cmd_deposit(a, cfg):
    with _client(cfg) as c:
        r = c.post("/deposit", json={"amount": a.amount})
    print(f"balance: ${r.json()['balance']}" if r.status_code == 200 else _die("deposit failed", r))


def cmd_wallet(a, cfg):
    with _client(cfg) as c:
        r = c.get("/wallet")
    if r.status_code != 200:
        _die("wallet failed", r)
    w = r.json()
    print(f"balance:  ${w['balance']}\nearnings: ${w['earnings']}")


def cmd_specs(a, cfg):
    with _client(cfg) as c:
        r = c.get("/specs")
    if r.status_code != 200:
        _die("specs failed", r)
    specs = r.json()["specs"]
    if not specs:
        print("no bookable GPUs available right now")
        return
    print(_dim(f"  {'ID':>3}  {'GPU':<10} {'$/HR':>7}  {'UNITS':>5}  {'REP':>3}  PROVIDER"))
    for sp in specs:
        rep = sp.get("reputation_score", sp.get("reputation"))
        tags = []
        if sp.get("confidential"): tags.append(_amber("confidential"))
        if sp.get("region_verified"): tags.append(_cyan("region\u2713"))
        line = (f"  {sp['spec_id']:>3}  {_bold(str(sp['gpu_model'] or 'CPU')):<10} "
                f"{_amber('$'+format(sp['price_per_hour'],'.2f')):>7}  "
                f"{sp['available_units']:>5}  {rep:>3}  {sp['provider']}")
        print(line + ("  " + " ".join(tags) if tags else ""))


def _read_code(path):
    if path.endswith(".ipynb"):
        nb = json.load(open(path))
        cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        return "\n\n".join("".join(c.get("source", [])) for c in cells)
    return open(path).read()


def cmd_run(a, cfg):
    code = _read_code(a.file)
    with _client(cfg) as c:
        # pick a spec
        spec_id = a.spec
        if not spec_id:
            specs = c.get("/specs").json()["specs"]
            if a.gpu:
                specs = [s for s in specs if (s["gpu_model"] or "").lower() == a.gpu.lower()]
            if not specs:
                _die("no matching GPU available")
            spec_id = specs[0]["spec_id"]   # cheapest (list is price-sorted)
            print(_dim(f"→ selected spec {spec_id} ({specs[0]['gpu_model']} @ ${specs[0]['price_per_hour']}/hr)"))
        # book (optionally on a private WireGuard VPN — the buyer chooses)
        want_vpn = bool(getattr(a, "vpn", False))
        r = c.post("/request_vm", json={"spec_id": spec_id, "hours": a.hours, "vpn": want_vpn})
        if r.status_code != 200:
            _die("booking failed", r)
        bk = r.json()
        print(f"booked #{bk['booking_id']}  escrow ${bk['gross_amount']} "
              f"(fee ${bk['platform_fee']}, seller ${bk['seller_payout']})")
        if want_vpn and bk.get("vpn_config_url"):
            cr = c.get(bk["vpn_config_url"])
            if cr.status_code == 200:
                path = f"petabyte-{bk['booking_id']}.conf"
                with open(path, "w") as f:
                    f.write(cr.text)
                print(_green(f"✓ VPN config written to {path}") +
                      _dim(f"  → connect with:  sudo wg-quick up ./{path}"))
            else:
                print(_amber("! could not fetch VPN config (booking still active)"))
        # create task
        r = c.post("/create_task", json={"booking_id": bk["booking_id"],
                                         "task_type": "notebook", "code": code})
        if r.status_code != 200:
            _die("task creation failed", r)
        tid = r.json()["task_id"]
        print(f"dispatched task #{tid} — waiting for a node to execute...")
        # poll
        deadline = time.time() + a.timeout
        while time.time() < deadline:
            t = c.get(f"/tasks/{tid}").json()
            if t["status"] in ("completed", "failed"):
                hdr = _green("\u2713 COMPLETED") if t["status"]=="completed" else _amber("\u2717 FAILED")
                print(f"\n{hdr}")
                print(t.get("result") or "(no output)")
                return
            time.sleep(2)
        print("timed out waiting for result", file=sys.stderr)


def cmd_vpn(a, cfg):
    """Download (or re-download) the WireGuard client config for a VPN-enabled booking."""
    with _client(cfg) as c:
        r = c.get(f"/vpn_config/{a.booking_id}")
        if r.status_code != 200:
            _die("no VPN config for that booking (was it booked with --vpn?)", r)
        path = a.out or f"petabyte-{a.booking_id}.conf"
        with open(path, "w") as f:
            f.write(r.text)
        print(_green(f"✓ VPN config written to {path}"))
        print(_dim(f"  connect:  sudo wg-quick up ./{path}      disconnect:  sudo wg-quick down ./{path}"))


def main():
    p = argparse.ArgumentParser(prog="petabyte")
    p.add_argument("--api", help="API base URL (overrides saved config)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("register"); s.add_argument("-u", "--username", required=True); s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("login");    s.add_argument("-u", "--username", required=True); s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("deposit");  s.add_argument("amount", type=float)
    sub.add_parser("wallet")
    sub.add_parser("specs")
    s = sub.add_parser("run", help="run a notebook/.py on a rented GPU, OR start a model runtime")
    s.add_argument("file", help="a .ipynb/.py file (compute job) OR a model id like Qwen/Qwen3-8B")
    s.add_argument("--spec", type=int); s.add_argument("--gpu")
    s.add_argument("--hours", type=int, default=1); s.add_argument("--timeout", type=int, default=120)
    s.add_argument("--vpn", action="store_true",
                   help="rent on a private WireGuard VPN and save the client config")
    s.add_argument("--revision"); s.add_argument("--format"); s.add_argument("--quantization")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("vpn", help="download the WireGuard config for a VPN booking")
    s.add_argument("booking_id", type=int); s.add_argument("-o", "--out")

    # model hub: discover/pull/manage AI models (Hugging Face-grade UX). Owns `model`, `pull`, `auth`;
    # `run` is shared with the compute flow above and dispatched smartly below.
    if mh_cli is not None:
        mh_cli.register(sub, include=("model", "pull", "auth"))

    a = p.parse_args()
    cfg = _cfg()
    if a.api:
        cfg["api_url"] = a.api

    if mh_cli is not None and a.cmd in ("model", "pull", "auth"):
        sys.exit(mh_cli.handle(a) or 0)
    if a.cmd == "run" and _is_model_ref(a.file):
        if mh_cli is None:
            _die("model runtime unavailable (modelhub not importable)")
        ns = __import__("argparse").Namespace(
            id=a.file, format=a.format, quantization=a.quantization, revision=a.revision,
            force=a.force, home=None)
        sys.exit(mh_cli.cmd_run(ns) or 0)
    {"register": cmd_register, "login": cmd_login, "deposit": cmd_deposit,
     "wallet": cmd_wallet, "specs": cmd_specs, "run": cmd_run, "vpn": cmd_vpn}[a.cmd](a, cfg)


def _is_model_ref(arg):
    """`run` overloads a file path and a model id. A model id has a source/slug shape and is NOT an
    existing local file or a notebook/script."""
    if os.path.exists(arg) or arg.endswith((".ipynb", ".py")):
        return False
    return ("/" in arg) or (":" in arg) or arg.startswith(("hf:", "pt:", "http://", "https://"))


if __name__ == "__main__":
    main()
