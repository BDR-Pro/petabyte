"""exe_smoke_test.py — prove the packaged Desktop Agent's entrypoint UX works.

The .exe is a PyInstaller bundle of petabyte_desktop.py. "It runs via `python
petabyte_desktop.py`" is NOT proof the .exe works — the classic failure is a module that
PyInstaller doesn't discover (imported lazily / by string) and drops from the bundle, so
the .exe dies with ModuleNotFoundError on first use. This test guards both halves:

  1. RUNTIME: drive the entrypoint's CLI paths (--version / --help / doctor / doctor
     --json) exactly as the .exe would, asserting exit codes, headings, JSON purity, and
     the absence of import/asset errors.
  2. PACKAGING: statically assert build_exe.py bundles every local module the entrypoint
     imports (including the new cli_ui + agent_cli), so the .exe can't silently lose them.

A real Windows .exe must be built on Windows (see BUILD.md / GitHub Actions); this runs
the same code path hermetically. Set PB_BUILD_EXE=1 (with PyInstaller installed) to also
attempt a local binary build as a config check.

Run:  python exe_smoke_test.py
"""
import ast
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(HERE, "petabyte_desktop.py")
BUILD = os.path.join(HERE, "build_exe.py")
_fail = 0


def ok(label, cond, extra=""):
    global _fail
    print(("ok   " if cond else "FAIL ") + label + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        _fail += 1


def run(*args):
    env = dict(os.environ)
    for k in ("PETABYTE_API_KEY", "PETABYTE_SPEC_ID", "PETABYTE_COLOR", "NO_COLOR"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, ENTRY, *args], cwd=HERE, env=env,
                       capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout, p.stderr


IMPORT_ERRORS = ("ModuleNotFoundError", "ImportError", "No module named",
                 "FileNotFoundError", "cannot import")


def no_import_error(text):
    return not any(e in text for e in IMPORT_ERRORS)


# ---- 1. RUNTIME: the entrypoint answers its CLI without launching the GUI ----
code, so, se = run("--version")
ok("exe entrypoint --version exits 0", code == 0, str(code))
ok("exe entrypoint --version prints the product + version",
   "Petabyte Desktop Agent" in so and "1.0.0" in so)
ok("--version has no import/asset error", no_import_error(so + se), (so + se)[:160])

code, so, se = run("--help")
ok("exe entrypoint --help exits 0", code == 0)
ok("exe entrypoint --help renders usage + doctor", "Usage" in so and "doctor" in so)

code, so, se = run("doctor")
ok("exe entrypoint doctor runs (exit 0/1, not a crash)", code in (0, 1), str(code))
ok("doctor renders a heading", "doctor" in (so + se).lower())
ok("doctor has no import/asset error", no_import_error(so + se), (so + se)[:200])
ok("doctor has no raw traceback", "Traceback" not in (so + se))

code, so, se = run("doctor", "--json")
try:
    dj = json.loads(so)
except Exception:
    dj = None
ok("doctor --json: stdout is pure valid JSON (no log noise)", isinstance(dj, dict))
ok("doctor --json has product/version/checks",
   bool(dj) and {"product", "version", "checks"} <= set(dj or {}))
ok("doctor --json product is the desktop product",
   bool(dj) and dj.get("product") == "Petabyte Desktop Agent")

# ---- 2. PACKAGING: every local import the entrypoint uses is bundled ---------
build_src = open(BUILD).read()
hidden = set(re.findall(r"--hidden-import=([A-Za-z0-9_]+)", build_src))
collected = set(re.findall(r"--collect-all=([A-Za-z0-9_]+)", build_src))

# local .py modules that live beside the entrypoint (candidates for hidden-import)
local_mods = {f[:-3] for f in os.listdir(HERE)
              if f.endswith(".py") and not f.endswith("_test.py")}


def local_imports(path):
    """Top-level + function-level module names imported by a source file."""
    tree = ast.parse(open(path).read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


# What the entrypoint (and ui.py, which it imports) pull in, restricted to LOCAL modules.
entry_local = (local_imports(ENTRY) | local_imports(os.path.join(HERE, "ui.py"))) & local_mods
missing = sorted(m for m in entry_local
                 if m not in hidden and m not in collected and m != "petabyte_desktop")
ok("build_exe bundles the new cli_ui module", "cli_ui" in hidden)
ok("build_exe bundles the new agent_cli module", "agent_cli" in hidden)
ok("build_exe bundles every local module the entrypoint imports",
   not missing, f"missing hidden-imports: {missing}")

# data + assets the bundle needs
ok("build_exe ships the templates dir (--add-data)", "add-data=templates" in build_src)
ok("templates/index.html exists to be bundled",
   os.path.exists(os.path.join(HERE, "templates", "index.html")))
ok("cli_ui.py + agent_cli.py are present in the desktop unit",
   os.path.exists(os.path.join(HERE, "cli_ui.py")) and os.path.exists(os.path.join(HERE, "agent_cli.py")))

# cli_ui / agent_cli must be pure-stdlib (no third-party import) so freezing them adds
# no new hidden-import surface of their own.
THIRD_PARTY = {"flask", "httpx", "cryptography", "requests", "nbformat", "nbclient",
               "dotenv", "stripe", "boto3"}
ok("cli_ui.py is pure-stdlib (no third-party deps to bundle)",
   not (local_imports(os.path.join(HERE, "cli_ui.py")) & THIRD_PARTY))

# ---- 3. OPTIONAL: attempt a real local build as a config check --------------
if os.environ.get("PB_BUILD_EXE") == "1":
    try:
        import PyInstaller  # noqa: F401
        r = subprocess.run([sys.executable, BUILD], cwd=HERE, capture_output=True,
                           text=True, timeout=900)
        exe = os.path.join(HERE, "dist", "PetabyteAgent" + (".exe" if os.name == "nt" else ""))
        ok("PyInstaller build completed", r.returncode == 0, r.stderr[-300:])
        ok("build produced the executable", os.path.exists(exe))
    except ImportError:
        print("skip PyInstaller build — PyInstaller not installed (EXTERNAL_BUILD_REQUIRED)")
else:
    print("note: set PB_BUILD_EXE=1 (with PyInstaller) to also attempt a local binary build")

print("\n" + ("PASS" if not _fail else f"FAIL ({_fail})") + " — desktop exe smoke")
sys.exit(1 if _fail else 0)
