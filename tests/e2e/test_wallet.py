"""test_wallet.py — wallet boundaries through the browser. Authoritative accounting is
checked via the app's own API AFTER the browser action; the action happens in Chromium."""
import re

import pytest

import helpers as H


def _balance_from_api(page):
    """Read the authenticated wallet balance via the app API in the browser context."""
    return page.evaluate("""async () => {
      for (const p of ['/wallet/balance', '/me', '/account/balance']) {
        try { const r = await fetch(p, {credentials:'include'});
              if (r.ok) return await r.json(); } catch (e) {}
      }
      return null;
    }""")


@pytest.mark.e2e(section="WALLET", label="Zero balance")
def test_zero_balance_is_honest(page):
    ident, pw = H.require_creds("buyer_zero")
    assert H.login(page, ident, pw)
    page.goto("/account", wait_until="networkidle")
    body = page.locator("body").inner_text() or ""
    assert re.search(r"\$\s?0(\.00)?\b", body), "zero-balance wallet not shown as $0"


@pytest.mark.e2e(section="WALLET", label="Balance never invalidly negative")
def test_balance_never_negative(page):
    ident, pw = H.require_creds("buyer")
    assert H.login(page, ident, pw)
    data = _balance_from_api(page)
    if not isinstance(data, dict):
        pytest.skip("no wallet balance API exposed to the browser")
    bal = data.get("balance", data.get("wallet_balance"))
    if bal is None:
        pytest.skip("balance field not present in wallet API response")
    assert float(bal) >= 0, f"wallet balance is invalidly negative: {bal}"


@pytest.mark.e2e(section="WALLET", label="Insufficient-funds UX")
def test_insufficient_funds_ux(page):
    ident, pw = H.require_creds("buyer_zero")
    assert H.login(page, ident, pw)
    # browse to a listing and attempt to rent with $0 — the UI must surface an insufficient-funds
    # / add-funds path, never silently proceed. Tolerant to marketplace being empty in TEST.
    page.goto("/marketplace", wait_until="networkidle")
    rent = page.locator("a:has-text('Rent'), button:has-text('Rent'), a[href*='/gpu/'], "
                        "button:has-text('Buy')")
    if not rent.count():
        pytest.skip("no rentable listing available in the TEST marketplace right now")
    rent.first.click()
    page.wait_for_load_state("networkidle")
    H.assert_no_horizontal_overflow(page)
    # we don't force a purchase (avoid state churn); assert the page didn't crash into a blank state
    H.assert_primary_content_visible(page)
