# frontend.md — the Petabyte website

## What this is
A complete marketing + app site, served **by the FastAPI app itself** (same-origin,
no separate frontend service, no build step). Pages are plain HTML strings in
`lumaris_api/pages.py`, sharing one brand system with the dashboard.

## Pages (all live)
| Route | Page | Auth |
|-------|------|------|
| `/` | Landing (hero, live stats, seller/buyer CTAs) | public |
| `/marketplace` | Public GPU inventory browser (badges, prices) | public |
| `/install` | Become a seller — **download-first** (Windows app button + no-account wallet quickstart) then the Linux/Windows one-liners | public |
| `/download`, `/download/windows` | Get the desktop app (serves the bundled `.exe`, redirects to `DESKTOP_APP_URL`, or shows the early-access page) | public |
| `/faq`, `/help` | Plain-language FAQ | public |
| `/mysystem`, `/test-gpu` | In-browser WebGPU self-benchmark (indicative) → install funnel | public |
| `/edge` | Edge-Inference SDK demo (on-device WebGPU + metered API fallback) | public |
| `/developers` | Curated API reference (Developer / Data / **Inference** APIs) + link to `/docs` | public |
| `/investors` | Investor relations one-pager — **no numbers** | public |
| `/keys` | Generate / list / revoke API keys | needs sign-in |
| `/console` | The dashboard (browse, deposit, run a job; buyer + seller) | needs sign-in |
| `/app` | Permanent redirect to `/console` (back-compat) | — |
| `/admin/desktop` | Admin: publish a new desktop release from the browser | admin |
| `/docs` | Auto-generated interactive API schema (FastAPI) | public |

## What it uses
- **No framework** — hand-written HTML/CSS/vanilla JS, flexbox layout (renders in
  legacy engines too). Google Fonts (Space Grotesk, Inter, JetBrains Mono) via CDN.
- **Brand: Petabyte.** Deep-navy base `#080D1C` with teal/cyan
  bioluminescent accents (`#4FD6C9` → `#74ECDD`) and an amber energy accent
  (`#F5B23D`). The hexagon node mark is the signature, served from
  `/static/petabyte-logo.png` (teal-gradient) with `/favicon.ico` + apple-touch icon.
- **No auth wall on the site.** All pages, including `/keys`, render without a forced
  sign-in. Google sign-in is a discreet, optional entry point; the JWT (when present)
  is stored in `localStorage` as `pb_token` and used by `/keys` and `/console`. Sign-in
  redirects to `/console#t=<jwt>`; a bootstrap script captures the fragment and cleans the
  URL. Money/compute API endpoints stay authenticated server-side. (`/app` is a permanent
  redirect to `/console` for backward compatibility.)
- **Live data:** landing + marketplace poll `/marketplace/stats` and
  `/marketplace/specs` (both public, read-only).
- **Investor page** mirrors the `Petabyte_Cloud_OnePager.pdf` layout (problem/solution,
  vision band, infrastructure grid, Live/169/&lt;HS/2026 stat tiles).

## New API endpoints added for the site
- `GET /` landing · `GET /app` dashboard (moved from `/`) · `/investors` `/developers`
  `/install` `/keys` `/marketplace` pages.
- `GET /marketplace/specs` — public inventory (no auth, limited fields).
- `GET /install.sh` — serves the node installer so the one-liner needs no extra hosting.
- `GET /static/{name}` (whitelisted brand assets) + `GET /favicon.ico` — the hexagon logo.
- `GET /auth/google/login` + `GET /auth/google/callback` — Google sign-in
  (create-or-login by email, issues the normal JWT).
- `GET /account/keys` (list) + `POST /keys/{jti}/revoke` — key management UI;
  `POST /create_api_key` now takes an optional `label`.

## Going live
1. **Deploy the API** per `deploy.md` (droplet, nginx, certbot, Postgres). The site
   ships with it — no separate frontend deploy.
2. **DNS:** point `petabyte.market` (site) and `petabyte.market` at the droplet, or
   serve both from one domain. HTTPS via certbot (deploy.md §5).
3. **Google sign-in:** in Google Cloud Console → APIs & Services → Credentials → create
   an **OAuth 2.0 Client ID (Web)**. Authorized redirect URI:
   `https://petabyte.market/auth/google/callback`. Put the client id/secret +
   redirect into the env (see `template.env`), set `GOOGLE_OAUTH_STUB=false`, restart.
4. **Installer URLs:** `/install.sh` is served by the API. Host `install.ps1` similarly
   (add a route or drop it in nginx static) so the Windows one-liner resolves.
5. **Verify:** open `/` (stats load), `/marketplace` (inventory), click **Sign in with
   Google** (round-trips to `/app` signed in), `/keys` (generate a key).

## Honest notes
- Google OAuth's real token exchange can't be tested without a Google project; the flow
  logic is verified via `GOOGLE_OAUTH_STUB=true`, and the live path is functional code
  needing your client id (same seam pattern as Stripe/S3 — see `stub.md`).
- The site is server-rendered static HTML; for a heavier marketing site later, the API
  is CORS-ready for a separate Next.js/React app, but that's not needed today.
