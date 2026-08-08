#!/usr/bin/env python3
"""verify-series-a — the reproducible release / diligence gate (#300, #493, #498-#500).

Runs the release gates and writes a MACHINE-READABLE evidence bundle to evidence/, so a
release is traceable to exactly what was verified rather than "someone said tests passed".

Gate priorities:
  P0      release-blocking — a FAIL means the release bar is not met (zero known P0 defects).
  P1      should pass — a FAIL is a strong warning but not, on its own, a hard block here.
  signal  informational (lint, dependency audit, honest coverage shortfall) — never blocks.

Honesty rules (matches the repo's ethos):
  * A gate that cannot run in this environment is recorded as SKIPPED with the reason
    (e.g. Postgres invariants need a Postgres DATABASE_URL; real-Stripe needs sk_test_).
  * `release_ready` is true ONLY when every P0 gate actually PASSED — a skip is NOT a pass.
  * Exit code is non-zero if any P0 gate FAILED (add --strict to also fail on P0 skips).

Usage:
  python scripts/verify_series_a.py            # full run
  python scripts/verify_series_a.py --quick    # fast structural gates only (no heavy suites)
  python scripts/verify_series_a.py --strict    # P0 skips count as failures too
  python scripts/verify_series_a.py --only drift,manifest_fresh
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, "lumaris_api")
AGENT = os.path.join(ROOT, "lumaris_agent")
EVID = os.path.join(ROOT, "evidence")
PY = sys.executable


def _sqlite_env():
    """Env for the SQLite suite gates: inherit, but drop DATABASE_URL so each suite uses its
    own sqlite default (mirrors run_tests.sh `unset DATABASE_URL`)."""
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    return env


def _schema_env():
    # ABSOLUTE, ROOT-anchored path. The schema_clean gate runs in lumaris_api/ while
    # financial_audit runs in the repo root; a RELATIVE sqlite path would resolve to two
    # different files, so financial_audit would audit an empty DB the schema gate never
    # populated. An absolute path makes both gates share ONE schema DB (built by
    # schema_clean, then read read-only by financial_audit).
    db_path = os.path.join(ROOT, "_series_a_schema.db")
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env.setdefault("SECRET_KEY", "x")
    env.setdefault("SERVER_PRIVATE_KEY", "x")
    return env


_VALIDATE_SNIPPET = (
    "import json,glob,yaml,sys\n"
    "for f in glob.glob('observability/grafana/dashboards/*.json'):\n"
    "  json.load(open(f))\n"
    "for f in glob.glob('observability/**/*.y*ml',recursive=True)+glob.glob('.github/workflows/*.y*ml'):\n"
    "  list(yaml.safe_load_all(open(f)))\n"
    "print('configs valid')"
)

# Each gate: id, title, priority, cwd, argv, quick(bool), + optional precheck() -> reason|None
GATES = [
    # ---- structural / config integrity (fast) ----
    {"id": "schema_clean", "title": "Schema builds from a clean SQLite DB", "prio": "P0",
     "cwd": API, "quick": True, "env": _schema_env,
     "argv": [PY, "-c", "import db; db.init_db(); print('schema OK')"]},
    {"id": "drift", "title": "Config drift (manifest/code/workflows/template.env in sync)",
     "prio": "P0", "cwd": ROOT, "quick": True,
     "argv": [PY, "scripts/check_configuration_drift.py"]},
    {"id": "manifest_fresh", "title": "Config manifest is up to date (regenerate -> no diff)",
     "prio": "P0", "cwd": ROOT, "quick": True, "shell": True,
     "argv": (PY + " scripts/build_config_manifest.py >/dev/null && "
              "git diff --exit-code config/github_configuration_manifest.yaml")},
    {"id": "docs_fresh", "title": "Config docs are up to date (regenerate -> no diff)",
     "prio": "P0", "cwd": ROOT, "quick": True, "shell": True,
     "argv": (PY + " scripts/generate_config_docs.py >/dev/null && "
              "git diff --exit-code docs/GITHUB_CONFIGURATION_REFERENCE.md "
              "docs/GITHUB_MANUAL_SETUP_CHECKLIST.md")},
    {"id": "yaml_json_valid", "title": "Dashboards + alert rules + workflows are valid",
     "prio": "P0", "cwd": ROOT, "quick": True, "argv": [PY, "-c", _VALIDATE_SNIPPET]},
    {"id": "financial_audit", "title": "Ledger integrity + booking/payout reconciliation",
     "prio": "P0", "cwd": ROOT, "quick": True, "env": _schema_env,
     "argv": [PY, "scripts/audit_ledger.py"]},
    {"id": "audit_ledger_signed", "title": "Ledger audit is sign-aware (wrong-direction leg)",
     "prio": "P1", "cwd": ROOT, "quick": True, "env": _sqlite_env,
     "argv": [PY, "scripts/audit_ledger_test.py"]},
    {"id": "repo_root_import", "title": "API imports from the repo root (canonical uvicorn path)",
     "prio": "P0", "cwd": ROOT, "quick": True, "argv": [PY, "scripts/repo_root_import_test.py"]},
    {"id": "agent_deps", "title": "Agent runtime imports are all declared in requirements",
     "prio": "P0", "cwd": ROOT, "quick": True, "argv": [PY, "lumaris_agent/deps_audit_test.py"]},
    {"id": "e2e_safety", "title": "E2E safety (no silent fake gw / connect mode / payout clock)",
     "prio": "P0", "cwd": API, "env": _sqlite_env, "quick": True,
     "argv": [PY, "e2e_safety_test.py"]},
    {"id": "e2e_runner_safety", "title": "E2E runner refuses live Stripe + redacts secrets",
     "prio": "P0", "cwd": ROOT, "quick": True,
     "argv": [PY, "scripts/e2e_marketplace_runner_test.py"]},
    {"id": "stripe_e2e_flow", "title": "Dispatch-once auto-capture + idempotency (fake gateway)",
     "prio": "P1", "cwd": API, "env": _sqlite_env,
     "argv": [PY, "stripe_e2e_flow_test.py"]},
    {"id": "secret_scan", "title": "No obvious committed secrets (best-effort)",
     "prio": "P0", "cwd": ROOT, "quick": True, "kind": "secret_scan"},
    # ---- offline test suites (heavier) ----
    {"id": "smoke", "title": "Smoke suite", "prio": "P0", "cwd": API, "env": _sqlite_env,
     "argv": [PY, "smoke_test.py"]},
    {"id": "adversarial", "title": "Adversarial (money conservation + races)", "prio": "P0",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "adversarial_test.py"]},
    {"id": "stripe", "title": "Stripe Connect flow (offline fake gateway)", "prio": "P0",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "stripe_test.py"]},
    {"id": "payout", "title": "Payout routing (provider-neutral)", "prio": "P0",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "payout_test.py"]},
    {"id": "config", "title": "GitHub config toolchain", "prio": "P0", "cwd": API,
     "env": _sqlite_env, "argv": [PY, "config_test.py"], "quick": True},
    {"id": "env_vars", "title": "ENV_VARS bundle (parser/secret-guard/precedence)",
     "prio": "P0", "cwd": API, "env": _sqlite_env, "argv": [PY, "env_vars_test.py"]},
    {"id": "observability", "title": "Observability (correlation/redaction/cardinality)",
     "prio": "P0", "cwd": API, "env": _sqlite_env, "argv": [PY, "observability_test.py"],
     "quick": True},
    {"id": "marketplace", "title": "Marketplace intelligence + financial heartbeat gauges",
     "prio": "P0", "cwd": API, "env": _sqlite_env, "argv": [PY, "marketplace_test.py"]},
    {"id": "newsletter", "title": "Newsletter signup (Mailgun mocked)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "newsletter_test.py"]},
    {"id": "account", "title": "Account (reset + cal webhook + notify)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "account_test.py"]},
    {"id": "wallet", "title": "Wallet (stripe checkout top-up)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "wallet_test.py"]},
    {"id": "seller_audit", "title": "Seller integrity audits (anti-fraud)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "seller_audit_test.py"]},
    {"id": "quorum", "title": "Quorum verification (redundant re-execution)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "quorum_test.py"]},
    {"id": "matmul", "title": "Matmul result validation", "prio": "P1", "cwd": API,
     "env": _sqlite_env, "argv": [PY, "matmul_validation_test.py"]},
    {"id": "email", "title": "Email (Mailgun, offline unit)", "prio": "P1", "cwd": API,
     "env": _sqlite_env, "argv": [PY, "email_test.py"]},
    {"id": "demo", "title": "Investor demo (seed + honesty + reset)", "prio": "P1",
     "cwd": API, "env": _sqlite_env, "argv": [PY, "demo_test.py"]},
    {"id": "agent_telemetry", "title": "Seller-agent telemetry (span/redaction/trace-join)",
     "prio": "P1", "cwd": AGENT, "env": _sqlite_env, "argv": [PY, "agent_telemetry_test.py"]},
    {"id": "obs_smoke", "title": "Observability smoke (local tier; remote skipped offline)",
     "prio": "P1", "cwd": ROOT, "argv": [PY, "scripts/observability_smoke_test.py"]},
    {"id": "local_e2e", "title": "Local buyer->seller->settlement E2E (offline full flow)",
     "prio": "P1", "cwd": ROOT, "env": _sqlite_env, "argv": [PY, "scripts/e2e/local_e2e.py"]},
    # ---- Postgres-only invariants (needs a Postgres DATABASE_URL) ----
    {"id": "postgres_invariants",
     "title": "Postgres-only invariants (exact NUMERIC, advisory lock, real races)",
     "prio": "P0", "cwd": API, "argv": [PY, "postgres_test.py"], "kind": "postgres"},
    # ---- signals (never block) ----
    {"id": "lint", "title": "ruff lint (style signal)", "prio": "signal", "cwd": ROOT,
     "quick": True, "shell": True,
     "argv": "ruff check lumaris_api lumaris_agent lumaris_gateway scripts"},
    {"id": "dep_audit", "title": "Dependency vulnerability audit (pip-audit)",
     "prio": "signal", "cwd": ROOT, "kind": "pip_audit"},
    {"id": "payout_coverage", "title": "Seller-payout country coverage (honest shortfall)",
     "prio": "signal", "cwd": ROOT, "kind": "coverage"},
]

_SECRET_PATTERNS = [
    r"sk_live_[0-9a-zA-Z]{16,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"AKIA[0-9A-Z]{16}",
    r"xox[baprs]-[0-9A-Za-z-]{10,}",
]


def _run_secret_scan() -> tuple[str, int | None, str]:
    """Best-effort scan of TRACKED files for obvious real secrets. Authoritative scanning is
    gitleaks in CI; this is a fast local backstop that excludes test fixtures/placeholders.

    Returns (status, exit_code, detail). If the file list can't be obtained the scan did not
    actually run, so it is reported as SKIP — never PASS. Recording an un-run scan as a pass
    would let a release claim "no committed secrets" on evidence that was never gathered."""
    import re
    try:
        # NUL-delimited: a tracked filename containing whitespace/newlines would otherwise be
        # split into invalid paths, whose read errors are swallowed below — silently skipping
        # that file and letting the scan report "pass" without ever reading it.
        files = [p for p in subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
            text=True, check=True).stdout.split("\0") if p]
    except Exception as e:  # noqa: BLE001
        return "skip", None, f"git ls-files unavailable ({type(e).__name__}) — scan not run"
    pats = [re.compile(p) for p in _SECRET_PATTERNS]
    hits = []
    for rel in files:
        if rel.endswith((".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2")):
            continue
        p = os.path.join(ROOT, rel)
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    for pat in pats:
                        m = pat.search(line)
                        if not m:
                            continue
                        tok = m.group(0)
                        # ignore obvious fixtures/placeholders
                        low = line.lower()
                        if any(x in tok for x in ("ABCDEF", "DEADBEEF", "XYZ")) or \
                           any(x in low for x in ("should", "example", "placeholder",
                                                  "test", "fixture", "dummy", "fake")):
                            continue
                        hits.append(f"{rel}:{i}")
        except (OSError, UnicodeError):
            continue
    if hits:
        return "fail", 1, "POSSIBLE secrets: " + ", ".join(hits[:20])
    return "pass", 0, "no obvious committed secrets"


def _postgres_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith("postgres")


def run_gate(g: dict) -> dict:
    prio = g["prio"]
    started = time.monotonic()
    kind = g.get("kind")

    # preconditions -> skip honestly
    if kind == "postgres" and not _postgres_available():
        return _res(g, "skip", None, started, "needs a Postgres DATABASE_URL (run under CI Postgres)")
    if kind == "pip_audit":
        try:
            subprocess.run(["pip-audit", "--version"], capture_output=True, check=True)
        except Exception:  # noqa: BLE001
            return _res(g, "skip", None, started, "pip-audit not installed")
        p = subprocess.run(["pip-audit", "-r", "lumaris_api/requirements.txt"],
                           cwd=ROOT, capture_output=True, text=True)
        return _res(g, "pass" if p.returncode == 0 else "warn", p.returncode, started,
                    _tail(p.stdout + p.stderr))
    if kind == "secret_scan":
        status, code, detail = _run_secret_scan()
        return _res(g, status, code, started, detail)
    if kind == "coverage":
        p = subprocess.run([PY, "scripts/verify_payout_country_coverage.py"], cwd=ROOT,
                           capture_output=True, text=True)
        # exit 0 (met) or 1 (expected honest shortfall) are both acceptable signals
        ok = p.returncode in (0, 1)
        return _res(g, "pass" if ok else "warn", p.returncode, started, _tail(p.stdout))

    env = g["env"]() if callable(g.get("env")) else os.environ.copy()
    argv = g["argv"]
    p = subprocess.run(argv, cwd=g["cwd"], env=env, capture_output=True, text=True,
                       shell=bool(g.get("shell")))
    status = "pass" if p.returncode == 0 else ("warn" if prio == "signal" else "fail")
    return _res(g, status, p.returncode, started, _tail(p.stdout + p.stderr))


def _tail(s: str, n: int = 6) -> str:
    lines = [ln for ln in (s or "").splitlines() if ln.strip()]
    return " | ".join(lines[-n:])[:600]


def _res(g, status, code, started, detail):
    return {"id": g["id"], "title": g["title"], "priority": g["prio"], "status": status,
            "exit_code": code, "duration_s": round(time.monotonic() - started, 2),
            "detail": detail}


def _git(*args, default=""):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return default


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="only the fast structural gates")
    ap.add_argument("--strict", action="store_true", help="P0 skips count as failures")
    ap.add_argument("--only", default="", help="comma-separated gate ids to run")
    args = ap.parse_args(argv)

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    selected = [g for g in GATES
                if (not only or g["id"] in only) and (not args.quick or g.get("quick"))]

    print(f"verify-series-a: running {len(selected)} gate(s)"
          f"{' [quick]' if args.quick else ''}{' [strict]' if args.strict else ''}\n")
    results = []
    for g in selected:
        r = run_gate(g)
        icon = {"pass": "ok  ", "fail": "FAIL", "warn": "warn", "skip": "skip"}[r["status"]]
        print(f"{icon}  [{r['priority']}] {r['id']}: {r['title']} ({r['duration_s']}s)")
        if r["status"] in ("fail", "warn") and r["detail"]:
            print(f"        {r['detail']}")
        results.append(r)

    def _count(prio, status):
        return sum(1 for r in results if r["priority"] == prio and r["status"] == status)

    p0_failed = _count("P0", "fail")
    p0_skipped = _count("P0", "skip")
    p0_passed = _count("P0", "pass")
    # release_ready may ONLY be claimed after a FULL run. A --quick or --only run executes a
    # subset of P0 gates, so "0 P0 failures" among them says nothing about the gates that
    # never ran (smoke, adversarial, stripe, postgres invariants, …). Claiming readiness from
    # a partial run would be the exact "someone said tests passed" failure this tool exists to
    # prevent.
    is_full_run = not args.quick and not only
    release_ready = (is_full_run and p0_failed == 0 and p0_skipped == 0 and p0_passed > 0)
    bundle = {
        "tool": "verify-series-a",
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .isoformat().replace("+00:00", "Z"),
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "mode": "quick" if args.quick else ("only" if only else "full"),
        "summary": {
            "p0": {"passed": p0_passed, "failed": p0_failed, "skipped": p0_skipped},
            "p1": {"passed": _count("P1", "pass"), "failed": _count("P1", "fail"),
                   "skipped": _count("P1", "skip")},
            "signals": {"pass": _count("signal", "pass"), "warn": _count("signal", "warn"),
                        "skip": _count("signal", "skip")},
        },
        "release_ready": bool(release_ready),
        "caveats": [f"{r['id']}: {r['detail']}" for r in results
                    if r["priority"] == "P0" and r["status"] == "skip"],
        "gates": results,
    }

    os.makedirs(EVID, exist_ok=True)
    sha = (bundle["commit"] or "unknown")[:12]
    out = os.path.join(EVID, f"series-a-{sha}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    # latest.json is the canonical "release verdict" pointer, so only a FULL run may write it.
    # A --quick / --only run would otherwise clobber a real verdict with a partial one that
    # carries release_ready=false and a subset of gates.
    if is_full_run:
        with open(os.path.join(EVID, "latest.json"), "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)

    print(f"\nP0 passed={p0_passed} failed={p0_failed} skipped={p0_skipped} "
          f"| release_ready={bundle['release_ready']}")
    if bundle["caveats"]:
        print("caveats:")
        for c in bundle["caveats"]:
            print(f"  - {c}")
    print(f"evidence bundle: {os.path.relpath(out, ROOT)}")

    # tidy up transient DBs this command created (never touch a real DATABASE_URL target).
    for base in (ROOT, API):
        for f in glob.glob(os.path.join(base, "_series_a_schema.db*")):
            try:
                os.remove(f)
            except OSError:
                pass

    # exit non-zero on any P0 failure; with --strict, P0 skips fail too.
    blocked = p0_failed > 0 or (args.strict and p0_skipped > 0)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
