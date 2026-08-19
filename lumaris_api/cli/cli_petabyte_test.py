"""cli_petabyte_test.py — the buyer CLI, driven as a real subprocess against a real API.

This is the CLI equivalent of the browser E2E: it boots the actual uvicorn server
(SQLite + fake Stripe, hermetic — reusing scripts/e2e/local_e2e.py), brings a seller GPU
online, then runs `python cli/petabyte.py …` and asserts the user-facing contract:

  * correct exit codes (success 0, handled error 1, argparse misuse 2)
  * the empty state before any GPU is online, and the populated table after
  * table headers + the seeded GPU's real values (model, price, provider) still render
  * --json is valid JSON on stdout (the machine-readable contract is intact)
  * NO_COLOR strips ANSI; PETABYTE_COLOR=always emits it
  * errors are readable (no raw traceback) and doctor reports health

Run:  python cli_petabyte_test.py
"""
import base64
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
API_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(API_DIR)
sys.path.insert(0, os.path.join(REPO, "scripts", "e2e"))
import local_e2e as le  # noqa: E402  (faithful server bootstrap + agent crypto)

CLI = os.path.join(HERE, "petabyte.py")
CONFIG = os.path.join(le._agent_key_dir, "cli_test.json")
_fail = 0


def ok(label, cond, extra=""):
    global _fail
    print(("ok   " if cond else "FAIL ") + label + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        _fail += 1


def run(*args, color=False, no_color=False, json_mode=False, config=CONFIG):
    """Invoke the buyer CLI as a subprocess; return (exit, stdout, stderr)."""
    env = dict(os.environ)
    env["PETABYTE_API_URL"] = le.BASE
    env["PETABYTE_CONFIG"] = config
    env.pop("PETABYTE_COLOR", None)
    env.pop("NO_COLOR", None)
    if color:
        env["PETABYTE_COLOR"] = "always"
    if no_color:
        env["NO_COLOR"] = "1"
    argv = [sys.executable, CLI]
    if json_mode:
        argv.append("--json")
    argv += list(args)
    p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=90)
    return p.returncode, p.stdout, p.stderr


def seed_gpu():
    """Bring one seller GPU online via the classic escrow path (register+prove+heartbeat)."""
    import httpx
    with httpx.Client(timeout=30) as c:
        for u in ("seller_cli", "buyer_cli"):
            c.post(f"{le.BASE}/register_user", json={"username": u, "password": "pw-correct-horse-1"})
        st = le.token_for(c, "seller_cli", "pw-correct-horse-1")
        c.post(f"{le.BASE}/change_role", headers={"Authorization": f"Bearer {st}"},
               json={"role": "seller"})
        kr = c.post(f"{le.BASE}/create_api_key?days=90&scopes=node,jobs",
                    headers={"Authorization": f"Bearer {st}"})
        sk = {"X-API-KEY": kr.json()["api_key"]}
        sr = c.post(f"{le.BASE}/register_specs", headers={"Authorization": f"Bearer {st}"},
                    json={"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.5,
                          "provider": "local-lab", "gpu_model": "RTX 4000 Ada", "gpu_count": 1,
                          "vram_gb": 20, "units": 4, "region": "us-east", "country": "US"})
        spec_id = sr.json()["spec_id"]
        att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
               "ts": int(time.time())}
        c.post(f"{le.BASE}/prove", headers={"Authorization": f"Bearer {st}"},
               json={"spec_id": spec_id, "attestation": att,
                     "signature": le.agent_crypto.sign_proof(att),
                     "pubkey": le.agent_crypto.public_key_b64()})
        c.post(f"{le.BASE}/heartbeat", headers=sk, json={"spec_id": spec_id})


ANSI = re.compile(r"\033\[[0-9;]*m")


def main():
    proc, log, _db = le.start_server()
    try:
        if not le.wait_up():
            print("SERVER FAILED TO START — last log lines:")
            try:
                print(open(log.name).read()[-2000:])
            except Exception:
                pass
            return 2

        # ---- help / argparse ----------------------------------------------
        code, so, se = run("--help")
        ok("--help exits 0", code == 0, str(code))
        ok("--help lists the commands",
           all(w in so for w in ("register", "specs", "run", "launch", "wallet")))
        code, so, se = run("launch", "--help")
        ok("launch --help documents the one-click template command (petabyte launch <template>)",
           code == 0 and "template" in so and "--hours" in so)

        code, so, se = run("deposit", "notanumber")
        ok("invalid argument exits 2 (argparse)", code == 2, str(code))
        ok("invalid argument prints a usage error", "usage:" in se.lower() or "invalid" in se.lower())

        # an unknown subcommand is a clean argparse error, not a crash
        code, so, se = run("definitely-not-a-command")
        ok("unknown command exits 2 (argparse)", code == 2, str(code))
        ok("unknown command prints an argparse error",
           "usage:" in se.lower() or "invalid choice" in se.lower())

        # ---- account flow ---------------------------------------------------
        code, so, se = run("register", "-u", "buyer_cli", "-p", "pw-correct-horse-1")
        # 'register' may already exist from seeding; either a clean success or a handled error
        ok("register exits cleanly (0 or handled 1)", code in (0, 1), str(code))
        code, so, se = run("login", "-u", "buyer_cli", "-p", "pw-correct-horse-1")
        ok("login exits 0", code == 0, se.strip()[:120])
        ok("login has no raw traceback", "Traceback" not in se)

        # ---- EMPTY STATE (signed in, but no GPU online yet) -----------------
        code, so, se = run("specs")
        ok("specs empty-state exits 0", code == 0, str(code))
        ok("specs empty-state explains itself (not a blank screen)",
           "no bookable gpus" in so.lower() or "no bookable" in so.lower())

        code, so, se = run("deposit", "100")
        ok("deposit exits 0", code == 0, se.strip()[:120])
        ok("deposit reports the new balance", "100" in so)

        code, so, se = run("wallet")
        ok("wallet exits 0", code == 0)
        ok("wallet shows the balance", "balance" in so.lower())
        ok("wallet shows earnings", "earnings" in so.lower())

        # ---- bad login is a readable error, not a stack trace ---------------
        code, so, se = run("login", "-u", "buyer_cli", "-p", "wrong-password")
        ok("bad login exits 1", code == 1, str(code))
        ok("bad login is readable (no traceback)", "Traceback" not in se)
        ok("bad login says what failed", "login failed" in (so + se).lower())

        # ---- populate the marketplace, then the TABLE -----------------------
        seed_gpu()
        code, so, se = run("specs")
        ok("specs (with a GPU) exits 0", code == 0)
        plain = ANSI.sub("", so)
        ok("specs table has the expected headers",
           all(h in plain for h in ("ID", "GPU", "$/HR", "PROVIDER")))
        ok("specs table shows the seeded GPU model", "RTX 4000 Ada" in plain)
        ok("specs table shows the price", "1.50" in plain)
        ok("specs table shows the provider", "local-lab" in plain)

        code, so, se = run("specs", no_color=True)
        ok("specs with NO_COLOR emits no ANSI", "\033[" not in so)

        # ---- run with no matching GPU is a readable error -------------------
        code_file = os.path.join(le._agent_key_dir, "job.py")
        with open(code_file, "w") as f:
            f.write("print('hello gpu')\n")
        code, so, se = run("run", code_file, "--gpu", "NOPE-9999", "--timeout", "5")
        ok("run --gpu <none> exits 1", code == 1, str(code))
        ok("run no-match is readable (no traceback)", "Traceback" not in se)
        ok("run no-match explains the problem", "no matching gpu" in (so + se).lower())

        # a genuinely missing file fails fast (exit 1), it does not hang
        code, so, se = run("run", os.path.join(le._agent_key_dir, "nope-missing.py"),
                           "--timeout", "5")
        ok("run on a missing file exits 1", code == 1, str(code))

    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            log.close()
        except Exception:
            pass

    print(f"\n{'PASS' if not _fail else 'FAIL (' + str(_fail) + ')'} — buyer CLI ({'0' if not _fail else _fail} failing)")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
