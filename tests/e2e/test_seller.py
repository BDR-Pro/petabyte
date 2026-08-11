"""test_seller.py — seller persona: dashboard, listing visibility, no admin access."""
import pytest

import helpers as H


@pytest.mark.e2e(section="PERSONAS", label="Seller")
def test_seller_dashboard_and_no_admin(page):
    ident, pw = H.require_creds("seller")
    assert H.login(page, ident, pw), "seller could not log in"
    page.goto("/account", wait_until="networkidle")
    H.assert_primary_content_visible(page)
    H.assert_no_horizontal_overflow(page)
    H.assert_no_major_console_errors(page)
    # a seller must NOT reach the admin console
    page.goto("/admin", wait_until="networkidle")
    body = (page.locator("body").inner_text() or "").lower()
    assert not ("pending payouts" in body or "all users" in body), \
        "seller can view the admin console"


@pytest.mark.e2e(section="PERSONAS", label="Seller listings visible")
def test_seller_sees_own_listings_area(page):
    ident, pw = H.require_creds("seller")
    assert H.login(page, ident, pw)
    # the seller's node/listing management area renders (nodes table or an empty-state CTA)
    page.goto("/account", wait_until="networkidle")
    body = (page.locator("body").inner_text() or "").lower()
    assert any(w in body for w in ("node", "gpu", "listing", "earnings", "list your")), \
        "no seller node/listing/earnings area visible on the seller account page"
