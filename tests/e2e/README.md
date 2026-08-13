# Browser E2E (Playwright + pytest)

Drives the **live TEST site** through Chromium as real users and writes a human-readable
report you can paste back to Claude/ChatGPT. Runs automatically in CI
(`.github/workflows/browser-e2e.yml`) — no other machine required.

## Run
```bash
make test-browser-e2e                 # installs deps + Chromium, runs the suite
# or:
E2E_BASE_URL=https://test.petabyte.market python -m pytest -q tests/e2e
```
Output: `artifacts/e2e_browser_report.txt` (also printed to stdout). Failures also drop a
screenshot + Playwright trace into `artifacts/` (git-ignored).

## Safety
The suite reads `<base>/payments/config` and **aborts** if the site looks LIVE
(`mode=live`/`gateway=live`/`payments_live_enabled`). It never uses real money or payouts.

## Credentials (all optional — GitHub Secrets)
Login-gated personas skip cleanly when their secret is absent, so the anonymous + UX +
protected-route checks always run with zero setup. Add these as repo Secrets to enable the
rest (username **or** email accepted as the identifier):

| Persona | Secrets |
|---|---|
| Funded buyer | `E2E_BUYER_USERNAME` / `E2E_BUYER_PASSWORD` |
| Zero-balance buyer | `E2E_BUYER_ZERO_USERNAME` / `E2E_BUYER_ZERO_PASSWORD` |
| Second buyer (isolation) | `E2E_BUYER_B_USERNAME` / `E2E_BUYER_B_PASSWORD` |
| Seller | `E2E_SELLER_USERNAME` / `E2E_SELLER_PASSWORD` |
| Second seller (isolation) | `E2E_SELLER_B_USERNAME` / `E2E_SELLER_B_PASSWORD` |
| Admin | `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD` |

Use clearly-marked `e2e-` TEST accounts. Never point these at real users.

## Files (kept intentionally small)
- `conftest.py` — safety abort, Chromium fixtures, console/network capture, screenshot+trace
  on failure, report hook. Set `E2E_CHROMIUM_PATH` to use a pre-installed browser.
- `helpers.py` — login + deterministic UX assertions (no CV/AI scoring).
- `report.py` — the `artifacts/e2e_browser_report.txt` writer.
- `test_smoke_ux.py` — anonymous pages, desktop+mobile, protected-route denial (no creds).
- `test_buyer.py` / `test_seller.py` / `test_authorization.py` / `test_wallet.py` — personas.
