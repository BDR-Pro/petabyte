#!/usr/bin/env python3
"""Regression: the API must import from the REPO ROOT under its canonical launch command.

The seller/platform bring-up doc tells operators to run:

    python -m uvicorn lumaris_api.main:app --host 0.0.0.0 --port 8000

from the repo root. That used to fail: the top-level ``observability/`` config directory
shadowed ``lumaris_api/observability.py`` on sys.path, so ``import observability`` in main.py
imported the wrong thing and the app would not start (forcing a fragile ``cd lumaris_api``).

This test imports the app in a CLEAN subprocess with the repo root as CWD and asserts both
that the app object exists AND that ``observability`` resolved to lumaris_api's module.

Run: python scripts/repo_root_import_test.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


_CHECK = (
    "import lumaris_api.main as m, observability as o\n"
    "assert m.app.title, 'no app'\n"
    "assert o.__file__.replace(chr(92), '/').endswith('lumaris_api/observability.py'), o.__file__\n"
    "print('IMPORT_OK', o.__file__)\n"
)

env = dict(os.environ)
env.update({
    "SECRET_KEY": "t", "SERVER_PRIVATE_KEY": "t", "WG_PUBLIC_KEY": "x",
    "WG_ENDPOINT": "y", "PAYMENT_WEBHOOK_SECRET": "w",
    "DATABASE_URL": "sqlite:///./_repo_root_import_test.db",
    "REAPER_DISABLED": "true",
})

# CWD = repo root, exactly like the documented launch command.
p = subprocess.run([sys.executable, "-c", _CHECK], cwd=ROOT, env=env,
                   capture_output=True, text=True)
ok("`import lumaris_api.main` succeeds from the repo root (canonical uvicorn path)",
   p.returncode == 0)
ok("`observability` resolves to lumaris_api/observability.py (not the top-level configs dir)",
   "IMPORT_OK" in p.stdout and "lumaris_api/observability.py" in p.stdout)
if p.returncode != 0:
    print("---- subprocess stderr (tail) ----")
    print("\n".join((p.stderr or "").splitlines()[-15:]))

for _f in ("_repo_root_import_test.db", "_repo_root_import_test.db-wal",
           "_repo_root_import_test.db-shm"):
    try:
        os.remove(os.path.join(ROOT, _f))
    except OSError:
        pass

print(f"\n=== repo_root_import: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
