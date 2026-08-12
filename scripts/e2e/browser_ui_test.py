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
import os
import sys
import threading

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


def _auth(page, token):
    page.goto(B + "/")
    page.evaluate("t => localStorage.setItem('pb_token', t)", token)


def run(pw, buyer_t, seller_t, pub):
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
        _auth(page, buyer_t)
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

        # ---------- JOURNEY: seller dashboard shows status + earnings ----------
        print("\n-- seller journey: node status + earnings render --")
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        _attach_error_capture(page, errs)
        _auth(page, seller_t)
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

        # ---------- RESPONSIVE across viewports (layout only; no live GPU needed) ----------
        print("\n-- responsive: no horizontal overflow, nav + primary action usable --")
        pages = [("/", "home"), ("/marketplace", "marketplace"), ("/login", "login"),
                 ("/pricing", "pricing"), ("/install", "install")]
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
            node_t = threading.Thread(target=be._node_loop, args=(sk, stop), daemon=True)
            node_t.start()
            try:
                with sync_playwright() as pw:
                    run(pw, buyer_t, seller_t, pub)
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
