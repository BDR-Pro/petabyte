"""web_routes.py — the static public web surface (marketing / legal / trust / status / info).

The first slice of a staged `main.py` -> domain-routers extraction. Every handler here returns
a pre-rendered HTML/text constant with NO database or auth dependency, so the whole surface
lifts out of the monolith with zero coupling and no circular import — `main` mounts it with a
single `app.include_router(...)`.

Staged plan (why this one is first): the remaining domains — trust (`/trust/summary`,
`/jobs/{id}/receipt`), compute lifecycle, payments — use shared dependencies
(`get_db`, `get_current_user`, `_username`) that still live in `main.py`. Extracting those
routers cleanly requires lifting those dependencies into a `deps.py` FIRST (so a router can
import them without importing `main`). This static-page slice needs none of that, so it is the
safe, self-contained first step that establishes the pattern behind the green test suite.
"""
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, FileResponse

from pages import (
    TRUST_HTML, STATUS_HTML, METRICS_HTML, TRACTION_HTML, BUY_HTML, SELLER_EARNINGS_HTML,
    TEMPLATES_HTML, DEMO_HTML, CONTACT_HTML, PRICING_HTML, SECURITY_HTML, PRIVACY_HTML,
    TERMS_HTML, AUP_HTML, REFUNDS_HTML, GPU_DETAIL_HTML, GAMERS_HTML, ARTISTS_HTML,
    CLUSTER_HTML, CONSOLE_HTML, FAQ_HTML, DESKTOP_SOON_HTML,
)

router = APIRouter(tags=["web"])


@router.get("/faq", response_class=HTMLResponse)
@router.get("/help", response_class=HTMLResponse)
def faq_page():
    """Plain-language answers for non-technical sellers and buyers (safety, payouts, trust)."""
    return HTMLResponse(FAQ_HTML)


@router.get("/download/windows")
@router.get("/download")
def download_windows():
    """The 'Get the Windows app' target — never a dead link, never a fabricated download.

    Order of truth: (1) a build bundled on THIS server (private-safe, no GitHub) wins; (2) else a
    configured DESKTOP_APP_URL (a domain-hosted .exe or a signed public release); (3) else an
    honest 'early access — start now with one command' page. So the button works the moment a real
    build exists and tells the truth until then."""
    local = "/opt/lumaris/installers/PetabyteAgent.exe"
    if os.path.exists(local):
        return FileResponse(local, filename="PetabyteAgent.exe",
                            media_type="application/vnd.microsoft.portable-executable")
    url = os.getenv("DESKTOP_APP_URL", "").strip()
    if url:
        return RedirectResponse(url, status_code=302)
    return HTMLResponse(DESKTOP_SOON_HTML)


@router.get("/trust", response_class=HTMLResponse)
def trust_page():
    return HTMLResponse(TRUST_HTML)


@router.get("/.well-known/security.txt", response_class=PlainTextResponse)
@router.get("/security.txt", response_class=PlainTextResponse)
def security_txt():
    """RFC 9116 security contact — the file security researchers look for first."""
    # Contact is a domain email, not a GitHub advisories URL: the source repo is (or may become)
    # private, and a github.com/<repo>/security/advisories link 404s for external researchers
    # without repo access — the opposite of what security.txt is for. mailto works regardless.
    return (
        "# Petabyte vulnerability disclosure — see /security\n"
        "Contact: mailto:security@petabyte.market\n"
        "Policy: https://petabyte.market/security\n"
        "Expires: 2027-08-01T00:00:00Z\n"
        "Preferred-Languages: en\n"
    )


@router.get("/status", response_class=HTMLResponse)
def status_page():
    """Plain service status — honest, generated from live heartbeats."""
    return HTMLResponse(STATUS_HTML)


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page():
    """Investor / operations metrics dashboard (data from /metrics/overview)."""
    return HTMLResponse(METRICS_HTML)


@router.get("/traction", response_class=HTMLResponse)
def traction_page():
    """Public investor traction — live, canonical, honest (data from /metrics/traction)."""
    return HTMLResponse(TRACTION_HTML)


@router.get("/buy/{public_id}", response_class=HTMLResponse)
def buy_page(public_id: str):
    """Browser checkout + run experience for one GPU: the buyer completes the entire
    Stripe compute-tx lifecycle (authorize -> card -> reserve -> dispatch -> run ->
    capture -> receipt) without touching an internal endpoint by hand. The spec id is
    read client-side from the path."""
    return HTMLResponse(BUY_HTML)


@router.get("/cluster", response_class=HTMLResponse)
@router.get("/distributed", response_class=HTMLResponse)
def cluster_page():
    """Buyer-facing distributed-compute launcher: form a cluster of N GPUs across different
    machines (one job, wired over the VPN), or export it to your own scheduler (Slurm/MPI/Ray).
    NOTE: the POST /distributed API endpoint is unaffected — this GET only serves the page."""
    return HTMLResponse(CLUSTER_HTML)


@router.get("/console", response_class=HTMLResponse)
def console_page():
    """Unified operator console for the signed-in user: everything they launched as a BUYER
    (VMs with stable addresses, distributed clusters, spend/runway) and a summary of everything
    they host as a SELLER (nodes, earnings, with a link to the full earnings page). Data comes
    from /me, /buyer/spend, /vms, /clusters, /seller/dashboard."""
    return HTMLResponse(CONSOLE_HTML)


@router.get("/seller/payouts", response_class=HTMLResponse)
def seller_payouts_page():
    """Seller Stripe onboarding + earnings/transfers/payouts (data from /payments/*).
    Distinct from the JSON API at /seller/earnings and /seller/earnings/stripe."""
    return HTMLResponse(SELLER_EARNINGS_HTML)


@router.get("/templates-catalog", response_class=HTMLResponse)
@router.get("/catalog", response_class=HTMLResponse)
def templates_page():
    return TEMPLATES_HTML


@router.get("/demo", response_class=HTMLResponse)
@router.get("/book-a-demo", response_class=HTMLResponse)
def demo_page():
    return DEMO_HTML


@router.get("/contact", response_class=HTMLResponse)
def contact_page():
    return CONTACT_HTML


@router.get("/pricing", response_class=HTMLResponse)
def pricing_page():
    return PRICING_HTML


@router.get("/security", response_class=HTMLResponse)
def security_page():
    return SECURITY_HTML


@router.get("/privacy", response_class=HTMLResponse)
def privacy_page():
    return PRIVACY_HTML


@router.get("/terms", response_class=HTMLResponse)
def terms_page():
    return TERMS_HTML


@router.get("/acceptable-use", response_class=HTMLResponse)
def aup_page():
    return AUP_HTML


@router.get("/refunds", response_class=HTMLResponse)
@router.get("/refund-policy", response_class=HTMLResponse)
def refunds_page():
    return REFUNDS_HTML


@router.get("/gpu/{public_id}", response_class=HTMLResponse)
def gpu_detail_page(public_id: str):
    return GPU_DETAIL_HTML


@router.get("/gamers", response_class=HTMLResponse)
def gamers_page():
    return GAMERS_HTML


@router.get("/artists", response_class=HTMLResponse)
def artists_page():
    return ARTISTS_HTML
