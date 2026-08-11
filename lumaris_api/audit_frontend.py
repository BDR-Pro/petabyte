"""
audit_frontend.py — does the frontend actually match the backend?

Four classes of bug that tests don't catch, because a broken frontend still
returns HTTP 200:

  1. DEAD CALL      — JS fetches an endpoint the backend doesn't serve. Silent 404.
  2. DEAD LINK      — an <a href> pointing at a route that doesn't exist. Silent 404.
  3. DEAD ID        — getElementById('x') where no element with id="x" exists.
                      Returns null, the line after it throws, and everything below
                      that in the script never runs. This is the nastiest one: it
                      breaks features that look fine in code review.
  4. ORPHAN ROUTE   — a backend endpoint no part of the UI ever calls. Not a bug,
                      but it's either dead code or an unshipped feature.

Run: python audit_frontend.py
"""
import os
import re
import sys

import glob

HERE = os.path.dirname(os.path.abspath(__file__))
pages = open(os.path.join(HERE, "pages.py")).read()
main = open(os.path.join(HERE, "main.py")).read()
# Domain routers extracted from main.py (staged monolith split): each `*_routes.py` defines an
# APIRouter mounted via app.include_router. Scan them too so extracting a route never trips the
# contract audit — the endpoint still exists, just in a router module.
router_src = "\n".join(open(f).read() for f in sorted(glob.glob(os.path.join(HERE, "*_routes.py"))))

# ---------------------------------------------------------------- backend routes
routes = set()
for src in (main, router_src):
    for m in re.finditer(r'@(?:app|v1|router)\.(get|post|put|delete)\(\s*"([^"]+)"', src):
        verb, path = m.group(1).upper(), m.group(2)
        routes.add((verb, path))
# v1 aliases registered via add_api_route
for m in re.finditer(r'v1\.add_api_route\(\s*"([^"]+)"[^)]*?methods=\["(\w+)"\]', main, re.S):
    routes.add((m.group(2).upper(), "/api/v1" + m.group(1)))

route_paths = {p for _, p in routes}


def norm(p):
    """/vm/{vm_id}/stop -> /vm/*/stop so we can compare templated paths."""
    return re.sub(r"\{[^}]+\}", "*", p)


norm_routes = {(v, norm(p)) for v, p in routes}
norm_paths = {norm(p) for p in route_paths}

# ---------------------------------------------------------------- frontend calls
# api('/x', {method:'POST'}) and fetch('/x', {...})
calls = set()
for m in re.finditer(r"""\bapi\(\s*'([^']+)'(?:\s*,\s*\{[^}]*method\s*:\s*'(\w+)')?""", pages):
    calls.add(((m.group(2) or "GET").upper(), m.group(1)))
for m in re.finditer(r"""\bfetch\(\s*'([^']+)'(?:\s*,\s*\{[^}]*method\s*:\s*'(\w+)')?""", pages):
    calls.add(((m.group(2) or "GET").upper(), m.group(1)))
# concatenated paths: api('/vm/'+id+'/stop', {method:'POST'})
# The naive regex above stops at the first quote and misses the tail, which made the
# audit report working buttons as "unsurfaced". Reconstruct the whole expression.
for m in re.finditer(
        r"""\b(?:api|fetch)\(\s*((?:'[^']*'\s*\+\s*[^,()]+?\s*\+\s*)*'[^']*'|'[^']*'\s*\+\s*[^,()]+?)\s*(?:,\s*\{([^}]*)\})?\s*\)""",
        pages):
    expr, opts = m.group(1), m.group(2) or ""
    # keep the literal chunks, replace the interpolated variables with *
    parts = re.findall(r"'([^']*)'", expr)
    if not parts:
        continue
    path = "*".join(parts) if len(parts) > 1 else parts[0] + "*"
    verb = (re.search(r"method\s*:\s*'(\w+)'", opts) or [None, "GET"])[1].upper()
    calls.add((verb, path))


def norm_call(p):
    p = p.split("?")[0]
    p = re.sub(r"'\s*\+\s*[\w.$\[\]]+\s*\+\s*'", "*", p)   # '/vm/'+id+'/stop'
    p = re.sub(r"\*+", "*", p)
    return p.rstrip("/") or "/"


dead_calls = []
for verb, path in sorted(calls):
    np = norm_call(path)
    if np.endswith("*"):
        base = np[:-1].rstrip("/")
        if any(nr.startswith(base) for nr in norm_paths):
            continue
    if np in norm_paths or (verb, np) in norm_routes:
        continue
    # tolerate trailing-star vs templated
    if any(norm_call(np) == nr or nr.startswith(np.rstrip("*")) for nr in norm_paths):
        continue
    dead_calls.append((verb, path))

# ---------------------------------------------------------------- links
links = set(re.findall(r'href="(/[^"#?]*)"', pages))
page_routes = {p for v, p in routes if v == "GET"}
dead_links = []
for h in sorted(links):
    h2 = h.rstrip("/") or "/"
    if h2 in {norm(p).rstrip("/") or "/" for p in page_routes}:
        continue
    if h.startswith("/static/") or h.startswith("/gpu/"):
        continue
    if any(norm(p).rstrip("/") == h2 for p in route_paths):
        continue
    dead_links.append(h)

# ---------------------------------------------------------------- DOM ids
declared = set(re.findall(r'id="([\w-]+)"', pages))
# ids created at runtime (document.createElement -> el.id = 'x') are real too
declared |= set(re.findall(r"""\.id\s*=\s*['"]([\w-]+)['"]""", pages))
used = set(re.findall(r"getElementById\(\s*'([\w-]+)'\s*\)", pages))
used |= set(re.findall(r'getElementById\(\s*"([\w-]+)"\s*\)', pages))
dead_ids = sorted(used - declared)

# ---------------------------------------------------------------- orphan routes
called_norm = {norm_call(p) for _, p in calls}
orphans = []
INTERNAL = ("/jobs/", "/heartbeat", "/prove", "/agent", "/tasks/", "/health",
            "/openapi", "/docs", "/static", "/api/v1", "/webhook", "/install.sh",
            "/manage.ps1", "/install.ps1", "/metrics", "/vm/register_tunnel",
            "/vm/*/route", "/backup", "/restore", "/notebook", "/solve",
            "/admin", "/email/verify", "/.well-known")
for v, p in sorted(routes):
    if any(p.startswith(i) for i in INTERNAL):
        continue
    if norm(p) in called_norm:
        continue
    if v == "GET" and p in {l for l in links}:      # it's a page, reachable by link
        continue
    if v == "GET" and norm(p) in {norm(x) for x in links}:
        continue
    orphans.append((v, p))

# ---------------------------------------------------------------- report
fail = 0
print("=" * 68)
print("FRONTEND <-> BACKEND CONTRACT AUDIT")
print("=" * 68)
print(f"\nbackend routes: {len(routes)}   frontend calls: {len(calls)}   "
      f"links: {len(links)}   dom ids used: {len(used)}")

print("\n--- 1. DEAD CALLS (frontend fetches an endpoint that does not exist) ---")
if dead_calls:
    fail += len(dead_calls)
    for v, p in dead_calls:
        print(f"  BROKEN  {v:5} {p}")
else:
    print("  none — every endpoint the UI calls exists")

print("\n--- 2. DEAD LINKS (href to a route that does not exist) ---")
if dead_links:
    fail += len(dead_links)
    for h in dead_links:
        print(f"  BROKEN  {h}")
else:
    print("  none — every link resolves")

print("\n--- 3. DEAD DOM IDS (getElementById on an element that isn't there) ---")
print("      ^ these are the silent killers: the script THROWS and everything")
print("        after it in that block never runs.")
if dead_ids:
    fail += len(dead_ids)
    for i in dead_ids:
        print(f"  BROKEN  getElementById('{i}') — no element with that id")
else:
    print("  none — every id the JS touches exists in the markup")

print("\n--- 4. ORPHAN ROUTES (backend works, but no UI reaches it) ---")
if orphans:
    for v, p in orphans:
        print(f"  unsurfaced  {v:5} {p}")
else:
    print("  none")

print("\n" + "=" * 68)
print(f"{'FAIL' if fail else 'PASS'}: {fail} broken frontend/backend contract(s)")
print("=" * 68)
sys.exit(1 if fail else 0)
