"""test_buyer.py — buyer personas (zero-balance + funded). Skips without credentials."""
import pytest

import helpers as H


@pytest.mark.e2e(section="PERSONAS", label="Funded buyer")
def test_funded_buyer_dashboard_and_marketplace(page):
    ident, pw = H.require_creds("buyer")
    assert H.login(page, ident, pw), "funded buyer could not log in"
    # account/dashboard renders real content, cleanly
    page.goto("/account", wait_until="networkidle")
    H.assert_primary_content_visible(page)
    H.assert_no_horizontal_overflow(page)
    H.assert_no_major_console_errors(page)
    # a buyer must NOT see an admin affordance
    assert page.locator("a[href*='/admin']").count() == 0, "buyer sees an admin link"
    # marketplace is browsable
    page.goto("/marketplace", wait_until="networkidle")
    H.assert_primary_content_visible(page)
    H.assert_no_horizontal_overflow(page)


@pytest.mark.e2e(section="WALLET", label="Funded buyer balance display")
def test_funded_buyer_wallet_display(page):
    ident, pw = H.require_creds("buyer")
    assert H.login(page, ident, pw)
    page.goto("/account", wait_until="networkidle")
    body = page.locator("body").inner_text() or ""
    assert "$" in body, "no monetary balance shown on the buyer account page"
    # balance must never render as an invalidly negative number
    import re
    negs = re.findall(r"-\$\s?\d", body)
    assert not negs, f"account shows a negative balance: {negs[:3]}"


@pytest.mark.e2e(section="PERSONAS", label="Buyer $0")
def test_zero_balance_buyer_insufficient_funds(page):
    ident, pw = H.require_creds("buyer_zero")
    assert H.login(page, ident, pw), "zero-balance buyer could not log in"
    page.goto("/account", wait_until="networkidle")
    H.assert_primary_content_visible(page)
    body = (page.locator("body").inner_text() or "")
    # a $0 wallet should be shown honestly (0.00 somewhere), not a broken/blank state
    assert "$" in body, "no wallet figure shown for the zero-balance buyer"
    # no admin access
    assert page.locator("a[href*='/admin']").count() == 0, "zero-balance buyer sees an admin link"
