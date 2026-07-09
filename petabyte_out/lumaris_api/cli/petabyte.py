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
        # book
        r = c.post("/request_vm", json={"spec_id": spec_id, "hours": a.hours})
        if r.status_code != 200:
            _die("booking failed", r)
        bk = r.json()
        print(f"booked #{bk['booking_id']}  escrow ${bk['gross_amount']} "
              f"(fee ${bk['platform_fee']}, seller ${bk['seller_payout']})")
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


def main():
    p = argparse.ArgumentParser(prog="petabyte")
    p.add_argument("--api", help="API base URL (overrides saved config)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("register"); s.add_argument("-u", "--username", required=True); s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("login");    s.add_argument("-u", "--username", required=True); s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("deposit");  s.add_argument("amount", type=float)
    sub.add_parser("wallet")
    sub.add_parser("specs")
    s = sub.add_parser("run")
    s.add_argument("file"); s.add_argument("--spec", type=int); s.add_argument("--gpu")
    s.add_argument("--hours", type=int, default=1); s.add_argument("--timeout", type=int, default=120)

    a = p.parse_args()
    cfg = _cfg()
    if a.api:
        cfg["api_url"] = a.api
    {"register": cmd_register, "login": cmd_login, "deposit": cmd_deposit,
     "wallet": cmd_wallet, "specs": cmd_specs, "run": cmd_run}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
