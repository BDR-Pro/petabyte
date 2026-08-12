#!/usr/bin/env python3
"""Petabyte CLI — book GPU compute and run a notebook in one command.

  petabyte register -u alice -p secret
  petabyte login    -u alice -p secret
  petabyte deposit 100
  petabyte specs
  petabyte run notebook.ipynb --gpu H100 --hours 1
  petabyte wallet
  petabyte doctor            # check API URL, connectivity, and sign-in

Human-friendly by default (semantic colour + tables); add --json to any command for
stable machine-readable output. Colour turns itself off when stdout is not a TTY or
NO_COLOR is set, so pipes and CI stay clean.
"""
import argparse
import json
import os
import sys
import time

import httpx

import cli_ui

CONFIG = os.getenv("PETABYTE_CONFIG") or os.path.expanduser("~/.petabyte/cli.json")
DEFAULT_API = os.getenv("PETABYTE_API_URL", "http://localhost:8000")

out = cli_ui.Ui(sys.stdout)
err = cli_ui.Ui(sys.stderr)
JSON = False   # set from --json / PETABYTE_JSON; flips every command to machine mode


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


def _die(msg, r=None, **fields):
    """Exit non-zero with a readable error (human) or a JSON error object (machine)."""
    detail = None
    if r is not None:
        detail = f"HTTP {r.status_code}: {r.text[:200]}"
    if JSON:
        cli_ui.emit_json({"error": msg, "detail": detail, **fields}, sys.stderr)
    else:
        err.error(msg, detail=detail, **fields)
    sys.exit(1)


def _money(v):
    """Render a money value the same way everywhere: $1,234.50."""
    try:
        return "$" + format(float(v), ",.2f")
    except (TypeError, ValueError):
        return f"${v}"


# --------------------------------------------------------------------- commands
def cmd_register(a, cfg):
    with _client(cfg, auth=False) as c:
        r = c.post("/register_user", json={"username": a.username, "password": a.password})
    if r.status_code != 200:
        _die("Registration failed", r,
             checks=["username may already be taken", "password must be 8+ characters"])
    if JSON:
        cli_ui.emit_json({"registered": True, "username": a.username})
    else:
        out.success(f"Registered account '{a.username}'", Next="petabyte login "
                    f"-u {a.username} -p ******")


def cmd_login(a, cfg):
    with _client(cfg, auth=False) as c:
        r = c.post("/login", data={"username": a.username, "password": a.password})
    if r.status_code != 200:
        _die("Sign-in failed", r, checks=["wrong username or password",
                                          "account not registered yet (petabyte register)"])
    cfg["token"] = r.json()["access_token"]
    _save(cfg)
    if JSON:
        cli_ui.emit_json({"logged_in": True, "username": a.username})
    else:
        out.success(f"Signed in as {a.username}", API=cfg["api_url"])


def cmd_deposit(a, cfg):
    with _client(cfg) as c:
        r = c.post("/deposit", json={"amount": a.amount})
    if r.status_code != 200:
        _die("Deposit failed", r, checks=["sign in first (petabyte login)"])
    bal = r.json().get("balance")
    if JSON:
        cli_ui.emit_json({"balance": bal})
    else:
        out.success(f"Deposited {_money(a.amount)}", Balance=_money(bal))


def cmd_wallet(a, cfg):
    with _client(cfg) as c:
        r = c.get("/wallet")
    if r.status_code != 200:
        _die("Could not load wallet", r, checks=["sign in first (petabyte login)"])
    w = r.json()
    if JSON:
        cli_ui.emit_json(w)
        return
    out.panel("Wallet", [
        ("Balance", _money(w.get("balance", 0))),
        ("Earnings", _money(w.get("earnings", 0))),
    ])


def cmd_specs(a, cfg):
    with _client(cfg) as c:
        r = c.get("/specs")
    if r.status_code != 200:
        _die("Could not list GPUs", r, checks=["sign in first (petabyte login)"])
    specs = r.json().get("specs", [])
    if JSON:
        cli_ui.emit_json(specs)
        return
    if not specs:
        out.info("No bookable GPUs are online right now.")
        out.line(out.dim("  A GPU appears here once a seller node is attested and online."))
        return
    rows = []
    for sp in specs:
        rep = sp.get("reputation_score", sp.get("reputation"))
        tags = []
        if sp.get("confidential"):
            tags.append(out.amber("confidential"))
        if sp.get("region_verified"):
            tags.append(out.cyan("region" + out.icon("ok")))
        rows.append([
            sp["spec_id"],
            sp.get("gpu_model") or "CPU",
            _money(sp["price_per_hour"]) + "/hr",
            sp.get("available_units"),
            rep,
            sp.get("provider"),
            " ".join(tags),
        ])
    out.table(["ID", "GPU", "PRICE", "UNITS", "REP", "PROVIDER", ""], rows,
              aligns=["r", "l", "r", "r", "r", "l", "l"])
    out.line(out.dim(f"\n  {len(specs)} GPU{'s' if len(specs) != 1 else ''} available "
                     f"· cheapest first · book with: petabyte run <file> --gpu <model>"))


def _read_code(path):
    if path.endswith(".ipynb"):
        nb = json.load(open(path))
        cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        return "\n\n".join("".join(c.get("source", [])) for c in cells)
    return open(path).read()


def cmd_run(a, cfg):
    try:
        code = _read_code(a.file)
    except FileNotFoundError:
        _die(f"File not found: {a.file}")
    with _client(cfg) as c:
        spec_id = a.spec
        chosen = None
        if not spec_id:
            specs = c.get("/specs").json().get("specs", [])
            if a.gpu:
                specs = [s for s in specs if (s["gpu_model"] or "").lower() == a.gpu.lower()]
            if not specs:
                _die("No matching GPU is available right now",
                     checks=[f"try a different --gpu (you asked for {a.gpu})" if a.gpu
                             else "no seller nodes are online", "petabyte specs — see what's online"])
            chosen = specs[0]                       # cheapest (list is price-sorted)
            spec_id = chosen["spec_id"]
            if not JSON:
                out.step(f"Selected GPU {chosen['gpu_model']} "
                         f"@ {_money(chosen['price_per_hour'])}/hr (spec {spec_id})")
        r = c.post("/request_vm", json={"spec_id": spec_id, "hours": a.hours})
        if r.status_code != 200:
            _die("Booking failed", r, checks=["enough balance? petabyte wallet",
                                             "GPU may have just gone offline"])
        bk = r.json()
        if not JSON:
            out.step(f"Booked #{bk['booking_id']} — escrowed {_money(bk['gross_amount'])} "
                     f"(fee {_money(bk['platform_fee'])}, seller {_money(bk['seller_payout'])})",
                     done=True)
        r = c.post("/create_task", json={"booking_id": bk["booking_id"],
                                         "task_type": "notebook", "code": code})
        if r.status_code != 200:
            _die("Task creation failed", r)
        tid = r.json()["task_id"]
        if not JSON:
            out.step(f"Dispatched task #{tid} — waiting for a node to execute…")
        deadline = time.time() + a.timeout
        while time.time() < deadline:
            t = c.get(f"/tasks/{tid}").json()
            if t["status"] in ("completed", "failed"):
                if JSON:
                    cli_ui.emit_json({"booking_id": bk["booking_id"], "task_id": tid,
                                      "status": t["status"], "result": t.get("result")})
                    return
                out.blank()
                if t["status"] == "completed":
                    out.success(f"Task #{tid} completed")
                else:
                    err.error(f"Task #{tid} failed")
                out.line(out.dim("  ── output " + "─" * 40))
                out.line(t.get("result") or out.dim("(no output)"))
                sys.exit(0 if t["status"] == "completed" else 1)
            time.sleep(2)
        _die(f"Timed out after {a.timeout}s waiting for task #{tid}",
             checks=["the node may be slow — the job is still booked",
                     f"petabyte specs and re-check, or raise --timeout"])


def cmd_doctor(a, cfg):
    """Diagnose the CLI's environment: API URL, connectivity, and sign-in state."""
    api = cfg["api_url"]
    checks = []

    def record(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # 1) reachability
    reachable, health_detail = False, ""
    try:
        with _client(cfg, auth=False) as c:
            t0 = time.time()
            hr = c.get("/healthz")
            ms = int((time.time() - t0) * 1000)
            reachable = hr.status_code < 500
            health_detail = f"HTTP {hr.status_code} in {ms}ms"
    except Exception as e:
        health_detail = f"{type(e).__name__}: {e}"
    record("API reachable", reachable, health_detail)

    # 2) sign-in
    signed_in, who = False, "not signed in"
    if cfg.get("token"):
        try:
            with _client(cfg) as c:
                me = c.get("/me")
            if me.status_code == 200:
                signed_in = True
                who = me.json().get("username", "?")
            else:
                who = f"token rejected (HTTP {me.status_code}) — petabyte login"
        except Exception as e:
            who = f"{type(e).__name__}: {e}"
    record("Signed in", signed_in, who)

    # 3) marketplace
    online, mk_detail = None, ""
    try:
        with _client(cfg, auth=False) as c:
            mk = c.get("/marketplace/specs")
        if mk.status_code == 200:
            data = mk.json()
            data = data if isinstance(data, list) else data.get("specs", [])
            online = len(data)
            mk_detail = f"{online} GPU(s) online"
    except Exception as e:
        mk_detail = f"{type(e).__name__}: {e}"
    record("Marketplace", online is not None, mk_detail)

    healthy = reachable
    if JSON:
        cli_ui.emit_json({"api_url": api, "healthy": healthy, "checks": checks})
        sys.exit(0 if healthy else 1)

    out.heading("petabyte doctor")
    out.kv("API URL", api, width=14)
    for ch in checks:
        state = "ok" if ch["ok"] else ("warning" if ch["check"] == "Signed in" else "failed")
        out.line(f"{out.status_label(state):<22} {out.dim(ch['check'])}  {ch['detail']}")
    out.blank()
    if healthy:
        out.success("Environment looks healthy.")
    else:
        err.error("Cannot reach the API",
                  reason=f"{api} did not respond.",
                  checks=["is PETABYTE_API_URL correct?",
                          "is the server running / is the URL public?"],
                  run="petabyte --api <url> doctor")
    sys.exit(0 if healthy else 1)


def main(argv=None):
    global JSON
    p = argparse.ArgumentParser(
        prog="petabyte",
        description="Book GPU compute and run a notebook in one command.",
        epilog="Set PETABYTE_API_URL or pass --api to point at a server. "
               "Add --json for machine-readable output. NO_COLOR disables colour.")
    p.add_argument("--api", metavar="URL", help="API base URL (overrides saved config)")
    p.add_argument("--json", action="store_true",
                   help="machine-readable JSON output (stable; no colour)")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    s = sub.add_parser("register", help="create an account")
    s.add_argument("-u", "--username", required=True)
    s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("login", help="sign in and save a token")
    s.add_argument("-u", "--username", required=True)
    s.add_argument("-p", "--password", required=True)
    s = sub.add_parser("deposit", help="add funds to your wallet")
    s.add_argument("amount", type=float, metavar="AMOUNT")
    sub.add_parser("wallet", help="show balance and earnings")
    sub.add_parser("specs", help="list bookable GPUs (cheapest first)")
    s = sub.add_parser("run", help="book the cheapest matching GPU and run a file on it")
    s.add_argument("file", help="a .ipynb (code cells) or .py file")
    s.add_argument("--spec", type=int, help="book a specific spec id (skips auto-select)")
    s.add_argument("--gpu", help="require a GPU model, e.g. H100")
    s.add_argument("--hours", type=int, default=1, help="max runtime hours (default 1)")
    s.add_argument("--timeout", type=int, default=120, help="seconds to wait (default 120)")
    sub.add_parser("doctor", help="check API URL, connectivity, and sign-in")

    a = p.parse_args(argv)
    JSON = a.json or cli_ui._env_flag("PETABYTE_JSON")
    if JSON:                                     # machine mode: never colour either stream
        out.color = err.color = False
    cfg = _cfg()
    if a.api:
        cfg["api_url"] = a.api
    handlers = {"register": cmd_register, "login": cmd_login, "deposit": cmd_deposit,
                "wallet": cmd_wallet, "specs": cmd_specs, "run": cmd_run, "doctor": cmd_doctor}
    try:
        handlers[a.cmd](a, cfg)
    except httpx.HTTPError as e:
        _die("Network error talking to the API", reason=str(e),
             checks=[f"is {cfg['api_url']} reachable?", "petabyte doctor"])


if __name__ == "__main__":
    main()
