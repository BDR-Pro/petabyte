"""web_ui_test.py — the web UI's user-facing contract, asserted (no browser required).

A page can return HTTP 200 and still be broken UX: missing heading, a primary button
that isn't there, a form whose inputs lost their labels, a price that stopped rendering,
a 404 that dumps a stack trace. This suite renders the real app through Starlette's
TestClient and asserts the *contract a human depends on* — structure AND data — across
the important surfaces, plus accessibility, empty data, weird data, and failure states.

It deliberately checks the user-facing thing (a heading exists, a label is associated,
a price is present) — never brittle whitespace or CSS values. Client-rendered data
(marketplace cards, live prices) is asserted two ways: the JSON the JS consumes is
correct, and the page's own template still references the fields, so a redesign can't
silently drop them. The rendered-pixels layer is covered separately by the Playwright
suite (scripts/e2e/browser_ui_test.py).

Run:  python web_ui_test.py
"""
import base64
import os
import sys
import time
from collections import Counter
from html.parser import HTMLParser

os.environ.setdefault("SECRET_KEY", "web-ui-test")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/web_ui_test.db")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("WG_PUBLIC_KEY", "x")
os.environ.setdefault("WG_ENDPOINT", "y")
os.environ.setdefault("GOOGLE_OAUTH_STUB", "true")
os.environ.setdefault("NOTIFY_STUB", "true")
os.environ.setdefault("GEOIP_STUB", "true")
os.environ.setdefault("MIN_REPUTATION", "0")
if "SERVER_PRIVATE_KEY" not in os.environ:
    from cryptography.fernet import Fernet
    os.environ["SERVER_PRIVATE_KEY"] = Fernet.generate_key().decode()

for _f in ("/tmp/web_ui_test.db", "/tmp/web_ui_test.db-wal", "/tmp/web_ui_test.db-shm"):
    try:
        os.remove(_f)
    except OSError:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402  (lumaris_api/main.py — must resolve BEFORE the agent dir is on path)

# Only now add the seller-agent dir (it also has a main.py/crypto.py) so importing the
# real Ed25519 signer can't shadow the API's own modules.
os.environ.setdefault("PETABYTE_AGENT_KEY",
                      os.path.join("/tmp", "web_ui_test_agent_ed25519.key"))
sys.path.append(os.path.join(os.path.dirname(HERE), "lumaris_agent"))
try:
    import crypto as agent_crypto  # noqa: E402  (Ed25519 attestation, same as the real node)
except Exception:
    agent_crypto = None

client = TestClient(main.app, raise_server_exceptions=False)

_fail = 0
_section = ""


def section(name):
    global _section
    _section = name
    print(f"\n── {name} " + "─" * max(0, 50 - len(name)))


def ok(label, cond, extra=""):
    global _fail
    mark = "ok  " if cond else "FAIL"
    print(f"  {mark} {label}" + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        _fail += 1


# ---------------------------------------------------------------- tiny DOM model
class Dom(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.title = None
        self.headings = {"h1": [], "h2": [], "h3": []}
        self.links = []        # (href, text)
        self.labels = []       # (for, text)
        self.inputs = []       # dict of attrs
        self.textareas = []    # dict of attrs
        self.selects = []      # dict of attrs
        self.buttons = []      # (text, attrs)
        self.imgs = []         # attrs
        self.ids = []          # every id="" in the static markup
        self.wrapped_ids = set()   # inputs nested inside a <label> (implicit association)
        self.html_lang = None
        self._stack = []
        self._text_into = None
        self._buf = []
        self._html = html
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        if "id" in a:
            self.ids.append(a["id"])
        if tag in ("h1", "h2", "h3", "title", "label", "a", "button"):
            self._stack.append((tag, a))
            self._text_into = tag
            self._buf = []
        inside_label = any(t == "label" for t, _ in self._stack)
        if tag in ("input", "textarea", "select") and inside_label and a.get("id"):
            self.wrapped_ids.add(a["id"])          # implicit label association is valid a11y
        if tag == "input":
            self.inputs.append(a)
        elif tag == "textarea":
            self.textareas.append(a)
        elif tag == "select":
            self.selects.append(a)
        elif tag == "img":
            self.imgs.append(a)

    def handle_data(self, data):
        if self._text_into:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1][0] == tag:
            _, a = self._stack.pop()
            text = "".join(self._buf).strip()
            if tag == "title":
                self.title = text
            elif tag in ("h1", "h2", "h3"):
                self.headings[tag].append(text)
            elif tag == "a":
                self.links.append((a.get("href", ""), text))
            elif tag == "label":
                self.labels.append((a.get("for"), text))
            elif tag == "button":
                self.buttons.append((text, a))
            self._text_into = None
            self._buf = []

    # -- convenience queries --
    def input_ids(self):
        return {i.get("id") for i in self.inputs if i.get("id")}

    def all_field_ids(self):
        s = set()
        for coll in (self.inputs, self.textareas, self.selects):
            s |= {i.get("id") for i in coll if i.get("id")}
        return s

    def button_texts(self):
        return [t for t, _ in self.buttons if t]

    def has_nav(self):
        # the floating nav is <nav>…</nav> with the brand + links; check id + brand
        return "pbnav" in self.ids and ("Petabyte" in self._html)

    def label_targets(self):
        return {f for f, _ in self.labels if f}


def get(path, **kw):
    return client.get(path, **kw)


def dom(path, **kw):
    r = get(path, **kw)
    return r, Dom(r.text)


# ---------------------------------------------------------------- seed live data
def seed():
    """Bring a seller GPU online + a funded buyer, using the real endpoints (so prices,
    hardware and status are REAL backend-rendered values, not fixtures)."""
    ctx = {}
    for u in ("admin_web", "seller_web", "buyer_web"):
        client.post("/register_user", json={"username": u, "password": "pw-correct-horse-1"})

    def tok(u):
        r = client.post("/login", data={"username": u, "password": "pw-correct-horse-1"})
        return r.json().get("access_token") if r.status_code == 200 else None

    st, bt = tok("seller_web"), tok("buyer_web")
    ctx["seller_t"], ctx["buyer_t"] = st, bt
    client.post("/change_role", headers={"Authorization": f"Bearer {st}"}, json={"role": "seller"})
    kr = client.post("/create_api_key?days=90&scopes=node,jobs",
                     headers={"Authorization": f"Bearer {st}"})
    sk = {"X-API-KEY": kr.json().get("api_key")} if kr.status_code == 200 else {}
    sr = client.post("/register_specs", headers={"Authorization": f"Bearer {st}"},
                     json={"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 1.5,
                           "provider": "aurora-labs", "gpu_model": "NVIDIA RTX 4000 Ada",
                           "gpu_count": 1, "vram_gb": 20, "units": 4,
                           "region": "us-east", "country": "US"})
    ctx["spec_id"] = sr.json().get("spec_id") if sr.status_code == 200 else None
    if agent_crypto and ctx["spec_id"]:
        att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
               "ts": int(time.time())}
        client.post("/prove", headers={"Authorization": f"Bearer {st}"},
                    json={"spec_id": ctx["spec_id"], "attestation": att,
                          "signature": agent_crypto.sign_proof(att),
                          "pubkey": agent_crypto.public_key_b64()})
        client.post("/heartbeat", headers=sk, json={"spec_id": ctx["spec_id"]})
    # public marketplace view + a public id for the buy page
    specs = client.get("/marketplace/specs").json()
    specs = specs if isinstance(specs, list) else specs.get("specs", [])
    ctx["public_specs"] = specs
    ctx["public_id"] = specs[0]["id"] if specs else None
    return ctx


# ================================================================ 1. every key page renders
section("critical pages render (HTTP 200 + non-trivial HTML)")
PAGES = ["/", "/marketplace", "/pricing", "/install", "/login", "/account", "/app",
         "/seller/payouts", "/catalog", "/status", "/security", "/developers",
         "/gamers", "/artists", "/contact", "/demo"]
for p in PAGES:
    r = get(p)
    ok(f"{p} renders", r.status_code == 200 and len(r.text) > 1500, f"HTTP {r.status_code}")


# ================================================================ 2. shared shell + nav
section("brand, navigation and account controls")
for p in ["/", "/marketplace", "/pricing", "/account"]:
    r, d = dom(p)
    ok(f"{p} has a <title>", bool(d.title) and "Petabyte" in (d.title or ""), repr(d.title))
    ok(f"{p} exposes the nav (brand + links)", d.has_nav())
    ok(f"{p} has an <html lang> for screen readers", bool(d.html_lang), repr(d.html_lang))
# account controls stay reachable
_, d_home = dom("/")
ok("nav has a sign-in control", "signinlink" in d_home.ids)
ok("nav has a sign-out control (auth-gated)", "signoutlink" in d_home.ids)
ok("nav has an account/admin link", "adminlink" in d_home.ids or "mename" in d_home.ids)


# ================================================================ 3. homepage: heading + CTA
section("homepage headline and primary CTA")
r, d = dom("/")
ok("homepage has exactly-one/at-least-one <h1>", len(d.headings["h1"]) >= 1, str(d.headings["h1"]))
ok("homepage h1 is real copy (not empty)", any(len(h) > 8 for h in d.headings["h1"]))
ok("homepage links to the marketplace (primary journey)",
   any(h.rstrip("/").endswith("/marketplace") for h, _ in d.links))
ok("homepage links to becoming a seller (/install)",
   any("/install" in h for h, _ in d.links))


# ================================================================ 4. login form UX + a11y
section("login form: labels, inputs, submit, error slot")
r, d = dom("/login")
ok("login h1 says Sign in", any("sign in" in h.lower() for h in d.headings["h1"]))
ok("login has a username input (id=u)", "u" in d.input_ids())
ok("login has a password input (id=p)", "p" in d.input_ids())
ok("password input is type=password",
   any(i.get("id") == "p" and i.get("type") == "password" for i in d.inputs))
ok("login has Username + Password labels",
   any("username" in (t or "").lower() for _, t in d.labels)
   and any("password" in (t or "").lower() for _, t in d.labels))
# a11y: labels are associated with their inputs (for= matches an input id)
ok("login labels are associated with inputs (for= → input id)",
   {"u", "p"} <= d.label_targets(), f"label for= targets: {sorted(d.label_targets())}")
ok("login has a submit control", any("sign in" in (t or "").lower() for t in d.button_texts()))
ok("login has an error slot for validation messages", "err" in d.ids)
ok("login offers a path to register", any("register" in (t or "").lower()
   or "create" in (t or "").lower() for _, t in d.links + [(None, x) for x in d.button_texts()])
   or "togglelink" in d.ids)


# ================================================================ 5. marketplace scaffold + data
section("marketplace: filters, empty-state, and real prices/hardware in the data")
r, d = dom("/marketplace")
ok("marketplace h1 present", len(d.headings["h1"]) >= 1)
ok("marketplace has GPU + price + region filters",
   {"fgpu", "fprice", "fregion"} <= d.all_field_ids())
ok("marketplace has an Apply and a Reset control",
   any("apply" in t.lower() for t in d.button_texts()) and
   any("reset" in t.lower() for t in d.button_texts()))
ok("marketplace has a results container (mrows)", "mrows" in d.ids)
# empty state: the professional empty-state copy is in the template (client renders it on [])
ok("marketplace ships a real empty state (not a blank screen)",
   any(s in r.text.lower() for s in ("no gpus", "no matching", "nothing", "check back",
                                     "no results", "be the first")))
empty_specs = client.get("/marketplace/specs").json()
empty_specs = empty_specs if isinstance(empty_specs, list) else empty_specs.get("specs", [])
ok("marketplace API returns cleanly with zero online GPUs", isinstance(empty_specs, list))

ctx = seed()
ok("seeding brought a GPU online", bool(ctx.get("public_id")), "no public spec id")
mk = client.get("/marketplace/specs")
specs = mk.json()
specs = specs if isinstance(specs, list) else specs.get("specs", [])
mine = [s for s in specs if "RTX 4000 Ada" in (s.get("gpu_model") or "")]
ok("the seeded GPU is visible in the marketplace data", bool(mine))
if mine:
    s = mine[0]
    ok("marketplace data carries the hardware (gpu_model)", "RTX 4000 Ada" in s.get("gpu_model", ""))
    ok("marketplace data carries VRAM", int(s.get("vram_gb") or s.get("vram") or 0) == 20)
    ok("marketplace data carries a positive price",
       float(s.get("price_per_hour") or s.get("price") or 0) > 0)
    ok("marketplace data carries an online/availability signal",
       ("online" in s) or (s.get("available_units") is not None) or ("status" in s))
# the marketplace template still references the fields it must render (refactor guard)
ok("marketplace template still references gpu_model + price fields",
   ("gpu_model" in r.text) and ("price" in r.text.lower()))


# ================================================================ 6. buy / checkout page
section("buy page: hardware, price, primary action, code + payment inputs")
if ctx.get("public_id"):
    r, d = dom(f"/buy/{ctx['public_id']}")
    body = r.text
    # The interactive checkout form is injected by JS from a template, so assert the
    # template still carries the critical ids/labels (the rendered, clickable button is
    # asserted in the Playwright suite). This is a redesign refactor-guard.
    ok("buy page renders", r.status_code == 200)
    ok("buy page template carries the Rent & run action (buy_pay)", "buy_pay" in body)
    ok("buy page template carries a runtime-hours input", "buy_hours" in body)
    ok("buy page template carries a code input for the workload", "buy_code" in body)
    ok("buy page template carries progress + result + error regions",
       all(x in body for x in ("buy_progress", "buy_result", "buy_error")))
    ok("buy page template carries a Cancel/release control",
       "buy_cancel" in body or "cancel" in body.lower())
    ok("buy page labels the runtime + code + card fields",
       all(x in body for x in ("Max runtime", "Code to run", "Card details")))
    # data ground truth: the priced spec the page will fetch
    detail = client.get(f"/marketplace/specs/{ctx['public_id']}").json()
    ok("buy spec detail carries a price the page can show",
       float(detail.get("price_per_hour") or detail.get("price") or 0) > 0)
    ok("buy spec detail carries the hardware", bool(detail.get("gpu_model")))
else:
    ok("buy page (skipped — no public spec)", True)


# ================================================================ 7. buyer dashboard (/app)
section("buyer dashboard: balance, run-a-job, referral")
r, d = dom("/app")
ok("/app has a balance region", "bal" in d.ids)
ok("/app has a run-a-job control", any("run" in t.lower() for t in d.button_texts()))
ok("/app has an Add funds control", any("add funds" in t.lower() for t in d.button_texts()))
ok("/app has a GPU list region", "specs" in d.ids)


# ================================================================ 8. seller dashboard differs
section("seller dashboard: earnings, node status, payout onboarding")
r, d = dom("/seller/payouts")
ok("seller page h1 is about getting paid", any("paid" in h.lower() or "earn" in h.lower()
   for h in d.headings["h1"]))
ok("seller page has a node/status region", "nodes_box" in d.ids)
ok("seller page has an earnings region", "earn_rows" in d.ids or "earn_stats" in d.ids)
ok("seller page has Stripe payout onboarding", any("stripe" in t.lower() for t in d.button_texts()))
# buyer vs seller surfaces are genuinely different journeys
buyer_ids = set(Dom(get("/app").text).ids)
seller_ids = set(d.ids)
ok("buyer and seller dashboards are distinct surfaces",
   len(buyer_ids ^ seller_ids) > 10)


# ================================================================ 9. accessibility sweep (all pages)
section("accessibility: alt text, associated inputs, unique ids, button names")
A11Y_PAGES = ["/", "/marketplace", "/login", "/account", "/app", "/seller/payouts",
              "/pricing", "/install", "/status"]
for p in A11Y_PAGES:
    r, d = dom(p)
    # images have alt text
    no_alt = [i for i in d.imgs if "alt" not in i]
    ok(f"{p}: every <img> has alt text", not no_alt,
       f"{len(no_alt)} without alt: {[i.get('src') for i in no_alt][:3]}")
    # no duplicate static ids (breaks getElementById + a11y)
    dups = [k for k, v in Counter(d.ids).items() if v > 1]
    ok(f"{p}: no duplicate element ids", not dups, f"dups: {dups[:5]}")
    # every visible text/number/email input is labelled or aria-labelled
    unlabelled = []
    labelled = d.label_targets() | d.wrapped_ids       # explicit for= OR implicit wrapping
    for i in d.inputs + d.textareas + d.selects:
        typ = (i.get("type") or "text").lower()
        if typ in ("hidden", "checkbox", "radio", "submit", "button"):
            continue
        iid = i.get("id")
        if i.get("aria-label") or i.get("aria-labelledby") or i.get("title"):
            continue
        if iid and iid in labelled:
            continue
        unlabelled.append(iid or i.get("name") or typ)
    ok(f"{p}: every text input has a label or aria-label", not unlabelled,
       f"unlabelled: {unlabelled[:6]}")
    # buttons have an accessible name (text or aria-label)
    nameless = [a for t, a in d.buttons if not t and not a.get("aria-label")]
    ok(f"{p}: every <button> has an accessible name", not nameless,
       f"{len(nameless)} nameless")


# ================================================================ 10. failure states (no raw errors)
section("failure states: sane statuses, no stack traces leaked")
# a made-up page → a real 404, not a 500 with a traceback
r = get("/this-page-does-not-exist-xyz")
ok("unknown page returns 404 (not 500)", r.status_code == 404, f"HTTP {r.status_code}")
ok("404 body does not leak a Python traceback", "Traceback (most recent call last)" not in r.text)
# a protected API without auth → 401/403 JSON, not a crash
r = get("/wallet")
ok("protected API without auth is 401/403 (not 500)", r.status_code in (401, 403), f"HTTP {r.status_code}")
ok("unauthorized response does not leak a traceback", "Traceback (most recent call last)" not in r.text)
# a buy page for a non-existent spec still renders a shell (client shows a friendly error)
r = get("/buy/does-not-exist-spec")
ok("buy page for an unknown spec still returns a usable shell (200)", r.status_code == 200,
   f"HTTP {r.status_code}")
ok("unknown-spec buy page has an error region for the client message",
   "buy_error" in r.text or "buy_signedout" in r.text)
# malformed marketplace detail id → handled status, no 500 traceback
r = get("/marketplace/specs/%%%not-an-id%%%")
ok("malformed spec id is handled (no 5xx traceback)",
   r.status_code < 500 or "Traceback (most recent call last)" not in r.text, f"HTTP {r.status_code}")


# ================================================================ 11. empty vs weird data
section("resilience: empty data and long/unicode/large values")
# empty: buyer with no jobs — dashboard + jobs API must not crash
r = get("/app")
ok("buyer dashboard renders with zero jobs (no crash)", r.status_code == 200)
# weird: register a spec with a very long, unicode provider + a large price, then list it
long_provider = "Ǆ" + "aurora-über-long-provider-name-" * 4 + "🚀"
r_login = client.post("/login", data={"username": "seller_web", "password": "pw-correct-horse-1"})
st = r_login.json().get("access_token")
wr = client.post("/register_specs", headers={"Authorization": f"Bearer {st}"},
                 json={"cpu": 4, "ram": 8, "duration": 1, "price_per_hour": 999999.99,
                       "provider": long_provider, "gpu_model": "H100 " + "X" * 40,
                       "gpu_count": 8, "vram_gb": 640, "units": 1,
                       "region": "us-west", "country": "US"})
ok("API accepts/ rejects weird data without a 500",
   wr.status_code < 500, f"HTTP {wr.status_code}: {wr.text[:120]}")
mk = client.get("/marketplace/specs")
ok("marketplace still lists cleanly after weird data (no 5xx)", mk.status_code == 200)
ok("marketplace JSON stays valid with unicode + huge values", isinstance(mk.json(), (list, dict)))


# ================================================================ 12. JS-syntax + shell integrity note
section("no client-render trap: pages carry their scripts")
for p in ["/", "/marketplace", "/buy/" + (ctx.get("public_id") or "demo-spec")]:
    r = get(p)
    ok(f"{p} ships inline script (client render present)", "<script" in r.text)


print("\n" + "=" * 60)
print(f"{'PASS' if not _fail else 'FAIL — ' + str(_fail) + ' failing'}: web UI contract")
print("=" * 60)
sys.exit(1 if _fail else 0)
