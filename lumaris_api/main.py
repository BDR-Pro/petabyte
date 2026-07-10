from fastapi import (
    FastAPI, Depends, HTTPException, Query, Header, Security, Request, WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse, JSONResponse, Response, HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime, timezone
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import os

from utils import (
    gen_wg_keypair, build_client_wg_config, apply_peer_to_interface,
    gen_secure_api_key, decode_api_key, verify_attestation, verify_signed_proof,
)
from db import (
    get_db, SessionLocal, PLATFORM_TAKE_RATE, HEARTBEAT_TIMEOUT_S,
    create_user, login_user, get_user_by_username, set_role,
    save_specs, get_spec_by_id, spec_is_live, touch_spec, reap_stale_specs,
    try_reserve_unit, release_unit, create_booking, get_booking_by_id,
    revoke_jti, is_jti_revoked, add_wg_peer,
    record_issued_key, list_issued_keys, get_or_create_oauth_user,
    idem_begin, idem_finish, idem_abort,
    create_task, claim_next_task, get_task_for_agent, mark_task_running,
    submit_task_result, get_booking_for_buyer,
    MIN_REPUTATION, create_test_task, get_testworkload_by_task,
    record_test_result, penalize_user, get_user_by_id, get_spec_by_id as _get_spec,
    deposit, try_debit, book_with_escrow, mark_booking_active,
    release_booking, refund_booking, settle_dead_specs, get_or_create_platform,
    webhook_already_processed, credit_user_by_username,
    create_challenge, consume_challenge, set_spec_confidential,
    create_org, get_org, get_membership, org_members, add_org_member,
    org_deposit, try_org_debit, org_refund, org_usage,
    retry_task, set_task_progress, add_task_log, get_task_logs,
    set_benchmark, create_benchmark_task, org_analytics,
    record_checkpoint, list_checkpoints, reschedule_task,
    get_or_create_task_enc_key,
    note_heartbeat, note_job_completed, note_job_failed, note_fraud,
    compute_reputation, recent_rep_events,
    set_idle_fallback, record_idle_report, idle_credited_total,
    add_payout_method, list_payout_methods, get_payout_method,
    request_payout, set_payout_status, list_payouts,
    create_schedule, list_schedules, run_due_schedules,
    list_notifications,
    create_multinode_job, add_job_segment, segment_for_task, complete_segment,
    all_segments_done, segment_output_refs, set_job_status, get_multinode_job,
    job_segments,
)
from auth import create_access_token, verify_token
from static_dashboard import DASHBOARD_HTML
from pages import (LANDING_HTML, INVESTORS_HTML, DEVELOPERS_HTML, INSTALL_HTML,
                   KEYS_HTML, MARKETPLACE_HTML, ADMIN_HTML, LOGIN_HTML, ACCOUNT_HTML,
                   GAMERS_HTML)
from templates_registry import TEMPLATES, public_catalog
from router import select_plan
from payout_providers import screen, get_provider
import notifications
RENDER_IMAGE = TEMPLATES['blender']['image']
FFMPEG_IMAGE = TEMPLATES['ffmpeg']['image']
from utils import (
    verify_webhook_signature, verify_tee_report, geolocate_country,
    mint_presigned_put, mint_presigned_get, s3_key_for, s3_uri,
)

REAPER_INTERVAL_S = int(os.getenv("REAPER_INTERVAL_S", "20"))
REAPER_DISABLED = os.getenv("REAPER_DISABLED", "false").lower() == "true"
PAYMENTS_MODE = os.getenv("PAYMENTS_MODE", "sandbox").lower()      # sandbox|live
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")
AWS_REFERENCE_PRICE = os.getenv("AWS_REFERENCE_PRICE", "12.29")


async def _reaper_loop():
    while True:
        await asyncio.sleep(REAPER_INTERVAL_S)
        try:
            db = SessionLocal()
            reap_stale_specs(db, HEARTBEAT_TIMEOUT_S)
            settle_dead_specs(db)   # refund in-flight bookings on dead nodes
            db.close()
        except Exception:
            pass  # never let the reaper crash the loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None if REAPER_DISABLED else asyncio.create_task(_reaper_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Lumaris API", lifespan=lifespan)

# Optional error tracking — only active when SENTRY_DSN is set (see HARDENING.md).
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=_SENTRY_DSN, traces_sample_rate=0.1,
                        environment=os.getenv("PAYMENTS_MODE", "sandbox"))
    except Exception as _e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger(__name__).warning(f"Sentry init skipped: {_e}")

# CORS: explicit allow-list only (never "*" with credentials). Set ALLOWED_ORIGINS
# to a comma-separated list, e.g. "https://petabyte.market,https://app.petabyte.market".
_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-KEY", "Idempotency-Key"],
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


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


class RequestVMModel(BaseModel):
    spec_id: int
    hours: int = Field(gt=0)
    vpn: bool = False
    require_confidential: bool = False
    require_region: Optional[str] = None
    require_country: Optional[str] = None
    org_id: Optional[int] = None


class UserRegisterModel(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)


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


class EmailModel(BaseModel):
    email: str
    notify_email: bool = True


class PayoutMethodModel(BaseModel):
    kind: str                         # gift_card|usdc|bank
    destination: str                  # email | wallet address | account ref
    label: Optional[str] = None


class WithdrawModel(BaseModel):
    method_id: int
    amount: float = Field(gt=0)


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


class UploadUrlModel(BaseModel):
    filename: str


class TranscodeModel(BaseModel):
    input_ref: str                       # object-storage ref to the source video
    codec: str = "h264"                  # h264|h265|av1
    resolution: Optional[str] = None     # e.g. 1920x1080
    bitrate: Optional[str] = None        # e.g. 5M  (or use crf)
    crf: Optional[int] = None
    container: str = "mp4"
    use_gpu: bool = True                 # NVENC
    duration_seconds: int = 0            # total length (for segment splitting)
    nodes: int = 1
    hours: int = 1
    gpu_class: Optional[str] = None
    region: Optional[str] = None


class RenderModel(BaseModel):
    blend_ref: str                       # object-storage ref to the .blend file
    frame_start: int
    frame_end: int
    samples: int = 128
    hours: int = 1
    nodes: int = 1
    gpu_class: Optional[str] = None
    region: Optional[str] = None


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


class OrgMemberModel(BaseModel):
    username: str
    role: str = "member"


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

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        return verify_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def _username(user: dict) -> str:
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Malformed token")
    return sub


def _client_ip(request: Request):
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


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
    if auth.startswith("Bearer "):
        try:
            owner = get_user_by_username(db, _username(verify_token(auth[7:])))
        except Exception:
            owner = None
    if owner is None:
        key = request.headers.get("X-API-KEY")
        if key:
            try:
                data = decode_api_key(key)
                if not is_jti_revoked(db, data["jti"]):
                    owner = get_user_by_username(db, data["u"])
            except Exception:
                owner = None
    if owner is None:
        raise HTTPException(status_code=401, detail="Sign in or provide a valid X-API-KEY")
    if owner.role != "seller":
        raise HTTPException(status_code=403, detail="Only sellers allowed")
    return owner


def api_key_user(x_api_key: str = Header(..., alias="X-API-KEY"),
                 db: Session = Depends(get_db)):
    """Authenticate an unattended agent via X-API-KEY (honors revocation)."""
    try:
        data = decode_api_key(x_api_key)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if is_jti_revoked(db, data["jti"]):
        raise HTTPException(status_code=401, detail="Key revoked")
    user = get_user_by_username(db, data["u"])
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    user._scopes = data.get("scopes", [])     # [] == full access (back-compat)
    return user


def require_scope(user, scope: str):
    scopes = getattr(user, "_scopes", [])
    if scopes and scope not in scopes:
        raise HTTPException(status_code=403, detail=f"API key lacks '{scope}' scope")


# ------------------- HEALTH -------------------

@app.get("/", response_class=HTMLResponse)
def landing():
    return LANDING_HTML

@app.get("/app", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML.replace("__AWS_REF__", AWS_REFERENCE_PRICE)

@app.get("/investors", response_class=HTMLResponse)
def investors_page():
    return INVESTORS_HTML

@app.get("/developers", response_class=HTMLResponse)
def developers_page():
    return DEVELOPERS_HTML

@app.get("/install", response_class=HTMLResponse)
def install_page():
    return INSTALL_HTML

@app.get("/keys", response_class=HTMLResponse)
def keys_page():
    return KEYS_HTML

@app.get("/marketplace", response_class=HTMLResponse)
def marketplace_page():
    return MARKETPLACE_HTML

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return ADMIN_HTML

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return LOGIN_HTML

@app.get("/account", response_class=HTMLResponse)
def account_page():
    return ACCOUNT_HTML

@app.get("/gamers", response_class=HTMLResponse)
def gamers_page():
    return GAMERS_HTML

def _find_installer(name: str):
    """Locate a bundled installer script across dev + deployed layouts."""
    here = os.path.dirname(__file__)
    for cand in (
        os.path.join(here, "installers", name),        # copied here by deploy.sh/update.sh
        os.path.join(here, "..", "lumaris_agent", name),  # dev / monorepo checkout
    ):
        if os.path.exists(cand):
            return cand
    return None

@app.get("/install.sh")
def install_script():
    """Serve the Linux node installer so the one-liner needs no extra hosting."""
    path = _find_installer("install.sh")
    if not path:
        raise HTTPException(status_code=404, detail="installer not bundled")
    with open(path) as f:
        return Response(content=f.read(), media_type="text/x-shellscript")

@app.get("/install.ps1")
def install_script_ps1():
    """Serve the Windows (WSL2) installer for the PowerShell one-liner."""
    path = _find_installer("install.ps1")
    if not path:
        raise HTTPException(status_code=404, detail="installer not bundled")
    with open(path) as f:
        return Response(content=f.read(), media_type="text/plain")


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_ALLOW = {
    "petabyte-logo.png": "image/png",
    "petabyte-mark-180.png": "image/png",
    "favicon.png": "image/png",
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

@app.get("/marketplace/specs")
def public_specs(db: Session = Depends(get_db),
                 gpu: Optional[str] = None, region: Optional[str] = None,
                 min_vram: int = 0, max_price: Optional[float] = None,
                 confidential: Optional[bool] = None, sort: str = "price"):
    """Public, read-only inventory with search/filter (no auth, limited fields)."""
    from db import SellerSpec
    out = []
    for spec in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(spec) or spec.available_units < 1:
            continue
        owner = get_user_by_id(db, spec.user_id)
        if not owner or not owner.can_accept_paid_jobs:
            continue
        if gpu and gpu.lower() not in (spec.gpu_model or "").lower():
            continue
        if region and region.lower() != (spec.region or "").lower():
            continue
        if (spec.vram_gb or 0) < min_vram:
            continue
        if max_price is not None and spec.price_per_hour > max_price:
            continue
        if confidential is not None and bool(spec.confidential) != confidential:
            continue
        total = (spec.jobs_completed or 0) + (spec.jobs_failed or 0)
        _rep = compute_reputation(db, spec)
        _score = _rep["score"] if isinstance(_rep, dict) else _rep
        out.append({"gpu_model": spec.gpu_model or "CPU",
                    "gpu_count": spec.gpu_count or 0, "vram_gb": spec.vram_gb or 0,
                    "price_per_hour": spec.price_per_hour,
                    "region": spec.region, "region_verified": bool(spec.region_verified),
                    "confidential": bool(spec.confidential),
                    "reputation_score": _score,
                    "available_units": spec.available_units,
                    "jobs_completed": spec.jobs_completed, "jobs_failed": spec.jobs_failed,
                    "success_rate": round(100.0 * spec.jobs_completed / total, 1) if total else None})
    keyfn = {"price": lambda x: x["price_per_hour"],
             "rep": lambda x: -x["reputation_score"],
             "vram": lambda x: -x["vram_gb"]}.get(sort, lambda x: x["price_per_hour"])
    out.sort(key=keyfn)
    return {"specs": out, "count": len(out), "aws_reference": float(AWS_REFERENCE_PRICE)}


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


# ------------------- AUTH -------------------

@app.post("/register_user")
def register_user(data: UserRegisterModel, db: Session = Depends(get_db)):
    user = create_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=400, detail="User already exists")
    return {"status": "ok", "msg": "User registered"}



# ------------------- GOOGLE SIGN-IN -------------------

@app.get("/auth/google/login")
def google_login(db: Session = Depends(get_db)):
    """Redirect to Google's consent screen. Stub short-circuits to the callback."""
    if os.getenv("GOOGLE_OAUTH_STUB", "").lower() == "true":
        return RedirectResponse(url="/auth/google/callback?code=stub&email=demo@petabyte.market")
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
def google_callback(code: str = Query(...), email: Optional[str] = Query(None),
                    db: Session = Depends(get_db)):
    """Exchange the code for the user's email, create-or-login, issue our JWT."""
    if os.getenv("GOOGLE_OAUTH_STUB", "").lower() == "true":
        user_email = email or "demo@petabyte.market"
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
    u = get_or_create_oauth_user(db, user_email, "google")
    token = create_access_token({"sub": u.username, "role": u.role})
    return RedirectResponse(url="/app#t=" + token)

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = login_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/change_role")
def change_role(data: RoleModel, user: dict = Depends(get_current_user),
                db: Session = Depends(get_db)):
    try:
        new_role = set_role(db, _username(user), data.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "msg": f"Role changed to {new_role}"}


# ------------------- SELLER -------------------

@app.post("/register_specs")
def register_specs(spec: SpecModel, owner=Depends(seller_actor),
                   db: Session = Depends(get_db)):
    db_spec = save_specs(db, owner, spec.model_dump())
    return {"status": "ok", "spec_id": db_spec.id,
            "attested": db_spec.attested, "available_units": db_spec.available_units}


@app.post("/prove")
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


@app.post("/heartbeat")
def heartbeat(data: HeartbeatModel, request: Request, owner=Depends(api_key_user),
              db: Session = Depends(get_db)):
    """Seller node agent pings here (~every 15s). We also GeoIP-verify the node's
    region from its source IP: declared country must match the detected country
    for the spec to count as residency-verified."""
    require_scope(owner, "node")
    spec = get_spec_by_id(db, data.spec_id)
    if not spec or spec.user_id != owner.id:
        raise HTTPException(status_code=404, detail="Spec not found")
    detected = geolocate_country(_client_ip(request))
    spec.detected_country = detected
    spec.region_verified = bool(detected and spec.country and detected == spec.country)
    touch_spec(db, spec)   # persists detected/verified + online/last_seen
    note_heartbeat(db, spec)
    return {"status": "ok", "spec_id": spec.id, "state": "online",
            "detected_country": detected, "region_verified": spec.region_verified,
            "idle_fallback": bool(spec.idle_fallback)}


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
        _fail(404, "Spec not found")
    if not spec.attested:
        _fail(409, "Spec not attested yet")
    if not spec_is_live(spec):
        _fail(503, "Spec offline (no recent heartbeat)")
    if spec.user_id == buyer.id:
        _fail(400, "Cannot rent your own spec")
    if req.require_confidential and not spec.confidential:
        _fail(403, "Spec is not confidential-computing attested")
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
        _fail(409, "No capacity available")

    # Atomic debit (org budget-capped, or personal); return the unit if it fails.
    debited = try_org_debit(db, pay_org_id, gross) if pay_org_id else try_debit(db, buyer.id, gross)
    if not debited:
        release_unit(db, req.spec_id)
        _fail(402, "Insufficient funds or budget cap exceeded")

    try:
        booking = book_with_escrow(db, buyer, spec, req.hours, req.vpn, PLATFORM_TAKE_RATE, org_id=pay_org_id)
    except Exception:
        release_unit(db, req.spec_id)
        if pay_org_id:
            org_refund(db, pay_org_id, gross)
        else:
            deposit(db, buyer, gross)
        if idempotency_key:
            idem_abort(db, idempotency_key, username, endpoint)
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
    _backup = {"backup_enabled": bool(task.backup_enabled),
               "backup_interval_s": task.backup_interval_s,
               "volume": task.volume,
               "restore_from": task.latest_checkpoint_ref}   # restore if a backup exists
    mark_task_running(db, task)
    if task.task_type == "notebook":
        return {"task_id": task.id, "task_type": "notebook", "code": task.code}
    if task.task_type == "test":
        params = json.loads(task.code or "{}")
        return {"task_id": task.id, "task_type": "test",
                "size": params.get("size"), "seed": params.get("seed"), **_backup}
    if task.task_type == "benchmark":
        return {"task_id": task.id, "task_type": "benchmark", **_backup}
    if task.task_type == "render":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "render", "image": RENDER_IMAGE,
                "gpu": True, **rp, **_backup}
    if task.task_type == "transcode":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "transcode", "image": FFMPEG_IMAGE,
                "gpu": bool(rp.get("use_gpu", True)), **rp, **_backup}
    if task.task_type == "stitch":
        rp = json.loads(task.template_params or "{}")
        return {"task_id": task.id, "task_type": "stitch", "image": FFMPEG_IMAGE,
                **rp, **_backup}
    if task.task_type == "template":
        tpl = TEMPLATES.get(task.template, {})
        return {"task_id": task.id, "task_type": "template", "template": task.template,
                "image": tpl.get("image"), "port": tpl.get("port"),
                "cache": tpl.get("cache"), "gpu": tpl.get("gpu", True),
                "params": json.loads(task.template_params or "{}"), **_backup}
    return {"task_id": task.id, "task_type": "vm", "vm_type": task.vm_type,
            "cpu": task.cpu, "ram": task.ram, "cuda": task.cuda}


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
        penalize_user(db, agent, 40)            # forged/expired proof is severe
        note_fraud(db, spec, "invalid result signature")
        if task.task_type == "test":
            tw = get_testworkload_by_task(db, task.id)
            if tw:
                record_test_result(db, tw, "<invalid-signature>")
        submit_task_result(db, task, None, "failed")
        raise HTTPException(status_code=401, detail=f"Invalid proof: {e}")

    # 2) Known-answer test workloads: compare to the expected hash, update reputation.
    if task.task_type == "test":
        tw = get_testworkload_by_task(db, task.id)
        if not tw:
            raise HTTPException(status_code=404, detail="Test record missing")
        passed = record_test_result(db, tw, data.proof["output_hash"])
        submit_task_result(db, task, None, "completed" if passed else "failed")
        return {"status": "ok", "task_id": task.id, "test_passed": passed,
                "reputation": agent.reputation,
                "can_accept_paid_jobs": agent.can_accept_paid_jobs}

    # 3) Normal job: signature binds output to the node; store hash + result.
    submit_task_result(db, task, data.result or data.proof.get("output_hash"), data.status)
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
        released = release_booking(db, task.booking_id)   # pay seller + platform
    if data.status == "completed":
        _advance_manifest(db, task, data.result or data.proof.get("output_hash"))
    return {"status": "ok", "task_id": task.id, "task_status": task.status,
            "output_hash": data.proof.get("output_hash"), "booking_released": released}


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
            "available_units": spec.available_units,
            "reputation": owner.reputation,
            "confidential": bool(spec.confidential),
            "tee_vendor": spec.tee_vendor,
            "region": spec.region, "country": spec.country,
            "detected_country": spec.detected_country,
            "region_verified": bool(spec.region_verified),
            "benchmark_tokens_sec": spec.benchmark_tokens_sec,
            "reputation_score": compute_reputation(db, spec)["score"],
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


@app.get("/marketplace/stats")
def marketplace_stats(db: Session = Depends(get_db)):
    """Public hero numbers for the dashboard."""
    from db import SellerSpec, Task, Booking, Platform
    nodes_online = db.query(SellerSpec).filter(SellerSpec.status == "online").count()
    specs_listed = db.query(SellerSpec).filter(SellerSpec.attested == True).count()  # noqa: E712
    jobs_completed = db.query(Task).filter(Task.status == "completed").count()
    gmv = db.query(func.coalesce(func.sum(Booking.gross_amount), 0.0)).filter(Booking.test == False).scalar() or 0.0  # noqa: E712 exclude sandbox
    plat = db.query(Platform).first()
    return {"nodes_online": nodes_online, "specs_listed": specs_listed,
            "jobs_completed": jobs_completed, "gmv": round(float(gmv), 2),
            "platform_revenue": round(plat.revenue, 2) if plat else 0.0}


# ------------------- ADMIN (platform operators) -------------------
# Admins are named in the ADMIN_USERS env var (comma-separated usernames or
# emails). No DB column, no migration; set it at deploy time. Every /admin/*
# route is gated by require_admin, so the page is safe to serve to anyone —
# it shows nothing until an admin token loads the data.

def _admin_allowlist() -> set:
    return {u.strip().lower() for u in os.getenv("ADMIN_USERS", "").split(",") if u.strip()}

def _is_admin(u) -> bool:
    if not u:
        return False
    idents = {(u.username or "").lower()}
    if getattr(u, "email", None):
        idents.add(u.email.lower())
    return bool(_admin_allowlist() & idents)

def require_admin(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    if not _is_admin(me):
        raise HTTPException(status_code=403, detail="Admin access required")
    return me


@app.get("/admin/whoami")
def admin_whoami(me=Depends(require_admin)):
    """200 only for admins — lets the UI reveal the Admin link."""
    return {"admin": True, "username": me.username}


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
    return {"status": "ok"}


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


# ------------------- ACCOUNT / NOTIFICATIONS -------------------

@app.post("/account/email")
def set_email(data: EmailModel, user: dict = Depends(get_current_user),
              db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    me.email = data.email; me.notify_email = data.notify_email
    db.add(me); db.commit()
    return {"status": "ok", "email": me.email, "notify_email": me.notify_email}


@app.get("/notifications")
def get_notifications(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"notifications": [{"event_type": n.event_type, "subject": n.subject,
                               "status": n.status, "created_at": str(n.created_at)}
                              for n in list_notifications(db, me.id)]}


# ------------------- PAYOUTS (withdraw earnings) -------------------

@app.post("/wallet/methods")
def add_method(data: PayoutMethodModel, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    try:
        m = add_payout_method(db, me, data.kind, data.destination, data.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "method_id": m.id, "kind": m.kind, "verified": m.verified}


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
    return {"methods": [{"id": m.id, "kind": m.kind, "destination": m.destination,
                         "label": m.label, "verified": m.verified}
                        for m in list_payout_methods(db, me.id)]}


@app.post("/wallet/withdraw")
def withdraw(data: WithdrawModel, user: dict = Depends(get_current_user),
             db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    m = get_payout_method(db, data.method_id, me.id)
    if not m:
        raise HTTPException(status_code=404, detail="Method not found")
    if not m.verified:
        raise HTTPException(status_code=403, detail="Method not verified")
    p = request_payout(db, me, m, data.amount)
    if not p:
        raise HTTPException(status_code=402, detail="Insufficient earnings")
    notifications.notify(db, me.id, "payout.requested", amount=p.amount_usd, kind=p.kind)
    return {"status": "ok", "payout_id": p.id, "amount_usd": p.amount_usd,
            "payout_status": p.status, "kind": p.kind}


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

@app.post("/orgs")
def create_org_endpoint(data: OrgCreateModel, user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    org = create_org(db, data.name, me)
    if not org:
        raise HTTPException(status_code=400, detail="Org name already taken")
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
    return {"status": "ok", "balance": bal, "budget_cap": org.budget_cap}


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

@app.post("/deposit")
def deposit_funds(data: DepositModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Top-up. In live mode this is disabled — funds come only via the payment
    webhook (so balances can't be minted for free)."""
    if PAYMENTS_MODE == "live":
        raise HTTPException(status_code=403,
                            detail="Direct deposit disabled; use checkout (payment webhook)")
    me = get_user_by_username(db, _username(user))
    balance = deposit(db, me, data.amount)
    return {"status": "ok", "balance": balance}


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


@app.get("/wallet")
def wallet(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"balance": round(me.balance, 4), "earnings": round(me.earnings, 4)}


@app.get("/me")
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


@app.get("/bookings/{booking_id}")
def booking_status(booking_id: int, user: dict = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    from db import Booking
    me = get_user_by_username(db, _username(user))
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b or not me or me.id not in (b.buyer_id, b.seller_id):
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"booking_id": b.id, "status": b.status, "gross_amount": b.gross_amount,
            "platform_fee": b.platform_fee, "seller_payout": b.seller_payout}


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
        _finalize_job(db, job)


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
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    segs = job_segments(db, job_id)
    return {"job_id": job.id, "kind": job.kind, "status": job.status,
            "total_segments": job.total_segments, "output_ref": job.output_ref,
            "stitch_task_id": job.stitch_task_id,
            "segments": [{"idx": s.idx, "task_id": s.task_id, "range": [s.range_start, s.range_end],
                          "status": s.status, "output_ref": s.output_ref} for s in segs]}


@app.post("/render")
def render_job(data: RenderModel, user: dict = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Render-farm: split a frame range across N verified nodes (chosen by the
    router) and dispatch a render task per node. Embarrassingly parallel; a dropped
    frame just re-renders via retry."""
    buyer = get_user_by_username(db, _username(user))
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
            "estimated_cost": round(sum(t["price_per_hour"] for t in tasks) * data.hours, 4)}


@app.post("/solve")
def solve_compute(intent: SolveModel, user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """AI Router: state intent, get a placement plan over verified inventory.
    The customer never picks a node — the router selects hardware, region,
    provider, and redundancy to satisfy the constraints at the best blended cost."""
    plan = select_plan(db, intent.model_dump())
    if not plan["selected"]:
        raise HTTPException(status_code=409, detail="No verified node satisfies these constraints")
    return plan


@app.get("/templates")
def list_templates():
    """One-click deployable stacks (Ollama, vLLM, ComfyUI, SD WebUI, TensorRT-LLM)."""
    return {"templates": public_catalog()}


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
    set_benchmark(db, spec, data.tokens_sec, data.meta or {})
    from db import record_rep_event
    record_rep_event(db, spec, "benchmark", data.tokens_sec)
    return {"status": "ok", "spec_id": spec.id, "tokens_sec": data.tokens_sec}



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


@app.post("/jobs/input_url")
def input_url(data: InputUrlModel, agent=Depends(api_key_user),
              db: Session = Depends(get_db)):
    """Pre-signed GET so a node can pull a job input (e.g. a .blend scene) it was
    assigned — without holding standing object-storage credentials."""
    task = get_task_for_agent(db, data.task_id, agent)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found or not yours")
    key = data.ref.split("/", 3)[-1] if data.ref.startswith("s3://") else data.ref
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
    from db import Task
    buyer = get_user_by_username(db, _username(user))
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not buyer or task.buyer_id != buyer.id:
        raise HTTPException(status_code=404, detail="Task not found")
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
    """Live log stream for a task the buyer owns. Auth via ?token=<JWT>."""
    await websocket.accept()
    db = SessionLocal()
    try:
        try:
            claims = verify_token(token)
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

@app.post("/create_api_key")
def create_api_key(days: int = Query(7, ge=1, le=90),
                   scopes: Optional[str] = Query(None, description="comma-separated, e.g. node,jobs"),
                   label: Optional[str] = Query(None),
                   user: dict = Security(get_current_user),
                   db: Session = Depends(get_db)):
    scope_list = [x.strip() for x in scopes.split(",")] if scopes else []
    api_key, jti = gen_secure_api_key(_username(user), days, scope_list)
    me = get_user_by_username(db, _username(user))
    record_issued_key(db, me.id, jti, label, scope_list, days)
    return {"status": "ok", "api_key": api_key, "jti": jti, "scopes": scope_list}


@app.get("/account/keys")
def list_keys(user: dict = Security(get_current_user), db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    return {"keys": list_issued_keys(db, me.id)}


@app.post("/keys/{jti}/revoke")
def revoke_key_by_jti(jti: str, user: dict = Security(get_current_user),
                      db: Session = Depends(get_db)):
    me = get_user_by_username(db, _username(user))
    owned = {k["jti"] for k in list_issued_keys(db, me.id)}
    if jti not in owned:
        raise HTTPException(status_code=404, detail="Key not found")
    revoke_jti(db, jti)
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
