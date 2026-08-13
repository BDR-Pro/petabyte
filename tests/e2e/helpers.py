"""helpers.py — reusable login + deterministic UX assertions for the browser E2E suite.

Kept small on purpose (minimise maintenance). UX checks are deterministic — no CV/AI scoring.
A UX problem that can't be asserted reliably is recorded as an observation, not a flaky assert.
"""
import os

import pytest

from report import REPORT

ROLES = ("buyer", "buyer_zero", "buyer_b", "seller", "seller_b", "admin")


def creds(role):
    """(identifier, password) from E2E_<ROLE>_USERNAME/PASSWORD (or _EMAIL), else None."""
    up = role.upper()
    ident = os.environ.get(f"E2E_{up}_USERNAME") or os.environ.get(f"E2E_{up}_EMAIL")
    pw = os.environ.get(f"E2E_{up}_PASSWORD")
    return (ident, pw) if ident and pw else None


def require_creds(role):
    c = creds(role)
    if not c:
        pytest.skip(f"no credentials for role '{role}' "
                    f"(set E2E_{role.upper()}_USERNAME/EMAIL + _PASSWORD as GitHub Secrets)")
    return c


def login(page, ident, password):
    """Log in via the real login form. Resilient to field naming; returns True on success."""
    page.goto("/login", wait_until="domcontentloaded")
    # username/email field
    for sel in ("input[name='username']", "input[type='email']", "input[name='email']",
                "input[type='text']"):
        loc = page.locator(sel)
        if loc.count() and loc.first.is_visible():
            loc.first.fill(ident)
            break
    page.locator("input[type='password']").first.fill(password)
    # submit
    for sel in ("button[type='submit']", "button:has-text('Sign in')",
                "button:has-text('Log in')", "button:has-text('Login')"):
        b = page.locator(sel)
        if b.count() and b.first.is_visible():
            b.first.click()
            break
    else:
        page.locator("input[type='password']").first.press("Enter")
    page.wait_for_load_state("networkidle")
    # logged-in signal: a sign-out affordance, or we left /login
    body = (page.locator("body").inner_text() or "").lower()
    return ("/login" not in page.url) or ("sign out" in body) or ("logout" in body)


# ------------------------------------------------------------------ UX assertions (deterministic)
def assert_no_horizontal_overflow(page, tolerance=2):
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > tolerance:
        REPORT.bump("overflow_failures")
        REPORT.bug(page=page.url, severity="medium",
                   problem=f"Horizontal overflow: content is {overflow}px wider than the viewport")
    assert overflow <= tolerance, f"horizontal overflow of {overflow}px at {page.url}"


def assert_primary_content_visible(page):
    # a real page has a visible primary heading / main region and non-trivial text
    has_heading = page.locator("h1, [role='heading'], main h2").first.is_visible() \
        if page.locator("h1, [role='heading'], main h2").count() else False
    text_len = len((page.locator("body").inner_text() or "").strip())
    assert has_heading or text_len > 200, \
        f"page looks blank/half-loaded at {page.url} (heading={has_heading}, text_len={text_len})"


def assert_no_major_console_errors(page):
    errs = list(getattr(page, "_pb_console", []))
    assert not errs, f"{len(errs)} console error(s) at {page.url}: {errs[:3]}"


def assert_no_critical_failed_requests(page):
    # ignore 401/403/404 (expected for auth probes); fail on 5xx or network failures
    bad = [f for f in getattr(page, "_pb_failed", [])
           if f[1] == "failed" or (isinstance(f[1], int) and f[1] >= 500)]
    assert not bad, f"{len(bad)} critical failed request(s) at {page.url}: {bad[:3]}"


def assert_button_visible_and_enabled(locator, name="button"):
    assert locator.count() and locator.first.is_visible(), f"{name} not visible"
    assert locator.first.is_enabled(), f"{name} is unexpectedly disabled"


def assert_form_labels_present(page):
    """Every visible, user-fillable input has a usable label (label/aria-label/placeholder)."""
    unlabeled = page.evaluate("""() => {
      const bad = [];
      for (const el of document.querySelectorAll('input, select, textarea')) {
        const t = (el.getAttribute('type') || '').toLowerCase();
        if (['hidden','submit','button','image'].includes(t)) continue;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;             // not visible
        const labelled = (el.labels && el.labels.length) ||
          el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
          el.getAttribute('placeholder') || el.getAttribute('title');
        if (!labelled) bad.push(el.name || el.id || t || 'input');
      }
      return bad;
    }""")
    assert not unlabeled, f"unlabeled form fields at {page.url}: {unlabeled[:5]}"


def observe(page, note):
    """Record a non-fatal UX observation (used where a reliable assertion isn't possible)."""
    REPORT.bug(page=getattr(page, "url", "?"), severity="observation", problem=note)
