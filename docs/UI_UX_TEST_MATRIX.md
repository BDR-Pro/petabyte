# UI/UX Test Matrix

Every user-facing surface in Petabyte — **web UI, CLI, and the packaged Windows `.exe`** —
is now backed by automated assertions, not visual judgment. This matrix records what is
actually verified and by which suite. A ✓ means an automated test asserts it; **N/A** means
the dimension does not apply to that surface; **manual** means it needs a human/CI step
noted below.

Legend of suites:

| Suite | What it proves | Browser? |
|---|---|---|
| `web_ui_test.py` | server-rendered contract: render, headings, nav, forms, a11y, prices/hardware, failure + empty + weird data | no (TestClient) |
| `audit_frontend.py` / `audit_js.py` | no dead calls/links/ids; every inline `<script>` parses | no |
| `scripts/e2e/browser_ui_test.py` | responsive (desktop/tablet/mobile), console-errors, visible+enabled controls, buyer/seller journeys | yes (Playwright/Chromium, opt-in) |
| `cli/cli_ui_test.py` | colour/no-colour, unicode/ASCII, tables, panels, JSON validity, no-drift across copies | no |
| `cli/cli_petabyte_test.py` | buyer CLI as a subprocess vs a real API: table, JSON, errors, exit codes | no |
| `lumaris_agent/agent_cli_test.py` | seller node `doctor`/`--help`/`--version`/`provision` UX + JSON purity | no |
| `desktop-app/exe_smoke_test.py` | `.exe` entrypoint UX + PyInstaller hidden-import packaging | no |

## Web

| Surface | Desktop | Tablet | Mobile | Interaction | Error state | Empty state | A11y | Automated |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Homepage (`/`) | ✓ | ✓ | ✓ | ✓ | N/A | N/A | ✓ | ✓ |
| Marketplace (`/marketplace`) | ✓ | ✓ | ✓ | ✓ (cards, prices, hardware) | ✓ | ✓ | ✓ | ✓ |
| Login (`/login`) | ✓ | ✓ | ✓ | ✓ | ✓ (bad creds) | N/A | ✓ (labels for=) | ✓ |
| Buyer dashboard (`/app`) | ✓ | N/A | N/A | ✓ | ✓ | ✓ (0 jobs) | ✓ | ✓ |
| Seller dashboard (`/seller/payouts`) | ✓ | N/A | ✓ | ✓ (nodes, earnings) | N/A | N/A | ✓ | ✓ |
| Buy / checkout (`/buy/<id>`) | ✓ | N/A | ✓ | ✓ (visible+enabled) | ✓ (unknown spec) | N/A | ✓ | ✓ |
| Account (`/account`) | ✓ | N/A | N/A | ✓ | N/A | N/A | ✓ (alt, aria) | ✓ |
| Pricing (`/pricing`) | ✓ | ✓ | ✓ | N/A | N/A | N/A | ✓ | ✓ |
| Install / seller (`/install`) | ✓ | ✓ | ✓ | ✓ | N/A | N/A | ✓ | ✓ |
| Failure states (404/401/malformed) | ✓ | N/A | N/A | N/A | ✓ (no stack traces) | N/A | N/A | ✓ |

Notes:
- **Desktop/tablet/mobile** ✓ come from `browser_ui_test.py`, which asserts
  `documentElement.scrollWidth <= clientWidth` (no horizontal overflow) plus a usable nav
  (brand on desktop, hamburger toggler on mobile) at 1280 / 768 / 390 px.
- **Interaction** for the buy page asserts the *Rent & run* button is both **visible and
  enabled** (not merely present in the DOM) at desktop and mobile widths.
- **A11y** ✓ asserts: every `<img>` has `alt`; every text input is labelled (explicit
  `for=`, wrapping `<label>`, or `aria-label`); no duplicate ids; every `<button>` has an
  accessible name; `<html lang>` present.

## Phone (mobile) ergonomics

Beyond "no horizontal overflow", the phone experience is asserted for the things that
actually make a small screen usable — measured on a real 390px mobile viewport:

| Check | Browser | Notes |
|---|:--:|---|
| Form inputs are **>=16px** so iOS doesn't zoom on focus | ✓ | marketplace, login, install |
| Primary buttons/controls meet the **~44px tap-target** minimum | ✓ | measured computed height |
| Multi-column tables become **stacked, labelled cards** (not a side-scrolling table) | ✓ | `.tbl td` display + every cell carries `data-l` |
| Long install/command blocks **wrap** instead of side-scrolling | ✓ | audited: zero in-page horizontal scrollers on `/install` |
| No horizontal overflow, nav collapses to a usable hamburger | ✓ | desktop/tablet/mobile sweep incl. `/account` |

Fast-tier guards (TestClient): marketplace rows label every cell (`data-l`) and the page
ships the `<=720px` breakpoint that upsizes inputs — so a refactor can't silently drop
the phone card view or reintroduce the iOS zoom-on-focus bug.

## Role-based value propositions + self-service role switch

| Behaviour | TestClient | Browser | Notes |
|---|:--:|:--:|---|
| Buyer marketplace **leads with savings vs AWS/GCP/Azure** | ✓ | ✓ | banner element + `updateSavingsBanner` logic (TestClient); renders a real % from a below-reference GPU (browser). Keeps the honest "benchmark, not a quote" framing. |
| Seller `/install` **leads with earnings** (keep 90%) + monthly estimate | ✓ | — | earnings banner + `/pricing/suggest`-driven monthly range, after the 10% fee |
| Seller `/seller/payouts` **leads with earnings** | ✓ | — | earnings banner |
| Onboarding framed as easy (one command, ~30s) | ✓ | — | assertion guards the copy from regressing |
| **Self-service role switch** buyer↔seller | ✓ (functional round-trip via `/change_role` + `/me`) | ✓ (click on `/account` → lands on `/install` as seller) | button carries a static `aria-label`; invalid role → 400, not 500 |

## CLI (buyer CLI, seller agent, tools)

| Surface | Human output | Colour off (NO_COLOR / pipe) | Machine (JSON) | Error UX | Exit codes | Automated |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `petabyte --help` | ✓ | ✓ | N/A | N/A | ✓ (0) | ✓ |
| `petabyte specs` (table) | ✓ | ✓ | N/A | ✓ (empty state) | ✓ | ✓ |
| `petabyte wallet` | ✓ | ✓ | N/A | ✓ | ✓ | ✓ |
| `petabyte run` | ✓ (progress) | ✓ | N/A | ✓ (no-match / timeout / missing file) | ✓ | ✓ |
| agent `doctor` | ✓ | ✓ | ✓ (pure stdout) | ✓ | ✓ (0/1) | ✓ |
| agent `--help` / `--version` | ✓ | ✓ | N/A | N/A | ✓ (0) | ✓ |
| `provision.py` | ✓ (steps + panel) | ✓ | N/A | ✓ (missing key/url) | ✓ | ✓ |

Notes:
- Colour is semantic (green=ok/online, yellow=pending, red=fail, cyan=info, dim=meta) and
  turns **off** automatically when stdout is not a TTY or `NO_COLOR` is set.
- **Machine-readable contract (seller agent CLI):** `--json` (and `PETABYTE_JSON`) emit
  pure, valid JSON on stdout with *no* ANSI and *no* stray log lines — asserted directly.
  The buyer `petabyte` client does **not** have a `--json` mode or a `doctor` command;
  those are agent-CLI features.
- Icons fall back to ASCII when the terminal can't encode Unicode (e.g. Windows cp1252),
  and output is verified cp1252-encodable so a legacy console never crashes.

## Windows `.exe` (packaged Desktop Agent)

| Check | Verified | Suite / command |
|---|:--:|---|
| Entrypoint identified (`petabyte_desktop.py` → PyInstaller onefile) | ✓ | `exe_smoke_test.py` |
| `--version` / `--help` / `doctor` run without launching the GUI | ✓ | `exe_smoke_test.py` |
| `doctor --json` is pure valid JSON | ✓ | `exe_smoke_test.py` |
| No import/asset error on the packaged path | ✓ | `exe_smoke_test.py` |
| `build_exe.py` bundles every local module (incl. `cli_ui`, `agent_cli`, `ui`) | ✓ | `exe_smoke_test.py` (static) |
| Real PyInstaller build produces a runnable binary that prints the new UX | ✓ (Linux config build) | `PB_BUILD_EXE=1 python exe_smoke_test.py` |
| Windows `.exe` artifact | manual | GitHub Actions on Windows (see `desktop-app/BUILD.md`) |

The shared presentation module `cli_ui.py` is pure-stdlib (no third-party import), so it
adds **no** new hidden-import surface to the bundle. It is shipped byte-identically in
`lumaris_api/cli/`, `lumaris_agent/`, and `desktop-app/`; a test fails if the copies drift.

## Running everything

```bash
# Web + CLI + exe surface assertions (no browser needed)
make ui-test

# Real-browser responsive + console-error + journeys (needs Chromium once):
python -m playwright install chromium
make browser-ui

# Or the whole platform suite (includes the UI suites above):
cd lumaris_api && bash run_tests.sh
```

What still needs a human/CI step: building and smoke-testing the actual **Windows** `.exe`
(this repo verifies the build *config* and entrypoint on Linux; the signed Windows artifact
is produced by the Windows GitHub Actions job in `desktop-app/BUILD.md`).
