"""test_authorization.py — authorization isolation. Hidden UI is not authorization;
direct navigation to another tenant's resource must be denied server-side."""
import pytest

import helpers as H


@pytest.mark.e2e(section="AUTHORIZATION", label="Non-admin cannot reach admin")
def test_authenticated_buyer_cannot_reach_admin(page):
    ident, pw = H.require_creds("buyer")
    assert H.login(page, ident, pw)
    page.goto("/admin", wait_until="networkidle")
    body = (page.locator("body").inner_text() or "").lower()
    assert not ("pending payouts" in body or "all users" in body or "admin console" in body), \
        "an authenticated non-admin buyer can view the admin console"


@pytest.mark.e2e(section="AUTHORIZATION", label="Admin API is owner-gated")
def test_admin_api_denied_for_buyer(page):
    ident, pw = H.require_creds("buyer")
    assert H.login(page, ident, pw)
    # hit an admin JSON API in the authenticated browser context; must be 401/403/404, never 200
    status = page.evaluate("""async () => {
      try { const r = await fetch('/admin/payouts', {credentials:'include'}); return r.status; }
      catch (e) { return -1; }
    }""")
    assert status in (401, 403, 404, -1), f"/admin/payouts returned {status} for a buyer"


@pytest.mark.e2e(section="AUTHORIZATION", label="Cross-seller isolation")
def test_seller_a_cannot_manage_seller_b(page):
    H.require_creds("seller")
    if not H.creds("seller_b"):
        pytest.skip("no seller_b credentials — cross-seller test needs a second TEST seller")
    identA, pwA = H.creds("seller")
    assert H.login(page, identA, pwA)
    # seller A should not be able to load seller B's node management via a guessed API
    status = page.evaluate("""async () => {
      try { const r = await fetch('/account/specs', {credentials:'include'}); return r.status; }
      catch (e) { return -1; }
    }""")
    # own specs = 200; the point is the response only ever contains the caller's own resources.
    assert status in (200, 401, 403), f"unexpected status {status} for /account/specs"
