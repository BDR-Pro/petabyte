#!/usr/bin/env python3
"""browser_ui_test.py — the redesign, proven in a real browser: responsive, interactable,
error-free, across the buyer and seller journeys.

Where web_ui_test.py asserts the server-rendered contract (fast, no browser), THIS drives
the actual rendered pixels through Chromium (Playwright), which is the only way to check
the things that only exist after layout + JS run:

  * RESPONSIVE — desktop / tablet / mobile: no horizontal overflow, nav stays usable,
    the primary action stays visible (a Rent button hidden under another element is a bug)
  * INTERACTABLE — the marketplace renders GPU cards with real prices/hardware; the buy
    page's Rent & run button is visible AND enabled
  * NO SERIOUS JS ERRORS — uncaught exceptions / same-origin console errors fail the run
    (offline CDN/font/Stripe load failures are filtered — they're the sandbox, not the app)
  * JOURNEYS — a buyer reaches a priced, bookable GPU; a seller sees node status + earnings

It reuses the hermetic bootstrap + seeding from local_e2e.py / browser_e2e.py (SQLite,
fake Stripe, no GPU). It SKIPS cleanly (exit 0) when Playwright/Chromium isn't installed,
so it's safe in run_tests.sh; CI installs Chromium and runs it for real.

Run:  python -m playwright install chromium   # once
      python scripts/e2e/browser_ui_test.py
"""
import base64
import os
import sys
import threading
import time

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import local_e2e as le          # noqa: E402  server bootstrap + agent crypto
import browser_e2e as be        # noqa: E402  reuse _seed / _launch / _node_loop

B = le.BASE
_fail = 0

VIEWPORTS = [
    ("desktop", 1280, 800),
    ("tablet", 768, 1024),
    ("mobile", 390, 844),
]

# Console noise that is the offline sandbox, not an app defect: the page pulls fonts,
# Bootstrap and Stripe.js from CDNs that are deliberately unreachable in this hermetic run.
_IGNORE_CONSOLE = (
    "fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "js.stripe.com",
    "net::err", "failed to load resource", "err_", "content security policy",
    "the stylesheet", "was preloaded using link preload", "favicon",
)


def ok(label, cond, extra=""):
    global _fail
    print(("ok   " if cond else "FAIL ") + label + (f"   [{extra}]" if extra and not cond else ""))
    if not cond:
        _fail += 1


def _serious(msg: str) -> bool:
    m = (msg or "").lower()
    return not any(sig in m for sig in _IGNORE_CONSOLE)


def _attach_error_capture(page, bucket):
    page.on("pageerror", lambda e: bucket.append(("pageerror", str(e))))
    page.on("console", lambda m: bucket.append(("console", m.text)) if m.type == "error" else None)


def _no_overflow(page) -> bool:
    # allow a couple of px for sub-pixel rounding
    return page.evaluate(
        "() => (document.documentElement.scrollWidth - document.documentElement.clientWidth) <= 2")


def _auth(page, username):
    # Sign the browser in through the real POST /login: the server sets the HttpOnly
    # pb_session cookie + the SIGNED pb_csrf cookie. enforce_csrf verifies the HMAC, so a
    # fabricated pb_csrf value would 403 every write the UI makes.
    page.context.clear_cookies()
    r = page.context.request.post(B + "/login", form={"username": username, "password": PW})
    if r.status != 200:
        raise RuntimeError(f"browser /login failed for {username}: HTTP {r.status}")
    page.goto(B + "/")


def _bearer(t):
    return {"Authorization": "Bearer " + t}


def _seed_below_reference_gpu(c, seller_t, sk):
    """List an H100 priced far below its cloud reference ($2.90 vs ~$12.29) so the buyer
    savings banner has real data to lead with. Uses the same real endpoints as the agent."""
    sr = c.post(f"{B}/register_specs", headers=_bearer(seller_t),
                json={"cpu": 16, "ram": 64, "duration": 24, "price_per_hour": 2.90,
                      "provider": "aurora-labs", "gpu_model": "NVIDIA H100", "gpu_count": 1,
                      "vram_gb": 80, "units": 2, "region": "us-east", "country": "US"})
    if sr.status_code != 200:
        return None
    spec_id = sr.json()["spec_id"]
    att = {"node": "petabyte-agent", "nonce": base64.b64encode(os.urandom(9)).decode(),
           "ts": int(time.time())}
    c.post(f"{B}/prove", headers=_bearer(seller_t),
           json={"spec_id": spec_id, "attestation": att,
                 "signature": le.agent_crypto.sign_proof(att),
                 "pubkey": le.agent_crypto.public_key_b64()})
    c.post(f"{B}/heartbeat", headers=sk, json={"spec_id": spec_id})
    return spec_id


def _fresh_buyer(c, name):
    c.post(f"{B}/register_user", json={"username": name, "password": PW})
    return le.token_for(c, name, PW)


def _heartbeat_keepalive(sk, spec_ids, stop):
    """Keep the seeded GPUs online for the whole run. The emulated node loop only claims
    jobs; without periodic heartbeats a spec drops out of the marketplace after
    HEARTBEAT_TIMEOUT_S, which would empty late-running sections (e.g. the phone check)."""
    with httpx.Client(timeout=10) as hc:
        while not stop.is_set():
            for sid in spec_ids:
                if sid:
                    try:
                        hc.post(f"{B}/heartbeat", headers=sk, json={"spec_id": sid})
                    except Exception:
                        pass
            stop.wait(30)


PW = "pw-correct-horse-1"


def run(pw, buyer_t, seller_t, pub, role_t):
    browser = be._launch(pw)
    try:
        # Data-dependent checks run FIRST, while the freshly-seeded GPU is still within its
        # heartbeat window; the layout sweep (which doesn't need a live GPU) runs last.

        # ---------- INTERACTABLE: marketplace cards render real data ----------
        print("\n-- marketplace: GPU cards render with hardware + price --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        page.goto(B + "/marketplace", wait_until="domcontentloaded")
        # cards are client-rendered from /marketplace/specs into #mrows (be._seed lists an NVIDIA L4)
        page.wait_for_function(
            "() => { const e = document.getElementById('mrows');"
            " return e && /NVIDIA|L4|GPU/i.test(e.textContent) && /\\$/.test(e.textContent); }",
            timeout=20000)
        rows = page.text_content("#mrows") or ""
        ok("marketplace renders the seeded GPU (hardware present)",
           "NVIDIA" in rows or "L4" in rows)
        ok("marketplace shows a price", "$" in rows)
        ok("marketplace shows hardware detail (VRAM/GB)", "GB" in rows or "vram" in rows.lower())
        ok("marketplace card exposes an availability/online signal",
           any(w in rows.lower() for w in ("online", "available", "verified", "unit", "rent", "view")))
        ok("marketplace has no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- INTERACTABLE: buy page primary action visible + enabled ----------
        print("\n-- buy page: Rent & run is visible AND enabled (not hidden/disabled) --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        _auth(page, "buyer1")
        page.goto(B + "/buy/" + pub, wait_until="domcontentloaded")
        page.wait_for_selector("#buy_pay", state="visible", timeout=20000)
        ok("buy: Rent & run button is visible", page.locator("#buy_pay").is_visible())
        ok("buy: Rent & run button is enabled", not page.is_disabled("#buy_pay"))
        ok("buy: a price is shown to the buyer", "$" in (page.text_content("#buywrap") or page.content()))
        # mobile: the primary action must not fall off-screen or overflow horizontally
        page.set_viewport_size({"width": 390, "height": 844})
        ok("buy [mobile]: no horizontal overflow", _no_overflow(page))
        ok("buy [mobile]: Rent & run still visible", page.locator("#buy_pay").is_visible())
        ok("buy: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- JOURNEY: AWS-style Launch Compute (/launch) ----------
        print("\n-- launch: guided launcher, template-first + machine-first --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        page.on("dialog", lambda d: d.accept("E2E launch template"))  # save-as-template prompt()
        _auth(page, "buyer1")
        # template-first
        page.goto(B + "/launch", wait_until="domcontentloaded")
        page.wait_for_selector("#tgrid .pick", timeout=20000)
        ok("launch: workload cards render from the curated catalog (/templates)",
           page.locator("#tgrid .pick").count() >= 5)
        page.click('#tgrid .pick[data-v="jupyter"]')
        page.wait_for_selector("#costbody .sumrow", timeout=20000)
        cost = page.text_content("#costbody") or ""
        ok("launch: server-priced cost panel appears after choosing a template",
           "$" in cost and "Estimated total" in cost)
        ok("launch: the chosen template is visually selected (aria-checked)",
           page.get_attribute('#tgrid .pick[data-v="jupyter"]', "aria-checked") == "true")
        ok("launch: a Review & Launch action is offered to the signed-in buyer",
           page.locator("#reviewbtn").is_visible())
        # change the template — selection must move
        page.click('#tgrid .pick[data-v="ollama"]')
        page.wait_for_timeout(300)
        ok("launch: changing the template updates the selection",
           page.get_attribute('#tgrid .pick[data-v="ollama"]', "aria-checked") == "true"
           and page.get_attribute('#tgrid .pick[data-v="jupyter"]', "aria-checked") == "false")
        # save a reusable launch template (localStorage, no secrets) + survive reload
        page.click("#savetplbtn")
        page.wait_for_timeout(400)
        ok("launch: save-as-template stores a reusable config",
           page.locator("#mytplgrid .pick").count() >= 1)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#tgrid .pick", timeout=20000)
        page.wait_for_timeout(400)
        ok("launch: saved templates persist across reload (localStorage)",
           page.locator("#mytpls").is_visible())
        # machine-first: /launch?spec= preselects custom-code and prices THAT host
        page.goto(B + "/launch?spec=" + pub, wait_until="domcontentloaded")
        page.wait_for_selector("#costbody .sumrow", timeout=20000)
        ok("launch [machine-first]: ?spec= prices the chosen host",
           "$" in (page.text_content("#costbody") or ""))
        ok("launch [machine-first]: the chosen host is selected in the list",
           page.locator('#mlist .mpick[aria-checked="true"]').count() >= 1)
        # mobile: no horizontal overflow (the card descriptions used to spill)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        ok("launch [mobile]: no horizontal overflow", _no_overflow(page))
        ok("launch: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:140])
        page.close()

        # anonymous: can browse + see price, but the launch action is gated behind sign-in
        print("\n-- launch: anonymous user is gated at launch --")
        apage = browser.new_page(viewport={"width": 1280, "height": 900})
        aerrs = []
        _attach_error_capture(apage, aerrs)
        apage.goto(B + "/launch", wait_until="domcontentloaded")
        apage.wait_for_selector("#tgrid .pick", timeout=20000)
        ok("launch [anon]: guests see a sign-in prompt", apage.locator("#lc_signedout").is_visible())
        apage.click('#tgrid .pick[data-v="jupyter"]')
        apage.wait_for_timeout(800)
        ok("launch [anon]: the launch action is hidden until sign-in",
           not apage.locator("#reviewbtn").is_visible())
        ok("launch [anon]: no serious JS errors", not [m for k, m in aerrs if _serious(m)],
           "; ".join(m for k, m in aerrs if _serious(m))[:140])
        apage.close()

        # ---------- JOURNEY: seller dashboard shows status + earnings ----------
        print("\n-- seller journey: node status + earnings render --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        _auth(page, "seller1")
        page.goto(B + "/seller/payouts", wait_until="domcontentloaded")
        page.wait_for_selector("#nodes_box", timeout=20000)
        page.wait_for_function(
            "() => { const e=document.getElementById('nodes_box');"
            " return e && e.textContent.trim().length > 0 && e.textContent.indexOf('loading')<0; }",
            timeout=20000)
        nodes = page.text_content("#nodes_box") or ""
        ok("seller: node status region renders (online/verified/offline)",
           any(w in nodes.lower() for w in ("online", "verified", "offline", "node")))
        ok("seller: earnings region is present", page.locator("#earn_rows, #earn_stats").first.count() > 0)
        page.set_viewport_size({"width": 390, "height": 844})
        ok("seller [mobile]: no horizontal overflow", _no_overflow(page))
        ok("seller: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- BUYER value prop: lead with cheap-vs-hyperscaler savings ----------
        print("\n-- buyer: marketplace leads with savings vs AWS/GCP/Azure --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        page.goto(B + "/marketplace", wait_until="domcontentloaded")
        page.wait_for_selector("#savingsbanner", state="visible", timeout=20000)
        banner = page.text_content("#savingsbanner") or ""
        ok("savings banner is visible on the marketplace", page.locator("#savingsbanner").is_visible())
        ok("savings banner names a hyperscaler (AWS)", "AWS" in banner)
        ok("savings banner shows a concrete percentage", "%" in banner)
        ok("marketplace savings: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- ROLE SWITCH: a buyer becomes a seller from the web UI ----------
        print("\n-- role switch: a buyer becomes a seller from /account --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        _auth(page, "roleswitch_web")
        page.goto(B + "/account", wait_until="domcontentloaded")
        page.wait_for_selector("#roleswitch", state="visible", timeout=20000)
        label = page.text_content("#roleswitch") or ""
        ok("role-switch control is visible for a signed-in user",
           page.locator("#roleswitch").is_visible())
        ok("role-switch invites a buyer to sell (earnings framing)",
           "seller" in label.lower() or "earn" in label.lower())
        page.click("#roleswitch")
        page.wait_for_url("**/install", timeout=20000)
        ok("switching to seller lands on the onboarding page", "/install" in page.url)
        ok("role switch: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- SELLER value prop: the earnings calculator is LIVE + correct ----------
        print("\n-- seller: NiceHash-style earnings calculator responds to the slider --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        page.goto(B + "/install", wait_until="domcontentloaded")
        page.wait_for_selector("#calc_month", timeout=15000)
        page.fill("#calc_price", "2.00")

        def month_at(util):
            page.eval_on_selector(
                "#calc_util",
                "(el, v) => { el.value = String(v); el.dispatchEvent(new Event('input', {bubbles:true})); }",
                util)
            txt = (page.text_content("#calc_month") or "$0").replace("$", "").replace(",", "")
            try:
                return int(txt)
            except ValueError:
                return 0

        high = month_at(100)
        low = month_at(25)
        ok("calculator shows a non-zero monthly estimate", high > 0, str(high))
        ok("dragging utilization up increases earnings (slider is live)", high > low, f"{high} vs {low}")
        ok("earnings scale correctly with utilization (100% == 4x25%)",
           abs(high - low * 4) <= 5, f"{high} vs {low}*4")
        label = page.text_content("#calc_util_val") or ""
        ok("the utilization % label tracks the slider", "25%" in label or "100%" in label, label)
        # 'Suggest a price' pulls a server-derived rate into the calculator
        page.fill("#pgpu", "H100")
        page.click("button:has-text('Suggest a price')")
        page.wait_for_function(
            "() => { var p = document.getElementById('calc_price'); return p && parseFloat(p.value) > 0; }",
            timeout=10000)
        ok("'Suggest a price' fills a server-derived rate",
           float(page.input_value("#calc_price")) > 0)
        page.set_viewport_size({"width": 390, "height": 844})
        ok("calculator [mobile]: output grid does not overflow", _no_overflow(page))
        ok("calculator: no serious JS errors", not [m for k, m in errs if _serious(m)],
           "; ".join(m for k, m in errs if _serious(m))[:120])
        page.close()

        # ---------- PHONE ergonomics: no iOS-zoom inputs, tappable controls, cards not tables ----------
        print("\n-- phone: 16px inputs, 44px tap targets, tables become labelled cards --")
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        errs = []
        _attach_error_capture(page, errs)
        page.goto(B + "/marketplace", wait_until="domcontentloaded")
        page.wait_for_selector("#fgpu", timeout=15000)   # the filter form — no live GPU needed
        m = page.evaluate("""() => {
          const vis = el => el.offsetParent !== null && el.getBoundingClientRect().height > 0;
          const inputs = [...document.querySelectorAll('input:not([type=checkbox]):not([type=radio]),select,textarea')].filter(vis);
          const btns = [...document.querySelectorAll('.btn,button')].filter(vis).filter(el => (el.textContent||'').trim().length > 1);
          const td = document.querySelector('.tbl td');
          return {
            minFont: inputs.length ? Math.min(...inputs.map(el => parseFloat(getComputedStyle(el).fontSize))) : 99,
            minBtnH: btns.length ? Math.min(...btns.map(el => Math.round(el.getBoundingClientRect().height))) : 99,
            tdDisplay: td ? getComputedStyle(td).display : 'none'
          };
        }""")
        ok("phone: form inputs are >=16px so iOS does not zoom on focus", m["minFont"] >= 16, str(m["minFont"]))
        ok("phone: primary buttons meet the ~44px tap-target minimum", m["minBtnH"] >= 44, str(m["minBtnH"]))
        ok("phone: the GPU table becomes stacked cards (not a cramped, side-scrolling table)",
           m["tdDisplay"] in ("block", "flex"), m["tdDisplay"])
        # the labelled-card check needs a real data row; degrade gracefully instead of
        # crashing the whole suite if the marketplace happens to be empty.
        try:
            page.wait_for_selector('#mrows td[data-l="GPU"]', timeout=15000)
            lab = page.evaluate("""() => {
              // Data cells must carry a stacked-card label; action-button cells (.tbl-action)
              // are self-describing and intentionally label-less (same as the pricing table).
              const tds = [...document.querySelectorAll('#mrows td')].filter(td =>
                td.offsetParent !== null && (td.textContent||'').trim() && !td.classList.contains('tbl-action'));
              return {total: tds.length, withLabel: tds.filter(td => td.getAttribute('data-l')).length};
            }""")
            ok("phone: every marketplace card cell carries its label (data-l)",
               lab["total"] > 0 and lab["withLabel"] == lab["total"], f"{lab['withLabel']}/{lab['total']}")
        except Exception:
            ok("phone: marketplace rendered a data row for the labelled-card check", False,
               "no online GPU row within timeout")
        ok("phone marketplace: no serious JS errors", not [x for k, x in errs if _serious(x)],
           "; ".join(x for k, x in errs if _serious(x))[:120])
        page.close()

        # inputs on the auth + onboarding forms must also be zoom-proof, and long code wraps
        for path, sel in [("/login", "#u"), ("/install", "#calc_price")]:
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
            page.goto(B + path, wait_until="domcontentloaded")
            page.wait_for_selector(sel, timeout=15000)
            fs = page.eval_on_selector(sel, "el => parseFloat(getComputedStyle(el).fontSize)")
            ok(f"phone {path}: input is >=16px (no iOS zoom)", fs >= 16, str(fs))
            ok(f"phone {path}: no horizontal overflow", _no_overflow(page))
            page.close()

        # ---------- RESPONSIVE across viewports (layout only; no live GPU needed) ----------
        print("\n-- responsive: no horizontal overflow, nav + primary action usable --")
        pages = [("/", "home"), ("/marketplace", "marketplace"), ("/login", "login"),
                 ("/pricing", "pricing"), ("/install", "install"), ("/account", "account")]
        for vname, w, h in VIEWPORTS:
            page = browser.new_page(viewport={"width": w, "height": h})
            errs = []
            _attach_error_capture(page, errs)
            for path, name in pages:
                page.goto(B + path, wait_until="domcontentloaded")
                page.wait_for_selector("nav", timeout=15000)
                ok(f"[{vname}] {name}: no horizontal overflow", _no_overflow(page),
                   "scrollWidth > clientWidth")
                ok(f"[{vname}] {name}: nav present", page.locator("nav").first.is_visible())
                if vname == "mobile":
                    # the nav must collapse to a usable toggler, not just clip its links
                    ok(f"[mobile] {name}: hamburger toggler is usable",
                       page.locator(".navbar-toggler").first.is_visible())
                else:
                    ok(f"[{vname}] {name}: brand is visible", page.locator(".brand").first.is_visible())
            serious = [m for k, m in errs if _serious(m)]
            ok(f"[{vname}] no serious JS/console errors across pages", not serious,
               "; ".join(serious[:2]))
            page.close()
    finally:
        browser.close()


def main():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("SKIP: Playwright is not installed — this is an opt-in browser suite.")
        print("      enable it with:  pip install playwright && python -m playwright install chromium")
        return 0

    proc, log, _db = le.start_server()
    stop = threading.Event()
    node_t = None
    try:
        if not le.wait_up():
            print("SERVER FAILED TO START — last log lines:")
            try:
                print(open(log.name).read()[-2000:])
            except Exception:
                pass
            return 2
        with httpx.Client(timeout=30) as c:
            seller_t, buyer_t, sk, pub = be._seed(c)
            if not pub:
                print("no bookable spec — cannot run the browser UI suite")
                return 1
            h100_spec = _seed_below_reference_gpu(c, seller_t, sk)   # a GPU cheaper than its cloud ref
            role_t = _fresh_buyer(c, "roleswitch_web")   # a throwaway user for the role-switch journey
            node_t = threading.Thread(target=be._node_loop, args=(sk, stop), daemon=True)
            node_t.start()
            # keep the seeded GPU online across the whole suite (late sections need it)
            threading.Thread(target=_heartbeat_keepalive, args=(sk, [h100_spec], stop),
                             daemon=True).start()
            try:
                with sync_playwright() as pw:
                    run(pw, buyer_t, seller_t, pub, role_t)
            except Exception as e:
                # A missing browser binary is an environment issue, not a UI failure — skip.
                if "executable" in str(e).lower() or "browsertype.launch" in str(e).lower():
                    print(f"SKIP: Chromium unavailable ({e}). Run: python -m playwright install chromium")
                    return 0
                raise
    finally:
        stop.set()
        if node_t:
            node_t.join(timeout=3)
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

    print(f"\n=== browser_ui_test: {'0 failures' if not _fail else str(_fail) + ' FAILED'} ===")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
