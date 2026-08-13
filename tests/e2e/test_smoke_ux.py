"""test_smoke_ux.py — anonymous visitor + UX/UI quality, desktop and mobile.

Runs with NO credentials, so it always executes in CI. Checks real rendered UI (not HTTP 200):
primary content present, no horizontal overflow, forms labelled, no major console errors / 5xx,
and that protected pages are not reachable anonymously.
"""
import pytest

from conftest import DESKTOP, MOBILE
import helpers as H

PUBLIC_PAGES = ["/", "/marketplace", "/login"]
VIEWPORTS = [("desktop", DESKTOP), ("mobile", MOBILE)]


@pytest.mark.e2e(section="UX/UI", label="Anonymous public pages")
@pytest.mark.parametrize("path", PUBLIC_PAGES)
@pytest.mark.parametrize("vp_name,vp", VIEWPORTS, ids=[v[0] for v in VIEWPORTS])
def test_public_page_renders(page_factory, path, vp_name, vp):
    page = page_factory(vp)
    page.goto(path, wait_until="networkidle")
    H.assert_primary_content_visible(page)
    H.assert_no_horizontal_overflow(page)
    H.assert_no_critical_failed_requests(page)
    H.assert_no_major_console_errors(page)


@pytest.mark.e2e(section="UX/UI", label="Landing CTA + navigation")
def test_landing_has_cta_and_nav(page):
    page.goto("/", wait_until="networkidle")
    # a primary call-to-action link/button exists and is usable
    cta = page.locator(
        "a[href*='marketplace'], a[href*='install'], a[href*='login'], "
        "button:has-text('Get started'), a:has-text('Rent'), a:has-text('List')")
    H.assert_button_visible_and_enabled(cta.first if cta.count() else cta, "primary CTA")
    # navigation is present
    assert page.locator("nav a, header a").count() >= 1, "no navigation links on the landing page"


@pytest.mark.e2e(section="UX/UI", label="Login form is usable")
def test_login_form_usable(page):
    page.goto("/login", wait_until="networkidle")
    assert page.locator("input[type='password']").count() >= 1, "no password field on /login"
    H.assert_form_labels_present(page)
    H.assert_no_horizontal_overflow(page)
    submit = page.locator("button[type='submit'], button:has-text('Sign in'), "
                          "button:has-text('Log in')")
    H.assert_button_visible_and_enabled(submit.first if submit.count() else submit, "login submit")


@pytest.mark.e2e(section="AUTHORIZATION", label="Admin protection (anonymous)")
def test_admin_pages_blocked_anonymously(page):
    # direct navigation to admin must NOT expose the admin console to an anonymous visitor
    page.goto("/admin", wait_until="networkidle")
    body = (page.locator("body").inner_text() or "").lower()
    on_admin = "/admin" in page.url
    looks_admin = any(w in body for w in ("pending payouts", "all users", "admin console"))
    assert (not on_admin) or (not looks_admin), \
        "admin console content is visible to an anonymous visitor"


@pytest.mark.e2e(section="AUTHORIZATION", label="Protected buyer routes (anonymous)")
@pytest.mark.parametrize("path", ["/account", "/wallet"])
def test_protected_routes_blocked_anonymously(page_factory, path):
    page = page_factory(DESKTOP)
    resp = page.goto(path, wait_until="networkidle")
    body = (page.locator("body").inner_text() or "").lower()
    # either redirected to login, or the page shows a sign-in prompt rather than private data
    redirected = "/login" in page.url or (resp is not None and resp.status in (401, 403))
    prompts_login = "sign in" in body or "log in" in body or "login" in body
    assert redirected or prompts_login, \
        f"{path} did not require authentication for an anonymous visitor"
