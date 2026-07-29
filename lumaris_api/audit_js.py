"""
audit_js.py — extract the JavaScript from every rendered page and PARSE it.

A Python test suite happily passes while the frontend is completely broken: a single
unbalanced quote in a JS string means the browser throws a SyntaxError, the whole
<script> block never executes, and the page renders as a dead shell. HTTP 200, zero
functionality.

The only honest way to check is to hand the JS to a real JavaScript engine. This
renders every page through the app and runs `node --check` on each script block.
"""
import os
import re
import subprocess
import sys
import tempfile

os.environ.setdefault("SECRET_KEY", "t")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/audit_js.db")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "w")
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("GOOGLE_OAUTH_STUB", "true")
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi.testclient import TestClient   # noqa: E402
import main                                  # noqa: E402

c = TestClient(main.app)

PAGES = ["/", "/marketplace", "/pricing", "/install", "/security", "/developers",
         "/account", "/login", "/keys", "/status", "/catalog", "/gamers", "/artists",
         "/privacy", "/terms", "/acceptable-use", "/demo", "/contact", "/app"]   # HTML pages only; the rest are JSON APIs

fail = 0
checked = 0
print("=" * 68)
print("RENDERED JAVASCRIPT SYNTAX AUDIT")
print("(a broken <script> = a dead page that still returns HTTP 200)")
print("=" * 68)

for path in PAGES:
    r = c.get(path)
    if r.status_code != 200:
        # A page in this list that does not render is itself a bug worth failing on.
        print(f"  BROKEN {path:16} HTTP {r.status_code} — page does not exist")
        fail += 1
        continue
    # Only executable JS. <script type="application/ld+json"> is structured data,
    # not code — node would rightly reject it.
    blocks = [m.group(2) for m in re.finditer(
        r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", r.text, re.S)
        if "type=" not in m.group(1)
        or "javascript" in m.group(1) or "module" in m.group(1)]
    if not blocks:
        print(f"  --    {path:16} no inline script")
        continue
    page_ok = True
    for n, js in enumerate(blocks):
        if not js.strip():
            continue
        checked += 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
            tmp = f.name
        p = subprocess.run(["node", "--check", tmp],
                           capture_output=True, text=True)
        os.unlink(tmp)
        if p.returncode != 0:
            page_ok = False
            fail += 1
            err = (p.stderr.strip().split("\n") or [""])[0:4]
            print(f"  BROKEN {path:16} script #{n + 1}")
            for line in err:
                print(f"         {line}")
    if page_ok:
        print(f"  ok    {path:16} {len(blocks)} script block(s) parse")

print("\n" + "=" * 68)
print(f"{'FAIL' if fail else 'PASS'}: {checked} script blocks checked, {fail} broken")
print("=" * 68)
sys.exit(1 if fail else 0)
