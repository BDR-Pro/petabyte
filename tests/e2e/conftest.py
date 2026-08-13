"""conftest.py — Petabyte browser E2E harness (Playwright sync API, Chromium headless).

Design goals: minimal operator work, safe (TEST-only, never LIVE), and a human-readable
report generated even on failure. Login-gated personas skip cleanly when their GitHub Secret
credentials are absent, so the no-account tests (anonymous + UX + protected-route) always run.
"""
import os
import urllib.request
import json

import pytest

from report import REPORT

BASE_URL = os.environ.get("E2E_BASE_URL", "https://test.petabyte.market").rstrip("/")
CHROMIUM_PATH = os.environ.get("E2E_CHROMIUM_PATH")          # pre-installed browser override
DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}
ARTIFACTS = os.path.join(os.getcwd(), "artifacts")

# console errors that are noise on many sites and not worth failing the run over
BENIGN_CONSOLE = ("favicon.ico", "ResizeObserver loop", "Download the React DevTools")


# --------------------------------------------------------------------------- safety first
def _fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "null")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e(section, label): group a test in the report")
    # SAFETY: refuse to run browser flows against a LIVE-money environment. We check the app's
    # own /payments/config. If it's unreachable we warn and continue (the tests will skip/fail),
    # but if it looks LIVE we abort the whole session.
    try:
        cfg = _fetch_json(f"{BASE_URL}/payments/config") or {}
    except Exception as e:  # noqa: BLE001
        print(f"[e2e-safety] could not read {BASE_URL}/payments/config ({e}); "
              "continuing — payment tests will skip if the site is unreachable.")
        return
    mode = str(cfg.get("mode") or cfg.get("stripe_mode") or "").lower()
    gateway = str(cfg.get("gateway") or cfg.get("stripe_gateway") or "").lower()
    live = bool(cfg.get("payments_live_enabled") or cfg.get("live"))
    if live or mode == "live" or gateway == "live":
        pytest.exit(f"[e2e-safety] ABORT: {BASE_URL} looks LIVE "
                    f"(mode={mode!r} gateway={gateway!r} live={live}). Refusing to run.", 2)
    print(f"[e2e-safety] OK: {BASE_URL} is TEST mode (mode={mode!r} gateway={gateway!r}).")


# --------------------------------------------------------------------------- browser fixtures
@pytest.fixture(scope="session")
def _playwright():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(_playwright):
    kwargs = {"headless": True, "args": ["--no-sandbox"]}
    if CHROMIUM_PATH:
        kwargs["executable_path"] = CHROMIUM_PATH
    b = _playwright.chromium.launch(**kwargs)
    yield b
    b.close()


@pytest.fixture
def page_factory(browser, request):
    """Return make(viewport=DESKTOP) -> page. Each page captures console errors + failed
    requests, and is traced; on test failure a screenshot + trace zip land in artifacts/."""
    created = []

    def make(viewport=None):
        ctx = browser.new_context(viewport=viewport or DESKTOP, base_url=BASE_URL,
                                  ignore_https_errors=False)
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        page._pb_console = []          # type: ignore[attr-defined]
        page._pb_failed = []           # type: ignore[attr-defined]

        def on_console(msg):
            if msg.type == "error" and not any(b in (msg.text or "") for b in BENIGN_CONSOLE):
                page._pb_console.append(msg.text)

        def on_response(resp):
            try:
                if resp.status >= 400 and resp.url.startswith(BASE_URL):
                    page._pb_failed.append((resp.url, resp.status))
            except Exception:  # noqa: BLE001
                pass

        page.on("console", on_console)
        page.on("response", on_response)
        page.on("requestfailed", lambda req: page._pb_failed.append((req.url, "failed")))
        created.append((ctx, page))
        return page

    yield make

    failed = getattr(request.node, "rep_call", None) and request.node.rep_call.failed
    safe = request.node.name.replace("/", "_").replace(":", "_")
    os.makedirs(ARTIFACTS, exist_ok=True)
    for i, (ctx, page) in enumerate(created):
        # roll up console/request signals into the report
        REPORT.bump("console_errors", len(page._pb_console))
        REPORT.bump("failed_requests", len(page._pb_failed))
        try:
            if failed:
                shot = os.path.join(ARTIFACTS, f"{safe}_{i}.png")
                page.screenshot(path=shot, full_page=True)
                trace = os.path.join(ARTIFACTS, f"{safe}_{i}.trace.zip")
                ctx.tracing.stop(path=trace)
                REPORT.bug(page=request.node.name, severity="high",
                           problem=(request.node.rep_call.longreprtext.splitlines()[-1]
                                    if request.node.rep_call else "test failed")[:200],
                           evidence=os.path.relpath(shot))
            else:
                ctx.tracing.stop()
        except Exception:  # noqa: BLE001
            pass
        ctx.close()


@pytest.fixture
def page(page_factory):
    return page_factory(DESKTOP)


# --------------------------------------------------------------------------- outcome -> report
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
    if rep.when == "call" or (rep.when == "setup" and rep.skipped):
        marker = item.get_closest_marker("e2e")
        section = (marker.kwargs.get("section") if marker else None) or "UX/UI"
        label = (marker.kwargs.get("label") if marker else None) or item.name
        status = "pass" if rep.passed else "fail" if rep.failed else "skip"
        REPORT.record(section, label, status)


def pytest_sessionfinish(session, exitstatus):
    text = REPORT.write()
    print("\n" + text)
