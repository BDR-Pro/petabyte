from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, CheckConstraint, update, event, Numeric,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import bcrypt
import hashlib
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import os
import secrets
import string

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")


def payments_mode() -> str:
    """Current money mode: 'LIVE' only when live payments are explicitly enabled,
    else 'TEST'. Stamped (immutably) on every financial record so test and live money
    can never be mixed or counted together. Authoritative live gate lives in
    stripe_gateway.assert_test_mode; this only chooses the label."""
    return "LIVE" if os.getenv("PAYMENTS_LIVE_ENABLED", "").lower() == "true" else "TEST"


# ---------------------------------------------------------------------------
# Money.
# Money is NEVER a float. 0.1 + 0.2 != 0.3 in binary floating point, and a
# marketplace that holds other people's funds cannot carry that error. All monetary
# columns are NUMERIC(20,8) and all monetary arithmetic is Decimal.
#   - On Postgres this is a true exact NUMERIC.
#   - On SQLite (tests) there is no decimal type; SQLAlchemy round-trips via float,
#     so tests verify LOGIC exactly but exactness in storage is a Postgres property.
# Use D() to lift any number into Decimal and q() to quantize to the storage scale.
# ---------------------------------------------------------------------------
Money = Numeric(20, 8)          # exact to 8 dp — enough for per-second billing
_CENTS = Decimal("0.01")
_SCALE = Decimal("0.00000001")


def D(x) -> Decimal:
    """Lift anything numeric into Decimal WITHOUT going through binary float."""
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal(0)
    return Decimal(str(x))      # str() first: Decimal(0.1) would inherit float error


def _json_money(o):
    """Serialize Decimal exactly (as a JSON number via str) — never via float."""
    if isinstance(o, Decimal):
        return float(o)     # transport only; storage + arithmetic stay Decimal
    raise TypeError(f"not serializable: {type(o).__name__}")


def q(x) -> Decimal:
    """Quantize to storage scale (8 dp), half-up like an accountant."""
    return D(x).quantize(_SCALE, rounding=ROUND_HALF_UP)


def qc(x) -> Decimal:
    """Quantize to cents — for anything a human will see or be charged."""
    return D(x).quantize(_CENTS, rounding=ROUND_HALF_UP)


PLATFORM_TAKE_RATE = D(os.getenv("PLATFORM_TAKE_RATE", "0.10"))
HEARTBEAT_TIMEOUT_S = int(os.getenv("HEARTBEAT_TIMEOUT_S", "60"))
MIN_REPUTATION = int(os.getenv("MIN_REPUTATION", "50"))
# Instant payout fee: scheduled/batch payouts are FREE; an on-demand instant cash-out costs a
# small fee (a real revenue line). Percentage with a flat floor. Never exceeds the amount.
INSTANT_PAYOUT_FEE_PCT = D(os.getenv("INSTANT_PAYOUT_FEE_PCT", "0.015"))
INSTANT_PAYOUT_FEE_MIN = D(os.getenv("INSTANT_PAYOUT_FEE_MIN", "0.50"))
# Anti-fraud payout holds. Earnings from a just-completed job are held for a clearing/dispute +
# re-verification window before they can be withdrawn. INSTANT payout (fast cash-out) is locked
# until a seller has matured: minimum reputation AND at least this many completed (released) jobs.
EARNINGS_HOLD_HOURS = int(os.getenv("EARNINGS_HOLD_HOURS", "24"))
PAYOUT_MATURITY_MIN_JOBS = int(os.getenv("PAYOUT_MATURITY_MIN_JOBS", "3"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rand_vm_id() -> str:
    """Opaque, non-enumerable VM handle: first char a letter, then 11 alphanumeric
    (lowercase). ~12 chars over base36 -> collision-negligible and unguessable, so
    ids never leak volume or let anyone probe vm-2, vm-3, ..."""
    first = secrets.choice(string.ascii_lowercase)
    rest = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(11))
    return first + rest


# ------------------ Engine with pooling / resilience ------------------

_engine_kwargs = dict(echo=False, future=True)
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # pool_pre_ping survives DB failover / idle drops; bounded statement timeout.
    _engine_kwargs.update(
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        connect_args={"options": "-c statement_timeout=30000"},
    )

engine = create_engine(DATABASE_URL, **_engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_con, _):
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")     # concurrent readers + 1 writer
        cur.execute("PRAGMA busy_timeout=5000")    # wait, don't error, on lock
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


# ------------------ Password hashing ------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode()[:72], hashed.encode())
    except (ValueError, TypeError):
        return False


# ------------------ Models ------------------

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="buyer", nullable=False)
    reputation = Column(Integer, default=100, nullable=False)
    email = Column(String, nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    email_token = Column(String, nullable=True)         # hashed verification token
    email_token_exp = Column(DateTime, nullable=True)   # short-lived
    notify_email = Column(Boolean, default=True)
    # --- two-factor auth (TOTP / authenticator app) ---
    totp_secret = Column(String, nullable=True)          # base32 secret, ENCRYPTED at rest (utils.seal_secret)
    totp_enabled = Column(Boolean, default=False, nullable=False)  # True only after a code is confirmed
    totp_backup_codes = Column(Text, nullable=True)      # JSON list of bcrypt-hashed single-use recovery codes
    tests_passed = Column(Integer, default=0, nullable=False)
    tests_failed = Column(Integer, default=0, nullable=False)
    can_accept_paid_jobs = Column(Boolean, default=True, nullable=False)
    balance = Column(Money, default=Decimal(0), nullable=False)   # buyer spendable credits
    earnings = Column(Money, default=Decimal(0), nullable=False)  # seller accrued payouts
    # --- referrals ---
    referral_code = Column(String, unique=True, index=True, nullable=True)  # this user's share code
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)    # who referred them
    referral_rewarded = Column(Boolean, default=False, nullable=False)      # did their qualifying event already pay out?
    referral_signup_meta = Column(String, nullable=True)                    # ip/dest at signup, for self-referral checks
    # Seeded demo entity. NEVER shown as real traction: metrics separate demo from
    # real, and the UI badges anything demo as "Demo data".
    is_demo = Column(Boolean, default=False, nullable=False, index=True)
    # Signup timestamp — powers funding cohorts (retention) + time-to-first-value. Nullable
    # so pre-existing rows (created before this column) don't block; new users always get it.
    created_at = Column(DateTime, default=_utcnow, index=True)
    # A user's spendable balance and accrued earnings can NEVER go negative — enforced at the
    # DB layer, not only by the guarded-debit application logic (defence in depth).
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_user_balance_nonneg"),
        CheckConstraint("earnings >= 0", name="ck_user_earnings_nonneg"),
    )


class SellerSpec(Base):
    __tablename__ = "specs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    cpu = Column(Integer, nullable=False)
    ram = Column(Integer, nullable=False)            # GB
    gpu_model = Column(String, nullable=True)
    gpu_count = Column(Integer, default=0)
    vram_gb = Column(Integer, default=0)
    public_id = Column(String, unique=True, index=True, default=lambda: _rand_vm_id())  # opaque listing handle
    price_per_hour = Column(Money, nullable=False)   # USD/hr
    min_price = Column(Money, nullable=True)         # auto-price floor (seller's cost)
    max_price = Column(Money, nullable=True)         # auto-price ceiling
    auto_price = Column(Boolean, default=False)      # opt-in demand pricing (engine TBD)
    duration = Column(Integer, nullable=False)       # max rentable hours
    provider = Column(String, index=True)
    region = Column(String, index=True, nullable=True)   # declared region, e.g. eu-west
    country = Column(String, nullable=True)              # declared ISO country
    detected_country = Column(String, nullable=True)     # GeoIP-derived from node IP
    region_verified = Column(Boolean, default=False)     # declared country == detected
    benchmark_tokens_sec = Column(Float, nullable=True)  # last LLM tokens/sec benchmark
    benchmark_meta = Column(Text, nullable=True)         # JSON: other metrics
    benchmark_at = Column(DateTime, nullable=True)
    # verdict of comparing a reported benchmark against the CLAIMED gpu_model's public
    # reference band (gpu_benchmark.classify): consistent | implausibly_low |
    # suspiciously_high | unknown_model | None. Feeds the honest trust ladder.
    benchmark_verdict = Column(String, nullable=True)
    # server-observed wall-clock (seconds) from dispatching the benchmark task to receiving
    # the signed result — the platform TIMED it, so the number isn't purely self-reported.
    benchmark_elapsed_s = Column(Float, nullable=True)
    jobs_completed = Column(Integer, default=0)
    jobs_failed = Column(Integer, default=0)
    fraud_count = Column(Integer, default=0)
    latency_sum_s = Column(Float, default=0.0)
    latency_n = Column(Integer, default=0)
    heartbeats = Column(Integer, default=0)
    first_seen = Column(DateTime, nullable=True)
    idle_fallback = Column(Boolean, default=False)   # opt-in: mine (NiceHash) when unrented
    idle_algo = Column(String, nullable=True)
    idle_hashrate = Column(Float, nullable=True)
    idle_est_daily_usd = Column(Float, nullable=True)
    idle_reported_at = Column(DateTime, nullable=True)
    # --- rent SPARE DISK to a web3/BitTorrent storage network (Storj/BTFS/Sia). NOT an idle/
    # fallback mode — it is an EXPLICIT, always-on contribution the seller configures with real
    # arguments (a provider AND a GB cap; neither is defaulted). It runs INDEPENDENTLY of GPU
    # rentals (disk != GPU), so it earns whether or not a job is running. Each node contributes as a
    # UNIQUE node name (pbdisk-<spec_id>) so earnings attribute 1:1 to the seller's unified balance
    # — no per-seller storage wallet. The seller can change the cap, pause, or delete at any time. ---
    disk_enabled = Column(Boolean, default=False)    # explicit on/off (requires provider + cap to enable)
    disk_provider = Column(String, nullable=True)    # storj | btfs | sia (adapter) — REQUIRED to enable
    disk_alloc_gb = Column(Integer, nullable=True)   # seller's hard cap on contributed GB — REQUIRED to enable
    disk_used_gb = Column(Float, nullable=True)      # last reported used GB
    disk_est_daily_usd = Column(Float, nullable=True)
    disk_reported_at = Column(DateTime, nullable=True)
    # model cache-locality: which model ids this node already holds locally (JSON list). The
    # scheduler favours a node that already has the requested model, so a 20-100 GB weight file
    # isn't re-downloaded when an equally-good node already has it.
    cached_models = Column(Text, nullable=True)
    cached_models_at = Column(DateTime, nullable=True)
    # capacity
    total_units = Column(Integer, default=1, nullable=False)
    available_units = Column(Integer, default=1, nullable=False)
    # trust / liveness
    attested = Column(Boolean, default=False)
    attested_at = Column(DateTime, nullable=True)
    attest_pubkey = Column(String, nullable=True)   # Ed25519 pubkey from /prove
    status = Column(String, default="offline", nullable=False)  # online|offline
    last_seen = Column(DateTime, nullable=True)
    confidential = Column(Boolean, default=False)      # TEE-attested (enclave)
    tee_vendor = Column(String, nullable=True)         # e.g. nvidia-h100-cc, amd-sev-snp
    tee_measurement = Column(String, nullable=True)    # attested enclave measurement
    tee_report = Column(Text, nullable=True)           # raw report (for buyer re-verify)
    tee_attested_at = Column(DateTime, nullable=True)  # when confidential was last attested (freshness)
    is_demo = Column(Boolean, default=False, nullable=False, index=True)  # seeded demo node


def trust_level_for(spec: "SellerSpec") -> dict:
    """The honest trust ladder for a listing. A level is awarded ONLY when its
    technical requirement is actually satisfied by evidence we hold:

      self_reported       registered via the API; nothing proven.
      agent_verified      the node's agent signed a hardware report with its
                          Ed25519 device key (/prove) — proves a keyholder on the
                          node claims this hardware, NOT that the silicon is real.
      benchmark_verified  agent_verified + a benchmark number the node's agent REPORTED and
                          SIGNED — so it is attributable (non-repudiable), but it is
                          self-reported, NOT independently measured by the platform.

    'hardware_attested' (real vendor TEE chain: NVIDIA NRAS / AMD SEV-SNP / Intel
    TDX) is deliberately NOT awardable today: the current verifier is a structural
    stub (stub.md #3). spec.confidential therefore surfaces separately as
    'cc_pilot' evidence and must never be marketed as hardware attestation.

    Honesty rule: the benchmark tier's label/evidence must never claim the throughput was
    'measured' or 'verified' by the platform — the agent's benchmark harness reports the number
    (today from BENCH_TOKENS_SEC) and signs it; the platform only records that signed claim."""
    if not spec.attested:
        return {"level": "self_reported", "rank": 0, "label": "Self-reported",
                "evidence": "Listing details supplied by the seller; no proof held."}
    verdict = getattr(spec, "benchmark_verdict", None)
    # A benchmark is present if the node reported a throughput OR any benchmark score was
    # graded against public reference data (a pure render/video benchmark carries no tok/s).
    tok = f"{round(spec.benchmark_tokens_sec)} tok/s" if spec.benchmark_tokens_sec else "a signed benchmark"
    if spec.benchmark_tokens_sec or verdict is not None:
        # A benchmark that did NOT match the claimed model's public reference data is NOT
        # corroborating evidence — it is a red flag. Don't let it upgrade the tier.
        if verdict in ("implausibly_low", "suspiciously_high"):
            return {"level": "agent_verified", "rank": 1,
                    "label": "Agent-verified (benchmark flagged)",
                    "evidence": "Hardware report signed by the node's Ed25519 device key. "
                                "A submitted benchmark did NOT match the claimed GPU model's "
                                f"public reference data ({verdict}) and was rejected as "
                                "corroborating evidence — the listing may be mislabeled."}
        if verdict == "consistent":
            timed = (f" The platform dispatched and TIMED the benchmark "
                     f"({round(spec.benchmark_elapsed_s, 1)}s observed), and the result is bound "
                     f"to that dispatch (no replay)." if getattr(spec, "benchmark_elapsed_s", None)
                     else "")
            return {"level": "benchmark_verified", "rank": 2, "label": "Benchmark-consistent",
                    "evidence": f"Agent-signed hardware report + {tok} that MATCHES public "
                                "reference data for the claimed GPU model (FP16 TFLOPS / Blender "
                                "Open Data / Cinebench / PugetBench)." + timed +
                                " Node-reported (not run in a platform enclave), but consistent "
                                "with the advertised card."}
        if spec.benchmark_tokens_sec:
            return {"level": "benchmark_verified", "rank": 2, "label": "Benchmark-reported",
                    "evidence": "Agent-signed hardware report + a node-REPORTED, signed benchmark "
                                f"({round(spec.benchmark_tokens_sec)} tok/s) — self-reported and "
                                "attributable, not independently measured by the platform."}
    return {"level": "agent_verified", "rank": 1, "label": "Agent-verified",
            "evidence": "Hardware report signed by the node's Ed25519 device key."}


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    org_id = Column(Integer, ForeignKey("orgs.id"), index=True, nullable=True)
    hours = Column(Integer, nullable=False)
    price_per_hour = Column(Money, nullable=False)   # SNAPSHOT: rate is locked at booking
    gross_amount = Column(Money, nullable=False)
    platform_fee = Column(Money, nullable=False)
    seller_payout = Column(Money, nullable=False)
    status = Column(String, default="escrowed", nullable=False)  # escrowed|active|released|refunded|cancelled
    vpn = Column(Boolean, default=False)
    # True for demo/sandbox bookings; excluded from GMV so test money never inflates
    # the marketplace/investor numbers. Set automatically from PAYMENTS_MODE at insert.
    test = Column(Boolean, nullable=False,
                  default=lambda: os.getenv("PAYMENTS_MODE", "sandbox").lower() != "live")
    is_demo = Column(Boolean, default=False, nullable=False, index=True)  # seeded demo booking
    created_at = Column(DateTime, default=_utcnow)
    released_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)




class Task(Base):
    """A unit of work tied to a paid Booking, executed by the spec's owner (agent)."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=True)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    task_type = Column(String, nullable=False)              # "notebook" | "vm" | "test"
    code = Column(Text, nullable=True)                       # notebook source
    vm_type = Column(String, nullable=True)                  # qemu|firecracker|docker
    cpu = Column(Integer, nullable=True)
    ram = Column(Integer, nullable=True)
    cuda = Column(Boolean, default=False)
    status = Column(String, default="pending", nullable=False)  # pending|assigned|running|completed|failed
    claimed_by = Column(String, nullable=True)              # username of the agent that claimed it
    priority = Column(Integer, default=0, index=True)       # higher = served first
    progress = Column(Integer, default=0)                   # 0-100
    progress_msg = Column(String, nullable=True)
    template = Column(String, nullable=True)                # e.g. ollama, vllm
    template_params = Column(Text, nullable=True)           # JSON (model, etc.)
    retries = Column(Integer, default=0)
    backup_enabled = Column(Boolean, default=False)
    backup_interval_s = Column(Integer, default=0)
    volume = Column(String, nullable=True)                 # logical data volume name
    latest_checkpoint_ref = Column(String, nullable=True)  # object-storage key of newest backup
    interrupted_at = Column(DateTime, nullable=True)       # set when its node died
    enc_key = Column(Text, nullable=True)                  # sealed per-task backup data key
    result = Column(Text, nullable=True)
    result_content_hash = Column(String, nullable=True)   # signed sha256 of the output bytes (#65)
    # Retained so a buyer can INDEPENDENTLY verify the result offline against the node's
    # attested Ed25519 pubkey (the verifiable-receipt surface): the exact signed payload and
    # its signature. Null on older jobs / test workloads.
    result_signature = Column(String, nullable=True)
    result_proof = Column(Text, nullable=True)            # JSON: the exact bytes the node signed
    created_at = Column(DateTime, default=_utcnow)
    assigned_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class VMRoute(Base):
    """A rentable VM instance with a STABLE id. The gateway proxies
    vm-<id>@petabyte.market to current_spec_id's node; on failover we re-point
    current_spec_id and the address stays the same. See docs/vm-rental.md.
    The id is a random alphanumeric handle (opaque, non-enumerable), NOT a
    sequential integer — so it never leaks volume or lets anyone guess vm-2, vm-3."""
    __tablename__ = "vm_routes"
    id = Column(String, primary_key=True, default=lambda: _rand_vm_id())  # e.g. q7bk2mrelpza
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=False)
    template = Column(String, nullable=True)
    current_spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    app_port = Column(Integer, default=0)                  # template's service port
    tunnel_port = Column(Integer, nullable=True)           # reported by node's frpc
    node_ip = Column(String, nullable=True)                # optional, for reachable nodes
    ssh_pubkey = Column(String, nullable=True)             # buyer key injected into VM
    snapshot_url = Column(String, nullable=True)           # latest S3 checkpoint
    status = Column(String, default="starting")            # starting|running|migrating|stopped|failed
    migrations = Column(Integer, default=0)
    hourly_rate = Column(Money, default=Decimal(0))        # $/hr charged for this VM
    started_at = Column(DateTime, nullable=True)           # when metering began
    paid_until = Column(DateTime, nullable=True)           # prepaid window end -> auto-stop
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class PriceChange(Base):
    """Audit log for auto-pricing: every price move, with the why. Transparency is
    what separates trusted dynamic pricing from surge-pricing suspicion."""
    __tablename__ = "price_changes"
    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    old_price = Column(Money, nullable=False)
    new_price = Column(Money, nullable=False)
    utilization = Column(Float, default=0)          # 0..1 class utilization at the time
    reason = Column(String, default="auto")         # auto|manual
    created_at = Column(DateTime, default=_utcnow)


class VMEvent(Base):
    """Timeline of a VM's life: created, tunnel-registered, migrated, extended,
    expired, stopped. Makes failover visible ('your VM moved nodes at 14:32')
    and is the support/debugging lifeline."""
    __tablename__ = "vm_events"
    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(String, ForeignKey("vm_routes.id"), index=True, nullable=False)
    event = Column(String, nullable=False)   # created|tunnel_registered|migrated|extended|expired|stopped|failed
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


def vm_event(db: Session, vm_id: str, event: str, detail: str = None):
    db.add(VMEvent(vm_id=vm_id, event=event, detail=detail))
    db.commit()


class TestWorkload(Base):
    """A known-answer test job. expected_hash is computed server-side at dispatch."""
    __tablename__ = "test_workloads"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    size = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    expected_hash = Column(String, nullable=False)
    difficulty = Column(String, default="easy")
    trigger = Column(String, default="manual")
    status = Column(String, default="pending")   # pending|passed|failed
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)


class QuorumCheck(Base):
    """Redundant re-execution: the SAME deterministic challenge is dispatched to several
    independent sellers and their results are compared. Honest sellers agree; a seller who
    fakes/corrupts the result diverges and is flagged. Used for deterministic workloads
    the platform can't cheaply compute itself (seller agreement is the oracle)."""
    __tablename__ = "quorum_checks"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, default=lambda: "qrm_" + _rand_vm_id())
    size = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    nonce = Column(String, nullable=False)
    min_agree = Column(Integer, nullable=False, default=2)
    status = Column(String, nullable=False, default="open", index=True)  # open|AGREED|DIVERGENT|INCONCLUSIVE
    agreed_hash = Column(String, nullable=True)
    submissions = Column(Text, nullable=False, default="{}")  # JSON {seller_id: {task_id, hash}}
    created_at = Column(DateTime, default=_utcnow, index=True)
    finalized_at = Column(DateTime, nullable=True)


class BenchmarkSample(Base):
    """Append-only log of every benchmark / hashrate observation — the labelled training corpus
    for the GPU-authenticity model (the data moat). GPU + performance signals only; NO PII.

    Each row pairs the raw signals (scores by metric, server-timing, proof-of-work result) with
    the spec's context at that moment (reputation, job history, attestation) and, over time, the
    fraud outcome — exactly the (features, label) shape a fraud/authenticity classifier trains on.
    Growing this dataset with every real benchmark is a compounding, proprietary advantage."""
    __tablename__ = "benchmark_samples"
    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=True)
    seller_id = Column(Integer, index=True, nullable=True)
    gpu_model = Column(String, nullable=True)
    source = Column(String, nullable=True)         # 'benchmark' | 'idle_mining'
    metrics = Column(Text, nullable=True)          # JSON {metric_name: score}
    verdict = Column(String, nullable=True)        # consistent | implausibly_low | ...
    pow_verified = Column(Boolean, nullable=True)  # fresh server proof-of-work answered?
    elapsed_s = Column(Float, nullable=True)       # server-observed wall-clock
    tokens_sec = Column(Float, nullable=True)
    # spec-context features (snapshot at sample time)
    reputation = Column(Integer, nullable=True)
    jobs_completed = Column(Integer, nullable=True)
    jobs_failed = Column(Integer, nullable=True)
    fraud_count = Column(Integer, nullable=True)
    attested = Column(Boolean, nullable=True)
    confidential = Column(Boolean, nullable=True)
    region_verified = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class Organization(Base):
    """Enterprise/lab account with a shared wallet and optional budget cap."""
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    balance = Column(Money, default=Decimal(0), nullable=False)
    budget_cap = Column(Money, default=Decimal(0), nullable=False)   # 0 = unlimited
    spent = Column(Money, default=Decimal(0), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class OrgMember(Base):
    __tablename__ = "org_members"
    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    role = Column(String, nullable=False)   # admin|billing|member
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_org_member"),)


class SellerPayoutMethod(Base):
    """Where a seller gets paid: gift card (Tremendous/Tango), USDC, or bank."""
    __tablename__ = "payout_methods"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)            # gift_card|usdc|bank
    destination = Column(String, nullable=False)     # email | wallet addr | account ref
    label = Column(String, nullable=True)
    verified = Column(Boolean, default=False)        # KYC/ownership check passed
    created_at = Column(DateTime, default=_utcnow)


class Payout(Base):
    """A withdrawal of seller earnings. USD is the unit of account; the rail is an
    adapter. State machine: requested -> sent -> confirmed | failed."""
    __tablename__ = "payouts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    method_id = Column(Integer, ForeignKey("payout_methods.id"), nullable=False)
    amount_usd = Column(Money, nullable=False)       # NET sent to the rail (amount minus any fee)
    fee_usd = Column(Money, nullable=True, default=Decimal(0))  # instant-payout fee kept by platform
    kind = Column(String, nullable=False)
    status = Column(String, default="requested", nullable=False)
    provider_ref = Column(String, nullable=True)     # provider txn id / tx hash
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class PayoutSchedule(Base):
    """Auto-withdraw on a weekly cadence, e.g. Monday 08:00 local."""
    __tablename__ = "payout_schedules"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    method_id = Column(Integer, ForeignKey("payout_methods.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)    # 0=Mon .. 6=Sun
    hour = Column(Integer, nullable=False)
    minute = Column(Integer, default=0)
    utc_offset_minutes = Column(Integer, default=0)  # local tz offset from UTC
    min_amount = Column(Money, default=Decimal(1))   # skip if balance below this
    enabled = Column(Boolean, default=True)
    next_run_at = Column(DateTime, nullable=False)
    last_run_at = Column(DateTime, nullable=True)


class LedgerTx(Base):
    """A single financial event. Its entries MUST balance: debits == credits.

    This is the unit of truth for money. `users.balance` and `users.earnings` are
    caches of what the ledger says; if they ever disagree, the ledger is right."""
    __tablename__ = "ledger_tx"
    id = Column(Integer, primary_key=True)   # PK is already indexed; naming it would
                                             # collide with ledger.tx_id's index name
    reference_type = Column(String, index=True, nullable=False)   # booking|deposit|payout|idle_mining|org
    reference_id = Column(String, index=True, nullable=True)      # e.g. the booking id
    description = Column(String, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)  # replay -> same tx
    created_at = Column(DateTime, default=_utcnow, index=True)


class LedgerEntry(Base):
    """One leg of a transaction. Append-only: never updated, never deleted.

    Convention: an account's balance = SUM(credits) - SUM(debits).
    Money entering the system credits a user and debits an `external:` account, so the
    books always sum to zero across every account. That is what makes it double-entry
    rather than a list of things that happened."""
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, ForeignKey("ledger_tx.id"), index=True, nullable=True)
    account = Column(String, index=True, nullable=False)   # e.g. buyer_available:12, escrow:99
    direction = Column(String, nullable=True)              # debit | credit
    amount = Column(Money, nullable=False)                 # always POSITIVE
    # --- kept so existing readers/reports keep working ---
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    entry_type = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    # DB-level invariants (defence in depth): a leg's amount is ALWAYS positive (the
    # convention in the docstring), and direction is a closed set. These make money impossible
    # to create/destroy via a stray write or raw SQL that bypasses post(). Apply on fresh
    # databases (create_all); existing DBs pick them up on a schema rebuild/migration.
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_ledger_amount_pos"),
        # `x IN (...)` is NULL (not FALSE) when x is NULL, so a NULL direction would slip past a
        # bare IN check. Require it explicitly — a ledger leg with no debit/credit is invalid.
        CheckConstraint("direction is not null and direction in ('debit','credit')",
                        name="ck_ledger_direction"),
    )


# ---- account naming ----------------------------------------------------------
DEBIT, CREDIT = "debit", "credit"


def acct_buyer(uid):      return f"buyer_available:{uid}"
def acct_escrow(bid):     return f"escrow:{bid}"
def acct_seller(uid):     return f"seller_earnings:{uid}"
def acct_org(oid):        return f"org_available:{oid}"
# UNIT SCALES (audit STD-E). The platform runs two long-standing money conventions:
#   * the WALLET/BOOKING path (this module: deposits, escrow, booking capture/settle, data-API,
#     mining, storage, instant payouts) posts Decimal DOLLARS;
#   * the STRIPE-CONNECT compute path (stripe_connect.py: capture/refund/processing-fee) posts
#     integer MINOR UNITS (cents), the unit pricing.py + PayoutObligation.net_amount_minor use.
# Each individual post() is internally consistent, but summing one account across BOTH scales is
# meaningless ($10 wallet top-up posts 10; a $10 card capture posts 1000). So the two scales get
# SEPARATE clearing/revenue accounts and account_balance() is never mixed across scales. The bare
# names below are the DOLLAR accounts; the *_MINOR names are the Stripe-Connect (cents) accounts.
PLATFORM_REVENUE   = "platform_revenue"     # DOLLARS: booking/data/mining/storage/payout-fee revenue
EXTERNAL_PAYMENTS  = "external:payments"    # DOLLARS: wallet/booking card + org top-up clearing
PLATFORM_REVENUE_MINOR  = "platform_revenue:minor"   # MINOR: Stripe-Connect compute commission
EXTERNAL_PAYMENTS_MINOR = "external:payments:minor"  # MINOR: Stripe-Connect card clearing
EXTERNAL_PAYOUTS   = "external:payouts"     # the bank / USDC rail
EXTERNAL_MINING    = "external:mining"      # NiceHash
EXTERNAL_STORAGE   = "external:storage"     # decentralized storage network (Storj/BTFS/Sia)
EXTERNAL_PROMO     = "external:promo"       # referral / promotional credit (marketing spend)


class UnbalancedTransaction(Exception):
    """Raised when debits != credits. This must never reach production; it means
    money was about to be created or destroyed."""


def post(db: Session, reference_type: str, legs: list, reference_id=None,
         description: str = None, idempotency_key: str = None,
         booking_id: int = None, entry_type: str = None) -> "LedgerTx":
    """Write ONE balanced transaction. `legs` = [(account, direction, amount, user_id?)].

    Refuses to write if debits != credits. There is deliberately no way to append a
    single-sided entry: the only door into the ledger is this function, and it will
    not let you through with unbalanced books.
    """
    debits  = sum((q(a) for (_, d, a, *_r) in legs if d == DEBIT),  Decimal(0))
    credits = sum((q(a) for (_, d, a, *_r) in legs if d == CREDIT), Decimal(0))
    if debits != credits:
        raise UnbalancedTransaction(
            f"{reference_type}: debits {debits} != credits {credits}")
    if debits == 0:
        raise UnbalancedTransaction(f"{reference_type}: zero-value transaction")

    tx = LedgerTx(reference_type=reference_type,
                  reference_id=str(reference_id) if reference_id is not None else None,
                  description=description, idempotency_key=idempotency_key)
    db.add(tx)
    db.flush()                      # need tx.id for the entries
    for leg in legs:
        account, direction, amount = leg[0], leg[1], leg[2]
        uid = leg[3] if len(leg) > 3 else None
        db.add(LedgerEntry(
            tx_id=tx.id, account=account, direction=direction, amount=q(amount),
            user_id=uid, booking_id=booking_id,
            entry_type=entry_type or f"{reference_type}_{direction}"))
    return tx


def account_balance(db: Session, account: str) -> Decimal:
    """Reconstruct an account balance FROM THE LEDGER: credits - debits."""
    rows = db.query(LedgerEntry).filter(LedgerEntry.account == account).all()
    bal = Decimal(0)
    for e in rows:
        bal += D(e.amount) if e.direction == CREDIT else -D(e.amount)
    return q(bal)


def seller_recoverable_debt_minor(db: Session, seller_id: int) -> int:
    """Minor units a seller owes the platform from a post-payout refund clawback — i.e. the amount
    by which their `seller_payable` ledger balance is MORE negative than their still-unpaid
    obligations can explain. Zero when the books are square.

    A refund/chargeback on a job whose seller was already paid via the batch path DEBITs
    seller_payable (the platform fronted the buyer's refund) with no reversible transfer to claw
    back — leaving a recoverable NEGATIVE balance (see stripe_connect.refund / audit killer #6).
    Unpaid obligations (accrued/available/batched) are seller_payable CREDITs not yet disbursed, so:

        recoverable_debt = Σ(unpaid obligation nets) − seller_payable_balance   (floored at 0)

    Clawback auto-netting (payout_routing) uses this to recover the debt from the seller's next
    payout instead of leaving it for manual operator recovery."""
    from sqlalchemy import func
    unpaid = (db.query(func.coalesce(func.sum(PayoutObligation.net_amount_minor), 0))
              .filter(PayoutObligation.seller_id == seller_id,
                      PayoutObligation.state.in_(["accrued", "available", "batched"]))
              .scalar()) or 0
    bal = account_balance(db, acct_seller_payable(seller_id))
    debt = int(unpaid) - int(bal)
    return debt if debt > 0 else 0


def ledger_is_balanced(db: Session):
    """Every transaction must balance, and the whole ledger must sum to zero.
    Returns (ok, list_of_broken_tx_ids)."""
    broken = []
    total = Decimal(0)
    for e in db.query(LedgerEntry).all():
        total += D(e.amount) if e.direction == CREDIT else -D(e.amount)
    for tx in db.query(LedgerTx).all():
        legs = db.query(LedgerEntry).filter(LedgerEntry.tx_id == tx.id).all()
        dr = sum((D(e.amount) for e in legs if e.direction == DEBIT), Decimal(0))
        cr = sum((D(e.amount) for e in legs if e.direction == CREDIT), Decimal(0))
        if dr != cr:
            broken.append(tx.id)
    return (not broken and q(total) == 0), broken


def financial_integrity(db: Session) -> dict:
    """Index-friendly ledger invariants for the runtime financial heartbeat (#286/#287).

    Computed entirely in SQL — it never loads the ledger into Python, so it stays cheap at
    10k+ entries per account (#229/#230). Returns:
      balanced       True iff EVERY transaction balances AND the whole ledger nets to zero
      net_minor      signed sum (credits - debits) across all entries; must be 0
      imbalanced_tx  number of ledger transactions whose debits != credits
    """
    from sqlalchemy import func, case
    signed = func.sum(case((LedgerEntry.direction == CREDIT, LedgerEntry.amount),
                           else_=-LedgerEntry.amount))
    net = db.query(func.coalesce(signed, 0)).scalar() or 0
    dr = func.sum(case((LedgerEntry.direction == DEBIT, LedgerEntry.amount), else_=0))
    cr = func.sum(case((LedgerEntry.direction == CREDIT, LedgerEntry.amount), else_=0))
    per_tx = (db.query(LedgerEntry.tx_id.label("tid"), dr.label("dr"), cr.label("cr"))
              .group_by(LedgerEntry.tx_id).subquery())
    imbalanced = (db.query(func.count()).select_from(per_tx)
                  .filter(per_tx.c.dr != per_tx.c.cr).scalar()) or 0
    return {"balanced": bool(D(net) == 0 and int(imbalanced) == 0),
            "net_minor": float(D(net)), "imbalanced_tx": int(imbalanced)}


def payout_backlog(db: Session) -> dict:
    """Payout-scheduler health (#289/#294): how many settled-but-unpaid obligations are
    waiting and how old the oldest is. 'accrued'/'available' = owed to a seller but not yet
    placed in a batch. A growing/aging backlog means the payout scheduler has stalled."""
    from sqlalchemy import func
    waiting = ("accrued", "available")
    count = (db.query(func.count(PayoutObligation.id))
             .filter(PayoutObligation.state.in_(waiting)).scalar()) or 0
    oldest = (db.query(func.min(PayoutObligation.created_at))
              .filter(PayoutObligation.state.in_(waiting)).scalar())
    age_s = 0
    if oldest is not None:
        now = _utcnow()
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        if getattr(oldest, "tzinfo", None) is not None:
            oldest = oldest.replace(tzinfo=None)
        age_s = max(0, int((now - oldest).total_seconds()))
    return {"unbatched": int(count), "oldest_age_seconds": age_s}


def seller_payable_by_mode(db: Session) -> dict:
    """Outstanding seller payable (MINOR units) per money mode: net earned by sellers but not
    yet paid out. Owed = states accrued/available/batched (paid/reversed/failed are excluded).
    Keyed by lowercased mode ('test'|'live') so it lines up with the payment_mode metric label —
    TEST and LIVE money are never summed into one figure."""
    from sqlalchemy import func
    owed = ("accrued", "available", "batched")
    rows = (db.query(PayoutObligation.mode,
                     func.coalesce(func.sum(PayoutObligation.net_amount_minor), 0))
            .filter(PayoutObligation.state.in_(owed))
            .group_by(PayoutObligation.mode).all())
    return {str(mode or "unknown").lower(): int(total or 0) for mode, total in rows}


class NewsletterSubscriber(Base):
    """Authoritative record of a newsletter signup. Postgres is the source of truth; the
    Mailgun mailing list is the delivery mechanism kept in sync via `mailgun_synced`.

    Single opt-in today (status jumps straight to 'subscribed', confirmed_at set on signup),
    but the schema already carries 'pending' + confirmed_at so double opt-in can be layered
    on later without a breaking change."""
    __tablename__ = "newsletter_subscribers"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)   # normalized, lowercased
    status = Column(String, nullable=False, default="subscribed", index=True)  # pending|subscribed|unsubscribed
    source = Column(String, nullable=True)                            # e.g. "homepage"
    mailgun_synced = Column(Boolean, default=False, nullable=False)   # reconciliation flag
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)                    # when the address opted in
    unsubscribed_at = Column(DateTime, nullable=True)


def record_newsletter_signup(db: Session, email: str, source: str = "homepage") -> str:
    """Idempotently record a newsletter signup (single opt-in). Returns a status:

      'new'          a new subscriber row was created
      'active'       already subscribed (idempotent no-op)
      'reactivated'  a still-PENDING (never-confirmed) signup was confirmed to subscribed
      'suppressed'   the address was previously UNSUBSCRIBED — its opt-out is PRESERVED and
                     is NOT silently reactivated by an (unauthenticated) public request.
                     Re-subscription must go through a confirmed / double-opt-in flow, so the
                     caller MUST NOT re-add a suppressed address to the Mailgun list.

    Never raises on a duplicate — the unique constraint on `email` is the final guard."""
    existing = (db.query(NewsletterSubscriber)
                .filter(NewsletterSubscriber.email == email).first())
    if existing:
        if existing.status == "subscribed":
            return "active"
        if existing.status == "unsubscribed":
            # Consent boundary: a recipient who opted out is not resubscribed by anyone who
            # merely knows their address. Leave the row untouched (no Mailgun re-add).
            return "suppressed"
        # status == "pending": they signed up and never opted out -> confirm it.
        existing.status = "subscribed"
        existing.unsubscribed_at = None
        if existing.confirmed_at is None:
            existing.confirmed_at = _utcnow()
        db.add(existing)
        db.commit()
        return "reactivated"
    sub = NewsletterSubscriber(email=email, status="subscribed", source=source,
                               confirmed_at=_utcnow())
    db.add(sub)
    try:
        db.commit()
        return "new"
    except IntegrityError:
        db.rollback()          # concurrent duplicate insert -> idempotent success
        return "active"


def unsynced_newsletter_subscribers(db: Session, limit: int = 200) -> list:
    """Subscribed addresses NOT yet reflected into the mailing list (Mailgun down/unconfigured
    at signup, or a transient failure). A reconciliation job drains these so a signup that
    returned 'you're subscribed' actually receives the newsletter. Oldest first (FIFO)."""
    return (db.query(NewsletterSubscriber)
            .filter(NewsletterSubscriber.status == "subscribed",
                    NewsletterSubscriber.mailgun_synced == False)   # noqa: E712
            .order_by(NewsletterSubscriber.created_at.asc())
            .limit(max(1, int(limit))).all())


def count_unsynced_newsletter(db: Session) -> int:
    from sqlalchemy import func as _func
    return int(db.query(_func.count(NewsletterSubscriber.id))
               .filter(NewsletterSubscriber.status == "subscribed",
                       NewsletterSubscriber.mailgun_synced == False).scalar() or 0)  # noqa: E712


def mark_newsletter_synced(db: Session, email: str, synced: bool = True) -> None:
    """Record whether the address has been reflected into the Mailgun mailing list, so a
    reconciliation job can later re-sync rows that Mailgun rejected/timed out on."""
    sub = (db.query(NewsletterSubscriber)
           .filter(NewsletterSubscriber.email == email).first())
    if sub and sub.mailgun_synced != synced:
        sub.mailgun_synced = synced
        db.add(sub)
        db.commit()


def unsubscribe_newsletter(db: Session, email: str) -> bool:
    """Mark an address unsubscribed locally. Returns False if unknown. Mailgun list removal
    (if used) is reconciled separately; local state stays authoritative."""
    sub = (db.query(NewsletterSubscriber)
           .filter(NewsletterSubscriber.email == email).first())
    if not sub:
        return False
    sub.status = "unsubscribed"
    sub.unsubscribed_at = _utcnow()
    # The Mailgun list still has this member until removal completes; flag it so
    # reconciliation can detect the pending removal (local state stays authoritative).
    sub.mailgun_synced = False
    db.add(sub)
    db.commit()
    return True


class Platform(Base):
    __tablename__ = "platform"
    id = Column(Integer, primary_key=True)
    revenue = Column(Money, default=Decimal(0), nullable=False)
    # KILL SWITCH. Stops NEW bookings while letting running rentals finish and settle
    # normally. In a pilot you will need to stop the world at 2am without killing
    # someone's 6-hour render.
    bookings_paused = Column(Boolean, default=False, nullable=False)
    pause_reason = Column(String, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    # Admin-editable landing-page video (stored as the YouTube video id).
    landing_video_id = Column(String, nullable=True)
    # "portrait" (9:16, a Short) or "landscape" (16:9, a normal video). Auto-detected
    # from the pasted URL, admin-overridable.
    landing_video_orientation = Column(String, nullable=True)


class AuditEvent(Base):
    """Append-only record of who did what. Never updated, never deleted.

    This is what you read when a buyer disputes a charge, when a payout goes to the
    wrong bank account, or when you need to know which key launched the workload that
    got a seller's ISP angry. The reputation log is about node quality; this is about
    accountability."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    actor_username = Column(String, index=True, nullable=True)   # kept even if user is deleted
    actor_type = Column(String, default="user")                  # user|api_key|system|admin
    action = Column(String, index=True, nullable=False)          # e.g. payout_method.changed
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    detail = Column(Text, nullable=True)                         # JSON, never secrets
    org_id = Column(Integer, ForeignKey("orgs.id"), index=True, nullable=True)  # team scope, if any
    # Tamper-evidence: each row commits to its own canonical fields (content_hash) and links to the
    # previous row (chain_hash = sha256(prev.chain_hash + content_hash)). A silent edit or a deletion
    # is then detectable by verify_audit_chain(). Nullable so pre-existing rows (written before the
    # chain landed) don't block startup — verify() treats a null-hash row as the chain's genesis.
    content_hash = Column(String, nullable=True)
    chain_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class Volume(Base):
    """A buyer-owned persistent volume that outlives any single VM. It stores content-addressed,
    DEDUPLICATED snapshots in object storage: identical/unchanged files across snapshots are stored
    once, so each new snapshot only uploads the DELTA (changed content) — never a full-disk mirror.
    `bytes_stored` is the sum of unique blob sizes actually held (the real cost)."""
    __tablename__ = "volumes"
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    org_id = Column(Integer, ForeignKey("orgs.id"), index=True, nullable=True)
    name = Column(String, nullable=False)
    size_limit_gb = Column(Integer, nullable=True)          # optional hard cap on unique bytes held
    bytes_stored = Column(Integer, default=0, nullable=False)   # sum of unique (deduped) blob sizes
    snapshot_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class VolumeBlob(Base):
    """Index of the unique content blobs held for a volume (one row per distinct sha256). This is
    what makes snapshots incremental: a blob already present is never re-uploaded or re-billed. The
    bytes live in object storage at volumes/<buyer>/<volume>/blobs/<sha256>."""
    __tablename__ = "volume_blobs"
    id = Column(Integer, primary_key=True, index=True)
    volume_id = Column(Integer, ForeignKey("volumes.id"), index=True, nullable=False)
    sha256 = Column(String, index=True, nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("volume_id", "sha256", name="uq_volume_blob"),)


class VolumeSnapshot(Base):
    """One point-in-time snapshot: a manifest of the important files (path -> content sha256), plus
    how many NEW bytes it added (delta_bytes) vs. how big it is logically (total_bytes). Restoring a
    snapshot 'since' an earlier one returns only the files whose content changed — the delta."""
    __tablename__ = "volume_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    volume_id = Column(Integer, ForeignKey("volumes.id"), index=True, nullable=False)
    seq = Column(Integer, nullable=False)
    label = Column(String, nullable=True)
    vm_id = Column(String, nullable=True)                   # provenance: the VM that produced it
    manifest = Column(Text, nullable=False)                 # JSON [{path, sha256, size, mode?}]
    total_bytes = Column(Integer, default=0, nullable=False)  # logical size (sum of file sizes)
    delta_bytes = Column(Integer, default=0, nullable=False)  # NEW unique bytes this snapshot added
    created_at = Column(DateTime, default=_utcnow)


def _audit_content(actor_username, actor_type, action, resource_type, resource_id,
                   org_id, detail, ts) -> str:
    """Deterministic serialization of the fields the tamper-evidence hash commits to. Order-stable
    so the same row hashes identically on write and on verify. The timestamp is normalized to a
    NAIVE-UTC isoformat because an aware datetime on write round-trips to a naive one on read (the
    DB DateTime column drops tzinfo) — normalizing both sides keeps the hash stable."""
    tsx = None
    if ts is not None:
        tsx = (ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts).isoformat()
    return json.dumps({"actor": actor_username, "actor_type": actor_type, "action": action,
                       "resource_type": resource_type, "resource_id": resource_id,
                       "org_id": org_id, "detail": detail, "ts": tsx},
                      sort_keys=True, separators=(",", ":"))


def audit(db: Session, action: str, actor=None, actor_type="user", resource_type=None,
          resource_id=None, ip=None, request_id=None, detail=None, org_id=None, commit=True):
    """Write a tamper-evident audit event. Never log secrets, tokens, or full payout destinations.

    `actor` may be a User (its id + username are captured) or a plain username string. `org_id`
    scopes the event to a team so an org admin can read its own trail. Each row is hash-chained to
    the previous one (content_hash of its own fields + chain_hash = sha256(prev.chain_hash +
    content_hash)), so a later edit or deletion is detectable by verify_audit_chain(). Chaining is
    best-effort — a failure to read the previous hash never blocks the action being audited."""
    actor_username = getattr(actor, "username", None)
    if actor_username is None and isinstance(actor, str):
        actor_username = actor
    det = json.dumps(detail) if isinstance(detail, dict) else detail
    rid = str(resource_id) if resource_id is not None else None
    ts = _utcnow()
    ev = AuditEvent(
        actor_user_id=getattr(actor, "id", None),
        actor_username=actor_username,
        actor_type=actor_type, action=action,
        resource_type=resource_type, resource_id=rid,
        ip_address=ip, request_id=request_id, detail=det, org_id=org_id, created_at=ts)
    try:
        prev = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
        prev_chain = (prev.chain_hash if prev and prev.chain_hash else "")
        content = _audit_content(actor_username, actor_type, action, resource_type, rid,
                                 org_id, det, ts)
        ev.content_hash = hashlib.sha256(content.encode()).hexdigest()
        ev.chain_hash = hashlib.sha256((prev_chain + ev.content_hash).encode()).hexdigest()
    except Exception:  # noqa: BLE001 — chaining is best-effort; never block the audited action
        pass
    db.add(ev)
    if commit:
        db.commit()
    return ev


def _audit_row(e: "AuditEvent") -> dict:
    det = e.detail
    if det and isinstance(det, str) and det.strip().startswith("{"):
        try:
            det = json.loads(det)
        except Exception:  # noqa: BLE001
            pass
    return {"id": e.id, "at": e.created_at.isoformat() if e.created_at else None,
            "actor": e.actor_username, "actor_type": e.actor_type, "action": e.action,
            "resource": (f"{e.resource_type}:{e.resource_id}" if e.resource_type else e.resource_id),
            "org_id": e.org_id, "ip": e.ip_address, "detail": det,
            "content_hash": e.content_hash}


def list_audit_for_actor(db: Session, user_id: int, limit: int = 100):
    """Audit events performed BY this user — their own "who did what" trail."""
    rows = (db.query(AuditEvent).filter(AuditEvent.actor_user_id == user_id)
            .order_by(AuditEvent.id.desc()).limit(limit).all())
    return [_audit_row(e) for e in rows]


def list_audit_for_org(db: Session, org_id: int, limit: int = 200):
    """Every audit event scoped to a team (member changes, deposits, spend) — for org admins."""
    rows = (db.query(AuditEvent).filter(AuditEvent.org_id == org_id)
            .order_by(AuditEvent.id.desc()).limit(limit).all())
    return [_audit_row(e) for e in rows]


def verify_audit_chain(db: Session, limit: int = 10000) -> dict:
    """Recompute the hash chain over the most recent rows (ascending id) and report the first break
    — a break means a row was edited or deleted after the fact. Rows written before chaining existed
    (content_hash NULL) are skipped but still carry the chain forward, mirroring audit()'s logic."""
    recent = db.query(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).all()
    rows = recent[::-1]
    prev_chain = ""
    if rows:
        before = (db.query(AuditEvent).filter(AuditEvent.id < rows[0].id)
                  .order_by(AuditEvent.id.desc()).first())
        prev_chain = (before.chain_hash or "") if before else ""
    broken = None
    checked = 0
    for e in rows:
        if not e.content_hash:                        # legacy row — not chained, not verifiable
            prev_chain = e.chain_hash or ""
            continue
        content = _audit_content(e.actor_username, e.actor_type, e.action, e.resource_type,
                                 e.resource_id, e.org_id, e.detail, e.created_at)
        ch = hashlib.sha256(content.encode()).hexdigest()
        expect = hashlib.sha256((prev_chain + ch).encode()).hexdigest()
        if ch != e.content_hash or expect != e.chain_hash:
            broken = e.id
            break
        checked += 1
        prev_chain = e.chain_hash
    return {"checked": checked, "intact": broken is None, "first_broken_id": broken}


class BookingsPaused(Exception):
    """Raised when the kill switch is on. New bookings refused; running ones untouched."""


def bookings_are_paused(db: Session):
    """(paused, reason). The kill switch."""
    p = db.query(Platform).first()
    if p and p.bookings_paused:
        return True, (p.pause_reason or "Bookings are temporarily paused.")
    return False, None


def set_bookings_paused(db: Session, paused: bool, reason: str = None, actor=None):
    p = db.query(Platform).first()
    if not p:
        p = Platform(revenue=Decimal(0))
        db.add(p)
        db.flush()
    p.bookings_paused = bool(paused)
    p.pause_reason = reason if paused else None
    p.paused_at = _utcnow() if paused else None
    db.add(p)
    audit(db, "platform.bookings_paused" if paused else "platform.bookings_resumed",
          actor=actor, actor_type="admin", detail={"reason": reason}, commit=False)
    db.commit()
    return p


class AttestationChallenge(Base):
    """Server-issued nonce a TEE report must include (prevents replay)."""
    __tablename__ = "attestation_challenges"
    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    nonce = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


class ReputationEvent(Base):
    """Append-only signal log per spec/owner — the auditable basis for the score."""
    __tablename__ = "reputation_events"
    id = Column(Integer, primary_key=True, index=True)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)  # completed|failed|fraud|benchmark|latency|uptime
    value = Column(Float, default=0.0)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class RoutingDecision(Base):
    """Why THIS node — recorded at decision time, append-only.

    Every automated placement (/solve, /launch) writes one row with the full set of
    eligible candidates, the factor scores, and the selection, so any booking can
    answer "why did the platform pick this machine?" months later. It is the audit
    trail a buyer or reviewer asks for, and the raw history a smarter pricing/routing
    model needs. Rows are never updated except to link the resulting booking."""
    __tablename__ = "routing_decisions"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False)                # solve | launch
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=True)
    intent = Column(Text, nullable=False)                  # JSON: constraints as requested
    candidates = Column(Text, nullable=False)              # JSON: every eligible node + factors
    selected_spec_ids = Column(Text, nullable=False)       # JSON list of chosen spec ids
    explanation = Column(Text, nullable=False)             # the sentence shown to the buyer
    fulfilled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


def record_routing_decision(db: Session, source: str, user_id, intent: dict,
                            candidates: list, selected_spec_ids: list,
                            explanation: str, fulfilled: bool = True,
                            booking_id: int = None) -> "RoutingDecision":
    """Persist one placement decision. JSON-serialises Decimals safely."""
    rd = RoutingDecision(
        source=source, user_id=user_id, booking_id=booking_id,
        intent=json.dumps(intent, default=_json_money),
        candidates=json.dumps(candidates, default=_json_money),
        selected_spec_ids=json.dumps(selected_spec_ids),
        explanation=explanation, fulfilled=fulfilled)
    db.add(rd)
    db.commit()
    db.refresh(rd)
    return rd


class MultiNodeJob(Base):
    """A multi-node job assembled from N parts.

    Two shapes share this table:
      * FAN-OUT (kind=render|transcode): N independent segments + a stitch step. Segments never
        talk to each other; a dropped one just re-runs.
      * DISTRIBUTED (kind=distributed): N ranks that form ONE cluster and communicate over the VPN
        (e.g. torchrun/NCCL all-reduce). rank 0 is the rendezvous master; its VPN-reachable
        address is stored here and handed to the other ranks so they can join. No stitch step —
        the job completes when every rank finishes, and fails if any rank dies (gang semantics)."""
    __tablename__ = "multinode_jobs"
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)              # render|transcode|distributed
    params = Column(Text, nullable=True)
    total_segments = Column(Integer, default=0)        # = world_size for a distributed job
    status = Column(String, default="running")         # running|assembling|complete|failed
    output_ref = Column(String, nullable=True)
    stitch_task_id = Column(Integer, nullable=True)
    # --- distributed-cluster coordination (null for fan-out jobs) ---
    backend = Column(String, nullable=True)            # nccl|gloo — the collective backend
    master_addr = Column(String, nullable=True)        # rank-0's VPN-reachable host (rendezvous)
    master_port = Column(Integer, nullable=True)       # rank-0's rendezvous port
    rendezvous_at = Column(DateTime, nullable=True)    # when rank 0 registered the address
    created_at = Column(DateTime, default=_utcnow)


class JobSegment(Base):
    __tablename__ = "job_segments"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("multinode_jobs.id"), index=True, nullable=False)
    idx = Column(Integer, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=True)
    range_start = Column(Float, nullable=True)         # frame or second
    range_end = Column(Float, nullable=True)
    output_ref = Column(String, nullable=True)
    status = Column(String, default="pending")         # pending|done
    # For DISTRIBUTED clusters: this rank's VPN-reachable address, so the whole cluster can be
    # exported as an MPI hostfile / Ray address / torchrun rdzv endpoint (null for fan-out).
    peer_host = Column(String, nullable=True)
    peer_port = Column(Integer, nullable=True)
    slots = Column(Integer, nullable=True)             # GPUs this rank contributes (mpirun slots)


class Checkpoint(Base):
    """A backup of a task's data volume, stored in object storage. The API holds
    only the reference + integrity hash — the bytes go node -> S3 directly."""
    __tablename__ = "checkpoints"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    snapshot_ref = Column(String, nullable=False)   # e.g. s3://bucket/key
    size_bytes = Column(Integer, default=0)
    content_hash = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class DatabaseBackup(Base):
    """A disaster-recovery backup of the PLATFORM database (not a buyer's job volume — that's
    Checkpoint). One row per backup attempt: where the encrypted dump lives in object storage,
    its size + SHA-256 (integrity), which engine produced it, and whether it succeeded. The
    bytes live in S3; the DB holds only the reference + hash so a backup can be verified and
    restored. See backup.py + docs/BACKUP_RUNBOOK.md."""
    __tablename__ = "database_backups"
    id = Column(Integer, primary_key=True, index=True)
    s3_key = Column(String, nullable=False)                 # key within the bucket
    s3_uri = Column(String, nullable=True)                  # s3://bucket/key
    engine = Column(String, nullable=False)                 # postgresql | sqlite
    environment = Column(String, nullable=True)             # development|staging|production
    size_bytes = Column(Integer, default=0)                 # compressed size
    sha256 = Column(String, nullable=True)                  # of the compressed object (integrity)
    status = Column(String, default="ok", index=True)       # ok | failed
    error = Column(Text, nullable=True)                     # populated when status=failed
    created_at = Column(DateTime, default=_utcnow, index=True)


def record_database_backup(db: Session, *, s3_key, s3_uri, engine, environment,
                           size_bytes, sha256, status="ok", error=None) -> "DatabaseBackup":
    row = DatabaseBackup(s3_key=s3_key, s3_uri=s3_uri, engine=engine, environment=environment,
                         size_bytes=int(size_bytes or 0), sha256=sha256, status=status,
                         error=(str(error)[:2000] if error else None))
    db.add(row); db.commit(); db.refresh(row)
    return row


def list_database_backups(db: Session, limit: int = 50, status: str = None) -> list:
    q = db.query(DatabaseBackup)
    if status:
        q = q.filter(DatabaseBackup.status == status)
    return q.order_by(DatabaseBackup.created_at.desc(), DatabaseBackup.id.desc()).limit(limit).all()


def latest_database_backup(db: Session, status: str = "ok") -> "DatabaseBackup":
    return (db.query(DatabaseBackup).filter(DatabaseBackup.status == status)
            .order_by(DatabaseBackup.created_at.desc(), DatabaseBackup.id.desc()).first())


def prune_database_backups(db: Session, keep: int) -> list:
    """Delete the DB rows for successful backups beyond the newest `keep`, returning the list of
    (id, s3_key) removed so the caller can delete the objects. Failed rows are never counted
    toward retention (they hold no restorable object) but are pruned alongside old ones."""
    if keep is None or keep < 0:
        return []
    ok = (db.query(DatabaseBackup).filter(DatabaseBackup.status == "ok")
          .order_by(DatabaseBackup.created_at.desc(), DatabaseBackup.id.desc()).all())
    removed = []
    for row in ok[keep:]:
        removed.append((row.id, row.s3_key))
        db.delete(row)
    if removed:
        db.commit()
    return removed


class Notification(Base):
    """Audit log of every notification we attempted to send."""
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    channel = Column(String, default="email")
    event_type = Column(String, index=True, nullable=False)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String, default="queued")   # queued|sent|failed|skipped
    created_at = Column(DateTime, default=_utcnow)


class TaskLog(Base):
    __tablename__ = "task_logs"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    line = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class IdleSettlement(Base):
    """Idempotent record of NiceHash earnings credited per worker per period."""
    __tablename__ = "idle_settlements"
    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String, index=True, nullable=False)
    period = Column(String, nullable=False)
    spec_id = Column(Integer, nullable=True)
    gross_usd = Column(Money, default=Decimal(0))
    credited_usd = Column(Money, default=Decimal(0))
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("worker_id", "period", name="uq_idle_settle"),)


class DiskSettlement(Base):
    """Idempotent record of storage-network earnings credited per node per period.
    Mirrors IdleSettlement: one row per (node_id, period); node_id is `pbdisk-<spec_id>`."""
    __tablename__ = "disk_settlements"
    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(String, index=True, nullable=False)
    period = Column(String, nullable=False)
    spec_id = Column(Integer, nullable=True)
    provider = Column(String, nullable=True)
    gross_usd = Column(Money, default=Decimal(0))
    credited_usd = Column(Money, default=Decimal(0))
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("node_id", "period", name="uq_disk_settle"),)


class DemoRequest(Base):
    """A person asked to see the product or get access.

    This is the single most valuable thing a pre-revenue marketplace can collect:
    evidence of demand, with a name attached. Each row is a real human who wanted
    a walkthrough — exactly what an investor is asking to see. We never fabricate
    these; they only exist because someone filled in the form."""
    __tablename__ = "demo_requests"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True)     # opaque handle for URLs
    name = Column(String, nullable=False)
    email = Column(String, index=True, nullable=False)
    organization = Column(String, nullable=True)
    role = Column(String, nullable=True)                    # buyer | host | investor | other
    workload = Column(Text, nullable=True)                  # what they want to run
    message = Column(Text, nullable=True)
    preferred_time = Column(String, nullable=True)          # free text, their words
    source = Column(String, nullable=True)                  # which page/CTA
    status = Column(String, default="new", index=True)      # new|contacted|scheduled|done|declined
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class ProcessedWebhook(Base):
    """Idempotency for payment webhooks — an event is credited at most once."""
    __tablename__ = "processed_webhooks"
    event_id = Column(String, primary_key=True, index=True)
    processed_at = Column(DateTime, default=_utcnow)


class IssuedKey(Base):
    """Tracks issued API keys so the UI can list/revoke them (secret not stored)."""
    __tablename__ = "issued_keys"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    jti = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=True)
    scopes = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)


class RevokedApiKey(Base):
    __tablename__ = "revoked_api_keys"
    jti = Column(String, primary_key=True, index=True)
    revoked_at = Column(DateTime, default=_utcnow)
    # The revoked token's own expiry, when the revoker knows it (session-JWT logout does).
    # Once past, the token is dead with or without this row, so maintenance can prune it —
    # otherwise the denylist (checked on EVERY authenticated request) grows forever.
    # NULL = unknown lifetime (e.g. an API key revoked by jti alone): kept indefinitely.
    expires_at = Column(DateTime, nullable=True)


class NodeInstallToken(Base):
    """A short, URL-safe enrollment token for the one-line installer.

    `curl <server>/i/<token> | bash` (or `irm <server>/i/<token>.ps1 | iex`) fetches an
    installer with a FRESHLY-minted, node-scoped API key baked in — so a machine onboards
    with no interactive input and nothing to hand-edit. Each fetch mints its own worker key,
    so the same token can enrol a whole rig farm, each machine independently revocable. The
    token is a bearer capability: it only enrols NODES for one seller (it cannot log in, spend,
    or withdraw) and it expires. Bound to a seller; carries an optional pinned price (null =>
    the node auto-prices from its GPU benchmark)."""
    __tablename__ = "install_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    price = Column(Money, nullable=True)             # pinned USD/hr, or null to auto-price
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=False)


INSTALL_TOKEN_TTL_DAYS = 30   # enrollment tokens are bearer capabilities — bound + expiring


def create_install_token(db: Session, user: "User", price=None,
                         ttl_days: int = INSTALL_TOKEN_TTL_DAYS) -> "NodeInstallToken":
    """Mint an enrollment token bound to `user`. `price` (optional) pins the listing rate;
    None lets the node auto-price from its benchmark."""
    tok = secrets.token_urlsafe(9)                   # ~12 url-safe chars, unguessable
    row = NodeInstallToken(
        token=tok, user_id=user.id,
        price=(Decimal(str(price)) if price is not None else None),
        expires_at=_utcnow() + timedelta(days=int(ttl_days)))
    db.add(row); db.commit(); db.refresh(row)
    return row


def resolve_install_token(db: Session, token: str) -> "NodeInstallToken | None":
    """Return the token row if it exists and has not expired, else None (fail-closed)."""
    if not token:
        return None
    row = db.query(NodeInstallToken).filter(NodeInstallToken.token == token).first()
    if row is None:
        return None
    exp = row.expires_at
    if exp is not None and getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and exp < _utcnow():
        return None
    return row


# ------------------ Paid data API: metering + price-history snapshots ------------------

class ApiUsage(Base):
    """Per-account metered usage of the data API, one row per calendar month. Every data call is
    counted; calls beyond the free monthly quota are billed pay-as-you-go against the wallet
    balance and tallied here (amount_usd)."""
    __tablename__ = "api_usage"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    period = Column(String, index=True, nullable=False)          # 'YYYY-MM'
    calls = Column(Integer, default=0, nullable=False)
    billed_calls = Column(Integer, default=0, nullable=False)
    amount_usd = Column(Money, default=Decimal(0), nullable=False)
    updated_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_api_usage_user_period"),)


class PriceSnapshot(Base):
    """A timestamped point in the GPU price index — the raw material the data API sells as history.
    Written periodically by the maintenance loop; one row per GPU model per capture."""
    __tablename__ = "price_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    captured_at = Column(DateTime, default=_utcnow, index=True, nullable=False)
    gpu_model = Column(String, index=True, nullable=False)
    reference_price = Column(Money, nullable=True)   # benchmark-anchored reference $/hr
    avg_price = Column(Money, nullable=True)         # mean of live listings (null if none online)
    min_price = Column(Money, nullable=True)
    max_price = Column(Money, nullable=True)
    live_count = Column(Integer, default=0, nullable=False)


def _period(now=None) -> str:
    return (now or _utcnow()).strftime("%Y-%m")


def charge_wallet(db: Session, user_id: int, amount, *, reference_type: str,
                  description: str = None) -> bool:
    """Atomically debit the user's WALLET BALANCE and book the charge to platform revenue.
    Returns False (no charge) if the balance is insufficient. Balanced double-entry."""
    amt = q(amount)
    if amt <= 0:
        return True
    if not try_debit(db, user_id, amt):          # atomic, no overspend
        return False
    post(db, reference_type, legs=[
        (acct_buyer(user_id), DEBIT,  amt, user_id),
        (PLATFORM_REVENUE,    CREDIT, amt),
    ], reference_id=user_id, description=description or reference_type, entry_type=reference_type)
    # Keep the Platform.revenue scalar in lockstep with the PLATFORM_REVENUE ledger account,
    # exactly like the booking-settlement paths — otherwise every metered charge (data API,
    # inference) would break the "platform revenue == ledger" reconciliation invariant.
    # Atomic increment: two concurrent metered charges must both land (no stale RMW).
    if not db.execute(update(Platform).values(revenue=Platform.revenue + amt)).rowcount:
        plat = db.query(Platform).first()          # first-ever charge: bootstrap the singleton
        if plat is None:
            db.add(Platform(revenue=amt))
        else:
            plat.revenue = q(D(plat.revenue) + amt)
    db.commit()
    return True


def meter_data_call(db: Session, user_id: int, *, free_quota: int, price_per_call, units=1) -> dict:
    """Count one data-API call for this user and bill it if it's past the free monthly TRIAL quota.

    `units` is the endpoint's price weight (commodity=1, premium>1): the charge is
    price_per_call * units, and each call consumes `units` of the free trial (so premium calls
    burn the trial faster). A billable call is served only if the wallet balance covers the charge;
    otherwise it is NOT counted and the caller gets ``{"ok": False, "reason": "insufficient_balance"}``
    (surface as HTTP 402). Pricing 0 keeps the API free."""
    units = max(1, int(units))
    period = _period()
    row = (db.query(ApiUsage)
           .filter(ApiUsage.user_id == user_id, ApiUsage.period == period).first())
    if row is None:
        row = ApiUsage(user_id=user_id, period=period, calls=0, billed_calls=0,
                       amount_usd=Decimal(0))
        db.add(row); db.flush()
    charge = q(D(str(price_per_call)) * units)
    within_free = row.calls < int(free_quota)     # trial measured in call-units already consumed
    if within_free or charge <= 0:
        row.calls += units
        row.updated_at = _utcnow()
        db.commit()
        return {"ok": True, "billed": False, "period": period, "calls": row.calls, "units": units,
                "free_quota": int(free_quota),
                "free_remaining": max(0, int(free_quota) - row.calls)}
    # past the free trial and pricing is on -> must pay
    if not charge_wallet(db, user_id, charge, reference_type="data_api",
                         description="data API usage"):
        return {"ok": False, "reason": "insufficient_balance",
                "price_per_call": float(charge), "period": period}
    row.calls += units
    row.billed_calls += 1
    row.amount_usd = q(D(row.amount_usd) + charge)
    row.updated_at = _utcnow()
    db.commit()
    return {"ok": True, "billed": True, "charged": float(charge), "units": units, "period": period,
            "calls": row.calls, "billed_calls": row.billed_calls,
            "amount_usd": float(row.amount_usd), "free_quota": int(free_quota),
            "free_remaining": 0}


def data_api_revenue(db: Session) -> dict:
    """Data-API monetization scoreboard: billed calls + revenue this month and all-time.
    Revenue is read from the ledger (PLATFORM_REVENUE credits tagged 'data_api') — the books."""
    period = _period()
    month = db.query(ApiUsage).filter(ApiUsage.period == period).all()
    allrows = db.query(ApiUsage).all()
    rev_total = q(sum((D(e.amount) for e in db.query(LedgerEntry)
                       .filter(LedgerEntry.entry_type == "data_api",
                               LedgerEntry.direction == CREDIT,
                               LedgerEntry.account == PLATFORM_REVENUE).all()), Decimal(0)))
    return {
        "period": period,
        "revenue_usd_month": float(q(sum((D(r.amount_usd) for r in month), Decimal(0)))),
        "revenue_usd_total": float(rev_total),
        "billed_calls_month": sum(int(r.billed_calls or 0) for r in month),
        "billed_calls_total": sum(int(r.billed_calls or 0) for r in allrows),
        "calls_month": sum(int(r.calls or 0) for r in month),
        "paying_accounts_month": sum(1 for r in month if (r.billed_calls or 0) > 0),
    }


def meter_tokens(db: Session, user_id: int, *, prompt_tokens: int, completion_tokens: int,
                 price_in_per_mtok, price_out_per_mtok) -> dict:
    """Bill ONE inference request by token count against the wallet, reusing the monthly
    ApiUsage row + charge_wallet, and tagging revenue ``entry_type='inference'`` in the ledger.

    Charge = prompt_tokens/1e6 * price_in + completion_tokens/1e6 * price_out (USD). Pricing 0
    keeps it free. The caller MUST pre-check the balance against an upper-bound estimate before
    running the model (the work is already done by the time we get here), so a False result is
    only the rare concurrent-spend race — surface it as billed:false, not a hard failure."""
    period = _period()
    row = (db.query(ApiUsage)
           .filter(ApiUsage.user_id == user_id, ApiUsage.period == period).first())
    if row is None:
        row = ApiUsage(user_id=user_id, period=period, calls=0, billed_calls=0,
                       amount_usd=Decimal(0))
        db.add(row)
        try:
            db.flush()
        except IntegrityError:      # concurrent first call of the month (uq_api_usage_user_period)
            db.rollback()
            row = (db.query(ApiUsage)
                   .filter(ApiUsage.user_id == user_id, ApiUsage.period == period).one())
    p = max(0, int(prompt_tokens or 0)); c = max(0, int(completion_tokens or 0))
    total = p + c
    charge = q((D(p) * D(str(price_in_per_mtok)) + D(c) * D(str(price_out_per_mtok)))
               / Decimal(1_000_000))
    row.calls += 1
    if charge <= 0:
        row.updated_at = _utcnow(); db.commit()
        return {"ok": True, "billed": False, "charged": 0.0, "tokens": total,
                "prompt_tokens": p, "completion_tokens": c, "period": period}
    if not charge_wallet(db, user_id, charge, reference_type="inference",
                         description=f"inference {total} tokens"):
        db.commit()
        return {"ok": False, "reason": "insufficient_balance", "charge": float(charge),
                "tokens": total, "prompt_tokens": p, "completion_tokens": c, "period": period}
    row.billed_calls += 1
    row.amount_usd = q(D(row.amount_usd) + charge)
    row.updated_at = _utcnow(); db.commit()
    return {"ok": True, "billed": True, "charged": float(charge), "tokens": total,
            "prompt_tokens": p, "completion_tokens": c, "period": period}


def usage_summary(db: Session, user_id: int, *, free_quota: int) -> dict:
    """The caller's data-API usage this month (free to check — not itself billed)."""
    period = _period()
    row = (db.query(ApiUsage)
           .filter(ApiUsage.user_id == user_id, ApiUsage.period == period).first())
    calls = row.calls if row else 0
    return {"period": period, "calls": calls,
            "billed_calls": (row.billed_calls if row else 0),
            "amount_usd": float(row.amount_usd) if row else 0.0,
            "free_quota": int(free_quota),
            "free_remaining": max(0, int(free_quota) - calls)}


def _live_price_index(db: Session):
    """Current index: for each recognised GPU, its benchmark reference price and the live
    marketplace stats (avg/min/max/count). Shared by the snapshot job and the data endpoint."""
    import pricing_engine
    import gpu_benchmark
    live = {}
    for s in db.query(SellerSpec).all():
        if not spec_is_live(s):
            continue
        key = gpu_benchmark.normalize_model(s.gpu_model)
        if key is None:
            continue
        live.setdefault(key, []).append(float(s.price_per_hour or 0))
    rows = []
    for r in pricing_engine.catalog():
        ls = live.get(r["gpu_model"], [])
        rows.append({
            "gpu_model": r["gpu_model"],
            "benchmark_tflops_fp16": r.get("benchmark_tflops_fp16"),
            "reference_price": r.get("reference_price_per_hour"),
            "avg_price": (round(sum(ls) / len(ls), 2) if ls else None),
            "min_price": (round(min(ls), 2) if ls else None),
            "max_price": (round(max(ls), 2) if ls else None),
            "live_count": len(ls),
        })
    return rows


def record_price_snapshot(db: Session) -> int:
    """Write one PriceSnapshot row per GPU model at the current index. Returns rows written."""
    n = 0
    for r in _live_price_index(db):
        db.add(PriceSnapshot(
            gpu_model=r["gpu_model"],
            reference_price=(q(r["reference_price"]) if r["reference_price"] is not None else None),
            avg_price=(q(r["avg_price"]) if r["avg_price"] is not None else None),
            min_price=(q(r["min_price"]) if r["min_price"] is not None else None),
            max_price=(q(r["max_price"]) if r["max_price"] is not None else None),
            live_count=r["live_count"]))
        n += 1
    db.commit()
    return n


def price_history(db: Session, *, gpu_model: str = None, since=None, limit: int = 5000):
    """Historical price-index points, newest first. Optional GPU filter + `since` datetime."""
    q_ = db.query(PriceSnapshot)
    if gpu_model:
        import gpu_benchmark
        key = gpu_benchmark.normalize_model(gpu_model) or gpu_model
        q_ = q_.filter(PriceSnapshot.gpu_model == key)
    if since is not None:
        q_ = q_.filter(PriceSnapshot.captured_at >= since)
    return q_.order_by(PriceSnapshot.captured_at.desc()).limit(int(limit)).all()


class WGPeer(Base):
    __tablename__ = "wg_peers"
    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    public_key = Column(String, unique=True, nullable=False)
    address = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    id = Column(Integer, primary_key=True)
    key = Column(String, nullable=False)
    username = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False, default=0)  # 0 = in-progress
    response = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("key", "username", "endpoint", name="uq_idempotency"),
    )


# ======================================================================
# Stripe Connect marketplace payments.
#
# These layer REAL money (Stripe test/live) on top of the existing booking + job +
# ledger primitives — they do not fork them. A ComputeTransaction wraps a Booking and
# drives it through a PaymentIntent (manual capture) -> Transfer to the seller's
# connected account, recording every money movement in the SAME double-entry ledger
# (post()/LedgerEntry). Amounts here are INTEGER MINOR UNITS (e.g. cents), never float.
# ======================================================================

class ConnectedAccount(Base):
    """A seller's Stripe Connect account + its cached readiness. Synced from Stripe
    via account.updated and on-demand retrieve; never trusted from a return URL."""
    __tablename__ = "connected_accounts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    stripe_account_id = Column(String, unique=True, index=True, nullable=False)
    country = Column(String, nullable=True)
    default_currency = Column(String, nullable=True)
    onboarding_state = Column(String, default="created", nullable=False)  # created|onboarding|verifying|enabled|restricted|disabled
    details_submitted = Column(Boolean, default=False, nullable=False)
    charges_enabled = Column(Boolean, default=False, nullable=False)
    payouts_enabled = Column(Boolean, default=False, nullable=False)
    transfers_capability = Column(String, default="inactive")   # active|inactive|pending
    card_payments_capability = Column(String, default="inactive")
    requirements_due = Column(Text, nullable=True)              # JSON list
    requirements_past_due = Column(Text, nullable=True)         # JSON list
    disabled_reason = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    # Which Stripe gateway minted this account: 'real' (Stripe API) or 'fake' (offline
    # FakeStripeGateway). A fake account (acct_fake…) must NEVER be reused once the process
    # switches to the real gateway, or the real Stripe Connect account is never created. Nullable
    # for legacy rows; the account-id prefix ('acct_fake') is the fallback classifier.
    gateway_mode = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    def payout_ready(self) -> bool:
        """A seller may take paid jobs only when Stripe can charge on the platform
        AND transfer to this account. details_submitted alone is NOT enough."""
        return bool(self.charges_enabled and self.payouts_enabled
                    and self.transfers_capability == "active")


class ComputeTransaction(Base):
    """The authoritative money+lifecycle object for one paid compute job. Amounts are
    integer minor units in `currency`. A frozen pricing snapshot means later price or
    config changes never rewrite this transaction's history."""
    __tablename__ = "compute_transactions"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, default=lambda: "ctx_" + _rand_vm_id())
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    spec_id = Column(Integer, ForeignKey("specs.id"), index=True, nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=True)
    currency = Column(String, nullable=False, default="usd")
    pricing_snapshot = Column(Text, nullable=False)             # frozen JSON, immutable
    # integer minor units
    estimated_amount = Column(Integer, nullable=False, default=0)
    authorization_amount = Column(Integer, nullable=False, default=0)
    captured_amount = Column(Integer, nullable=False, default=0)
    platform_fee_amount = Column(Integer, nullable=False, default=0)
    seller_net_amount = Column(Integer, nullable=False, default=0)
    stripe_fee_amount = Column(Integer, nullable=False, default=0)
    refunded_amount = Column(Integer, nullable=False, default=0)
    transferred_amount = Column(Integer, nullable=False, default=0)
    reversed_amount = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="DRAFT", index=True)
    reconciliation_status = Column(String, nullable=False, default="pending", index=True)
    # Stripe identifiers
    stripe_payment_intent_id = Column(String, unique=True, index=True, nullable=True)
    stripe_charge_id = Column(String, index=True, nullable=True)
    stripe_transfer_id = Column(String, index=True, nullable=True)
    stripe_connected_account_id = Column(String, index=True, nullable=True)
    settlement_version = Column(Integer, nullable=False, default=0)
    metering_seconds = Column(Integer, nullable=True)
    metering_source = Column(String, nullable=True)
    failure_reason = Column(String, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False, index=True)
    # TEST vs LIVE money, stamped at creation and IMMUTABLE thereafter (see the
    # before_update guard). Test and live records must never mix or be summed together.
    mode = Column(String, nullable=False, default=payments_mode, index=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (
        CheckConstraint("captured_amount >= 0 AND authorization_amount >= 0 "
                        "AND platform_fee_amount >= 0 AND seller_net_amount >= 0 "
                        "AND refunded_amount >= 0 AND transferred_amount >= 0",
                        name="ck_ctx_nonneg"),
    )


class ComputeTxEvent(Base):
    """Append-only state-transition history for a ComputeTransaction (admin audit)."""
    __tablename__ = "compute_tx_events"
    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, ForeignKey("compute_transactions.id"), index=True, nullable=False)
    from_state = Column(String, nullable=True)
    to_state = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    actor = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


class PaymentOperation(Base):
    """One idempotent money-moving operation against Stripe. Persisted BEFORE the
    Stripe call so an uncertain network response is reconciled by retrieval, never by
    blindly repeating the mutation."""
    __tablename__ = "payment_operations"
    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, ForeignKey("compute_transactions.id"), index=True, nullable=False)
    op_type = Column(String, nullable=False)                    # authorize|capture|transfer|refund|reversal|cancel
    internal_idempotency_key = Column(String, unique=True, index=True, nullable=False)
    stripe_idempotency_key = Column(String, nullable=True)
    request_fingerprint = Column(String, nullable=True)
    external_object_id = Column(String, index=True, nullable=True)
    state = Column(String, nullable=False, default="pending")   # pending|succeeded|failed
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class StripeWebhookEvent(Base):
    """Every Stripe event we receive, processed at most once (generalizes the older
    ProcessedWebhook, which stays for the legacy sandbox webhook)."""
    __tablename__ = "stripe_webhook_events"
    stripe_event_id = Column(String, primary_key=True, index=True)
    event_type = Column(String, index=True, nullable=False)
    account_context = Column(String, nullable=True)             # connected account id, if any
    api_version = Column(String, nullable=True)
    processing_state = Column(String, nullable=False, default="received")  # received|processed|failed
    attempt_count = Column(Integer, nullable=False, default=0)
    received_at = Column(DateTime, default=_utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)
    error = Column(String, nullable=True)


class Settlement(Base):
    """Immutable, versioned settlement math for a transaction. A new version is written
    (never edited) when a refund/reversal changes the picture."""
    __tablename__ = "settlements"
    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, ForeignKey("compute_transactions.id"), index=True, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    captured_amount = Column(Integer, nullable=False, default=0)
    seller_amount = Column(Integer, nullable=False, default=0)
    platform_fee = Column(Integer, nullable=False, default=0)
    stripe_fee = Column(Integer, nullable=False, default=0)
    refund_amount = Column(Integer, nullable=False, default=0)
    transfer_amount = Column(Integer, nullable=False, default=0)
    transfer_reversal_amount = Column(Integer, nullable=False, default=0)
    currency = Column(String, nullable=False, default="usd")
    finalized_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (
        UniqueConstraint("tx_id", "version", name="uq_settlement_version"),
    )


# --- Stripe-Connect ledger account names (reuse the double-entry post()) ---
def acct_stripe_receivable():   return "stripe:receivable"      # captured, held on platform
def acct_seller_payable(uid):   return f"seller_payable:{uid}"  # owed to seller (net)
def acct_stripe_fees():         return "stripe:fees"            # processing fees (platform cost)
def acct_stripe_payouts():      return "external:stripe_transfers"  # money sent to connected accts


# ======================================================================
# Provider-neutral global payout layer.
#
# Job settlement produces an immutable PayoutObligation (what Petabyte owes a seller);
# a separate routing/aggregation layer selects a rail and creates a PayoutBatch that
# may cover many obligations. The obligation NEVER changes because the rail changes,
# and one obligation can never be paid by two batches (guarded). Amounts are integer
# minor units.
# ======================================================================

class PayoutObligation(Base):
    """Immutable record of net earnings Petabyte owes a seller for settled compute.
    Created at settlement; provider-neutral; survives provider changes/failures."""
    __tablename__ = "payout_obligations"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, default=lambda: "obl_" + _rand_vm_id())
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    compute_tx_id = Column(Integer, ForeignKey("compute_transactions.id"), index=True, nullable=True)
    currency = Column(String, nullable=False, default="usd")
    gross_amount_minor = Column(Integer, nullable=False, default=0)     # seller gross (== compute seller_net)
    commission_minor = Column(Integer, nullable=False, default=0)       # platform commission (already taken upstream)
    adjustments_minor = Column(Integer, nullable=False, default=0)
    withholding_minor = Column(Integer, nullable=False, default=0)
    net_amount_minor = Column(Integer, nullable=False, default=0)       # what a batch will pay
    country = Column(String, nullable=True)
    available_at = Column(DateTime, nullable=True)                      # after the risk hold
    risk_hold_until = Column(DateTime, nullable=True)
    compliance_status = Column(String, nullable=False, default="NOT_STARTED")
    state = Column(String, nullable=False, default="accrued", index=True)  # accrued|available|batched|paid|reversed|failed
    batch_id = Column(Integer, ForeignKey("payout_batches.id"), index=True, nullable=True)
    pricing_snapshot = Column(Text, nullable=True)
    is_demo = Column(Boolean, default=False, nullable=False)
    mode = Column(String, nullable=False, default=payments_mode, index=True)  # TEST|LIVE, immutable
    created_at = Column(DateTime, default=_utcnow, index=True)
    __table_args__ = (
        CheckConstraint("net_amount_minor >= 0 AND gross_amount_minor >= 0",
                        name="ck_obligation_nonneg"),
        # One settlement -> at most one obligation. The SELECT-then-INSERT in
        # create_payout_obligation races under concurrent settlement workers; this DB
        # constraint is the real guarantee. NULL compute_tx_id (standalone/manual
        # obligations) is exempt — SQL treats NULLs as distinct.
        UniqueConstraint("compute_tx_id", name="uq_obligation_compute_tx"),
    )


class PayoutBatch(Base):
    """One external payout that may cover MANY obligations (small-payment aggregation).
    Bound to exactly one rail + idempotency key."""
    __tablename__ = "payout_batches"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, default=lambda: "pob_" + _rand_vm_id())
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    rail_type = Column(String, nullable=False)
    provider = Column(String, nullable=True)
    source_currency = Column(String, nullable=False, default="usd")
    destination_currency = Column(String, nullable=True)
    total_amount_minor = Column(Integer, nullable=False, default=0)
    provider_fee_minor = Column(Integer, nullable=False, default=0)
    fx_rate = Column(Numeric(20, 8), nullable=True)   # exact rate; never binary float (money rule)
    external_id = Column(String, index=True, nullable=True)
    # created|sent|paid|failed|aborted|reversed|needs_reconciliation.
    # TERMINAL (obligations released, never an idempotent replay): failed, aborted.
    state = Column(String, nullable=False, default="created", index=True)
    idempotency_key = Column(String, unique=True, index=True, nullable=False)
    routing_explanation = Column(Text, nullable=True)
    failure_reason = Column(String, nullable=True)
    mode = Column(String, nullable=False, default=payments_mode, index=True)  # TEST|LIVE, immutable
    created_at = Column(DateTime, default=_utcnow, index=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class ComplianceDecision(Base):
    """A screening/compliance decision for a seller (or a specific payout). A payout
    must not execute unless an APPROVED, current decision exists."""
    __tablename__ = "compliance_decisions"
    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    screening_type = Column(String, nullable=False)      # identity|sanctions|country|wallet|tax|risk
    provider = Column(String, nullable=True)
    decision = Column(String, nullable=False, default="NOT_STARTED")  # NOT_STARTED|INFORMATION_REQUIRED|UNDER_REVIEW|APPROVED|RESTRICTED|REJECTED|RESCREEN_REQUIRED
    reference = Column(String, nullable=True)
    checked_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime, nullable=True)


class PayoutMethodRail(Base):
    """A seller's chosen payout method on a specific rail (bank vs stablecoin shown
    separately). Distinct from the legacy SellerPayoutMethod (wallet-era)."""
    __tablename__ = "payout_method_rails"
    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    rail_type = Column(String, nullable=False)
    method_type = Column(String, nullable=False)         # bank|stablecoin
    currency = Column(String, nullable=True)
    masked_destination = Column(String, nullable=True)
    wallet_network = Column(String, nullable=True)
    verification_state = Column(String, nullable=False, default="unverified")
    active = Column(Boolean, default=False, nullable=False)
    consented_at = Column(DateTime, nullable=True)       # required for stablecoin
    provider_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    disabled_at = Column(DateTime, nullable=True)


class WalletTopup(Base):
    """A buyer 'Add funds' via Stripe Checkout (hosted card page). The wallet is credited
    when the session is paid (checkout.session.completed webhook, or the sandbox
    simulate-pay). Stamped with the money mode (TEST|LIVE) so demo top-ups can never be
    counted as live funds."""
    __tablename__ = "wallet_topups"
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String, unique=True, index=True, default=lambda: "wtu_" + _rand_vm_id())
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    amount_minor = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="usd")
    stripe_session_id = Column(String, unique=True, index=True, nullable=True)
    stripe_payment_intent_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)  # pending|paid|failed|expired
    mode = Column(String, nullable=False, default=payments_mode, index=True)  # TEST|LIVE, immutable
    created_at = Column(DateTime, default=_utcnow, index=True)
    credited_at = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_topup_amount_pos"),
    )


def get_topup_by_session(db: Session, session_id: str) -> "WalletTopup":
    return db.query(WalletTopup).filter(
        WalletTopup.stripe_session_id == session_id).first()


def mark_topup_paid_and_credit(db: Session, topup: "WalletTopup", *,
                               payment_intent_id: str = None) -> bool:
    """Credit the buyer's wallet exactly once for a paid top-up. Idempotent: a second
    call (duplicate webhook / retry) returns False and never double-credits."""
    if topup.status == "paid":
        return False
    topup.status = "paid"
    topup.credited_at = _utcnow()
    if payment_intent_id:
        topup.stripe_payment_intent_id = payment_intent_id
    user = db.query(User).filter(User.id == topup.user_id).first()
    if user:
        # minor -> major in Decimal (never binary float — the money rule the module enforces)
        deposit(db, user, Decimal(int(topup.amount_minor)) / Decimal(100))
    db.add(topup); db.commit()
    return True


def create_payout_obligation(db: Session, *, seller_id: int, compute_tx_id: int,
                             currency: str, net_amount_minor: int, country: str = None,
                             commission_minor: int = 0, pricing_snapshot: str = None,
                             risk_hold_until=None, is_demo: bool = False,
                             mode: str = None) -> "PayoutObligation":
    """Create the immutable obligation from a settled compute transaction. Idempotent
    per compute_tx_id: one settlement -> one obligation. `mode` MUST be the originating
    transaction's mode (tx.mode) so reconciling an old TEST tx after go-live cannot mint
    a LIVE obligation; when omitted it falls back to the current payments_mode()."""
    existing = db.query(PayoutObligation).filter(
        PayoutObligation.compute_tx_id == compute_tx_id).first()
    if existing:
        return existing
    obl = PayoutObligation(
        seller_id=seller_id, compute_tx_id=compute_tx_id, currency=currency,
        gross_amount_minor=net_amount_minor, net_amount_minor=net_amount_minor,
        commission_minor=commission_minor, country=country,
        pricing_snapshot=pricing_snapshot, risk_hold_until=risk_hold_until,
        available_at=risk_hold_until or _utcnow(),
        state="available" if risk_hold_until is None else "accrued", is_demo=is_demo,
        mode=(mode or payments_mode()))
    db.add(obl); db.commit(); db.refresh(obl)
    return obl


def payout_hold_elapsed(obligation, now=None) -> bool:
    """CLOCK-INJECTABLE risk-hold check: True iff this obligation's hold window has elapsed.

    This is the pure, testable core of the 14-day seller payout hold. Production calls it with
    ``now=None`` (a trusted UTC clock); tests inject ``now=captured_at + timedelta(days=15)`` to
    verify the exact boundary WITHOUT changing wall-clock time or exposing any clock override to
    a runtime HTTP request. The hold is satisfied at or after ``available_at``
    (== captured_at + PAYOUT_HOLD_DAYS), so day 13 is held and day 14 onward is eligible.

    It checks ONLY the time-based hold. Batch state, sanctions, and admin review holds are
    enforced separately (see payout_hold_active / payout_routing), so a True here does NOT by
    itself release money — it is one necessary condition, never the whole gate."""
    if obligation is None:
        return False
    if getattr(obligation, "state", None) in ("paid", "reversed", "cancelled"):
        return False
    now = now or _utcnow()
    avail = getattr(obligation, "available_at", None)
    if avail is None:
        return True                      # no hold configured (PAYOUT_HOLD_DAYS=0)
    # Normalize naive datetimes (SQLite round-trips lose tzinfo) to UTC before comparing.
    if getattr(avail, "tzinfo", None) is None:
        avail = avail.replace(tzinfo=timezone.utc)
    if getattr(now, "tzinfo", None) is None:
        now = now.replace(tzinfo=timezone.utc)
    return now >= avail


# A seller under one of these risk decisions has their payouts HELD: matured earnings
# do not become batchable until an admin clears the review. (Separate from the sanctions
# gate in payout_routing.compliance_ok.)
_PAYOUT_HOLD_DECISIONS = ("UNDER_REVIEW", "RESTRICTED", "INFORMATION_REQUIRED")


def payout_hold_active(db: Session, seller_id: int) -> bool:
    """True if the seller's LATEST 'risk' compliance decision is an active hold (e.g. an
    open report under review). While held, their earnings stay 'accrued' past the risk
    hold and are never batched — the money waits until an admin releases it."""
    d = (db.query(ComplianceDecision)
         .filter(ComplianceDecision.seller_id == seller_id,
                 ComplianceDecision.screening_type == "risk")
         .order_by(ComplianceDecision.id.desc()).first())
    return bool(d and d.decision in _PAYOUT_HOLD_DECISIONS)


def _held_seller_ids(db: Session) -> set:
    """Sellers whose LATEST 'risk' decision is an active payout hold."""
    rows = (db.query(ComplianceDecision.seller_id, ComplianceDecision.decision)
            .filter(ComplianceDecision.screening_type == "risk")
            .order_by(ComplianceDecision.seller_id, ComplianceDecision.id.desc()).all())
    latest, held = set(), set()
    for sid, dec in rows:
        if sid in latest:
            continue
        latest.add(sid)
        if dec in _PAYOUT_HOLD_DECISIONS:
            held.add(sid)
    return held


def place_payout_hold(db: Session, seller_id: int, reason: str = "under review"):
    """Put a seller's payouts on hold pending review (e.g. after a report). Recorded as a
    'risk' ComplianceDecision so it sits in the same audited decision log."""
    d = ComplianceDecision(seller_id=seller_id, screening_type="risk",
                           decision="UNDER_REVIEW", reference=(reason or "")[:200])
    db.add(d); db.commit(); db.refresh(d)
    return d


def clear_payout_hold(db: Session, seller_id: int, note: str = "cleared"):
    """Release a payout hold after review; matured earnings become batchable again."""
    d = ComplianceDecision(seller_id=seller_id, screening_type="risk",
                           decision="APPROVED", reference=(note or "")[:200])
    db.add(d); db.commit(); db.refresh(d)
    return d


def promote_due_obligations(db: Session, seller_id: int = None) -> int:
    """Move accrued obligations whose risk hold has elapsed (available_at <= now) to
    'available' so they become batchable automatically. Returns the count promoted.
    Sellers under an active payout hold (open report/review) are SKIPPED — their money
    stays held past the risk window until an admin clears it. Idempotent; safe to call
    on every read or from a scheduler."""
    q = (update(PayoutObligation)
         .where(PayoutObligation.state == "accrued",
                PayoutObligation.batch_id.is_(None),
                PayoutObligation.available_at.isnot(None),
                PayoutObligation.available_at <= _utcnow())
         .values(state="available"))
    if seller_id is not None:
        if payout_hold_active(db, seller_id):
            return 0
        q = q.where(PayoutObligation.seller_id == seller_id)
    else:
        held = _held_seller_ids(db)
        if held:
            q = q.where(PayoutObligation.seller_id.notin_(held))
    res = db.execute(q)
    db.commit()
    return res.rowcount or 0


def available_obligations(db: Session, seller_id: int, currency: str = None,
                          mode: str = None):
    """Obligations ready to be batched (available, not yet in a batch). Accrued
    obligations past their risk hold are promoted first so the hold expires on its own.
    A `mode` (TEST|LIVE) filter keeps test and live obligations in separate batches."""
    promote_due_obligations(db, seller_id)
    q = db.query(PayoutObligation).filter(
        PayoutObligation.seller_id == seller_id,
        PayoutObligation.state == "available",
        PayoutObligation.batch_id.is_(None))
    if currency:
        q = q.filter(PayoutObligation.currency == currency)
    if mode:
        q = q.filter(PayoutObligation.mode == mode)
    return q.all()


# --- Immutability guard: a financial record's TEST/LIVE mode can never change ---
def _forbid_mode_change(mapper, connection, target):
    from sqlalchemy import inspect as _sa_inspect
    hist = _sa_inspect(target).attrs.mode.history
    if hist.deleted and hist.added and hist.deleted[0] is not None \
            and hist.deleted[0] != hist.added[0]:
        raise ValueError(
            f"{type(target).__name__}.mode is immutable "
            f"({hist.deleted[0]} -> {hist.added[0]}); test and live money must never "
            f"be reclassified.")

for _mode_cls in (ComputeTransaction, PayoutObligation, PayoutBatch, WalletTopup):
    event.listen(_mode_cls, "before_update", _forbid_mode_change, propagate=True)


# ------------------ Session plumbing ------------------

def _ensure_columns():
    """Forward-migrate columns added to a model AFTER its table already exists.
    create_all() only creates missing TABLES, never columns — so on an older DB a
    newly-added column (e.g. bookings.test) is absent and every query on that table
    500s. This idempotently adds known-missing columns. Safe on SQLite and Postgres."""
    from sqlalchemy import inspect as _inspect, text as _text
    wanted = {
        "bookings": [("test", "BOOLEAN NOT NULL DEFAULT true"),
                     ("is_demo", "BOOLEAN NOT NULL DEFAULT false")],
        "specs": [("min_price", "FLOAT"), ("max_price", "FLOAT"),
                  ("auto_price", "BOOLEAN DEFAULT false"), ("public_id", "VARCHAR"),
                  ("is_demo", "BOOLEAN NOT NULL DEFAULT false"),
                  ("tee_attested_at", "TIMESTAMP"),
                  ("benchmark_verdict", "VARCHAR"),
                  ("benchmark_elapsed_s", "FLOAT"),
                  ("disk_enabled", "BOOLEAN DEFAULT false"),
                  ("disk_provider", "VARCHAR"), ("disk_alloc_gb", "INTEGER"),
                  ("disk_used_gb", "FLOAT"), ("disk_est_daily_usd", "FLOAT"),
                  ("disk_reported_at", "TIMESTAMP"),
                  ("cached_models", "TEXT"), ("cached_models_at", "TIMESTAMP")],
        "users": [("referral_code", "VARCHAR"), ("referred_by", "INTEGER"),
                  ("referral_rewarded", "BOOLEAN DEFAULT false"),
                  ("referral_signup_meta", "VARCHAR"),("email_verified", "BOOLEAN DEFAULT false"), ("email_token", "VARCHAR"),
                  ("email_token_exp", "TIMESTAMP"),
                  ("is_demo", "BOOLEAN NOT NULL DEFAULT false"),
                  ("created_at", "TIMESTAMP"),
                  ("totp_secret", "VARCHAR"),
                  ("totp_enabled", "BOOLEAN NOT NULL DEFAULT false"),
                  ("totp_backup_codes", "TEXT")],
        "platform": [("bookings_paused", "BOOLEAN DEFAULT false"),
                     ("pause_reason", "VARCHAR"), ("paused_at", "TIMESTAMP"),
                     ("landing_video_id", "VARCHAR"),
                     ("landing_video_orientation", "VARCHAR")],
        "ledger": [("tx_id", "INTEGER"), ("direction", "VARCHAR")],
        "vm_routes": [("hourly_rate", "FLOAT DEFAULT 0"), ("started_at", "TIMESTAMP"),
                      ("paid_until", "TIMESTAMP"), ("stopped_at", "TIMESTAMP")],
        "compute_transactions": [("mode", "VARCHAR NOT NULL DEFAULT 'TEST'")],
        "payout_obligations": [("mode", "VARCHAR NOT NULL DEFAULT 'TEST'")],
        "payout_batches": [("mode", "VARCHAR NOT NULL DEFAULT 'TEST'")],
        "revoked_api_keys": [("expires_at", "TIMESTAMP")],
        "connected_accounts": [("gateway_mode", "VARCHAR")],
        "tasks": [("result_content_hash", "VARCHAR"),
                  ("result_signature", "VARCHAR"), ("result_proof", "TEXT")],
        "multinode_jobs": [("backend", "VARCHAR"), ("master_addr", "VARCHAR"),
                           ("master_port", "INTEGER"), ("rendezvous_at", "TIMESTAMP")],
        "job_segments": [("peer_host", "VARCHAR"), ("peer_port", "INTEGER"),
                         ("slots", "INTEGER")],
        "audit_events": [("org_id", "INTEGER"), ("content_hash", "VARCHAR"),
                         ("chain_hash", "VARCHAR")],
    }
    try:
        insp = _inspect(engine)
    except Exception:
        return
    for table, cols in wanted.items():
        try:
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in existing:
                    with engine.begin() as conn:
                        conn.execute(_text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        except Exception:
            pass  # never block startup on a best-effort migration


def _ensure_check_constraints():
    """Best-effort: add the money-safety CHECK constraints to an EXISTING (pre-constraint) DB.
    create_all() only adds constraints to NEW tables, so a database whose `users`/`ledger` tables
    predate these constraints would keep allowing negative balances and invalid ledger legs.

    Postgres only (SQLite cannot ALTER TABLE ADD CONSTRAINT — fresh SQLite DBs get them via
    create_all). Guarded so it NEVER blocks startup or a deploy: each constraint is skipped if it
    already exists OR if any legacy row would violate it (which would make the ALTER fail) — in
    that case we log the count so an operator can remediate, then the constraint is added on a
    later boot. Idempotent."""
    import logging as _logging
    from sqlalchemy import text as _text
    if not engine.dialect.name.startswith("postgres"):
        return
    wanted = [
        ("users",  "ck_user_balance_nonneg",  "balance >= 0"),
        ("users",  "ck_user_earnings_nonneg", "earnings >= 0"),
        ("ledger", "ck_ledger_amount_pos",    "amount > 0"),
        ("ledger", "ck_ledger_direction",
         "direction is not null and direction in ('debit','credit')"),
    ]
    for table, name, check in wanted:
        try:
            with engine.begin() as conn:
                if conn.execute(_text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
                                {"n": name}).first():
                    continue                                   # already present
                bad = conn.execute(
                    _text(f"SELECT count(*) FROM {table} WHERE NOT ({check})")).scalar() or 0
                if bad:
                    _logging.getLogger("petabyte").warning(
                        "skip constraint %s on %s: %d legacy row(s) violate it — remediate, "
                        "then it will be added on the next boot", name, table, bad)
                    continue                                   # adding would fail; don't block
                conn.execute(_text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check})"))
        except Exception:  # noqa: BLE001 — never block startup on a best-effort constraint add
            pass


# Distinct from main._MAINTENANCE_LOCK_ID; stable so every worker contends on the same key.
_SCHEMA_LOCK_ID = 918273646


def init_db():
    """Bring the schema up to date, idempotently AND safely under concurrency.

    `create_all(checkfirst=True)` and the ALTER/CREATE-INDEX passes are each non-atomic across
    connections, so on a multi-worker boot (gunicorn) two processes can race — e.g. both issue
    CREATE TABLE and the loser fails with 'relation <table>_id_seq already exists' (the pg_class
    UniqueViolation we saw). On Postgres we serialize the WHOLE setup behind a session advisory
    lock: one worker does the work while the rest block, then run the same idempotent passes and
    no-op. SQLite (dev/tests) has no cross-process concurrency, so it runs the passes directly."""
    if not engine.dialect.name.startswith("postgres"):
        _schema_setup()
        return
    conn = engine.connect()
    try:
        conn.exec_driver_sql("SELECT pg_advisory_lock(%s)", (_SCHEMA_LOCK_ID,))
        _schema_setup()
    finally:
        try:
            conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (_SCHEMA_LOCK_ID,))
        finally:
            conn.close()


def _schema_setup():
    _create_all_safe()
    _ensure_columns()
    _ensure_check_constraints()
    _ensure_indexes()
    _backfill_public_ids()


def _create_all_safe():
    """create_all, healing a half-applied earlier deploy (orphaned SERIAL sequence) if needed."""
    try:
        Base.metadata.create_all(bind=engine, checkfirst=True)
    except Exception:  # noqa: BLE001
        _create_all_resilient()


def _create_all_resilient():
    """Last resort: create tables one at a time, tolerating one that already exists and clearing an
    ORPHANED SERIAL sequence (sequence present but its table absent — a prior create that failed
    mid-way) before retrying that single table. Never blocks startup on a benign 'already exists'."""
    import logging as _logging
    from sqlalchemy import inspect as _inspect, text as _text
    from sqlalchemy.exc import ProgrammingError, IntegrityError, OperationalError
    log = _logging.getLogger("petabyte")
    existing = set(_inspect(engine).get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name in existing:
            continue
        try:
            table.create(bind=engine, checkfirst=True)
        except (ProgrammingError, IntegrityError, OperationalError) as e:
            if "already exists" not in str(e).lower():
                raise
            # Benign "already exists": most often an ORPHANED SERIAL sequence (the sequence is
            # present but its table is absent, from a create that failed mid-way). Drop the orphan
            # ONLY when the table is genuinely missing, then retry the create. Any failure in the
            # drop or the retry now PROPAGATES — we must not swallow it and boot on a half-built
            # schema.
            log.warning("schema: healing orphaned sequence for %s and retrying create: %s",
                        table.name, e)
            with engine.begin() as conn:
                if not _inspect(conn).has_table(table.name):
                    # RESTRICT (the default — no CASCADE): a genuinely orphaned SERIAL sequence has
                    # no dependents, so it drops cleanly. If something else DOES depend on it (e.g.
                    # another table's column default references this sequence name), RESTRICT refuses
                    # and the error propagates — we fail closed rather than silently dropping another
                    # table's default and changing the schema contract.
                    conn.execute(_text(f'DROP SEQUENCE IF EXISTS "{table.name}_id_seq"'))
            table.create(bind=engine, checkfirst=True)
            # Fail closed: if recovery still did not produce the table, that is terminal. Returning
            # here would let init_db() "succeed" with the table absent, so later queries error out
            # and writes are silently discarded — worse than failing loudly at boot.
            if not _inspect(engine).has_table(table.name):
                raise RuntimeError(
                    f"schema: table {table.name!r} is still missing after orphan-sequence "
                    "recovery; refusing to start with an incomplete schema") from e


def _backfill_public_ids():
    """Give any pre-existing spec an opaque public handle (idempotent)."""
    try:
        db = SessionLocal()
        rows = db.query(SellerSpec).filter(SellerSpec.public_id.is_(None)).all()
        for r in rows:
            r.public_id = _rand_vm_id()
            db.add(r)
        if rows:
            db.commit()
        db.close()
    except Exception:
        pass


def get_spec_by_public_id(db: Session, public_id: str):
    return db.query(SellerSpec).filter(SellerSpec.public_id == public_id).first()


def _ensure_indexes():
    """Create indexes on hot query columns (idempotent; new + existing DBs).
    These back the marketplace scan, failover, metering, and pricing loops."""
    from sqlalchemy import inspect as _inspect, text as _text
    idx = [
        ("ix_specs_status", "specs", "status"),
        ("ix_specs_attested", "specs", "attested"),
        ("ix_specs_auto_price", "specs", "auto_price"),
        ("ix_vm_routes_status", "vm_routes", "status"),
        ("ix_vm_routes_spec", "vm_routes", "current_spec_id"),
        ("ix_bookings_status", "bookings", "status"),
    ]
    try:
        insp = _inspect(engine)
    except Exception:
        return
    for name, table, col in idx:
        try:
            if not insp.has_table(table):
                continue
            with engine.begin() as conn:
                conn.execute(_text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"))
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------ Users ------------------

def create_user(db: Session, username: str, password: str) -> User | None:
    if db.query(User).filter(User.username == username).first():
        return None
    user = User(username=username, password=hash_password(password), role="buyer")
    db.add(user); db.commit(); db.refresh(user)
    return user


def login_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user and verify_password(password, user.password):
        return user
    return None


# ------------------ Two-factor auth (TOTP) storage helpers ------------------

def set_totp_secret(db: Session, user: User, enc_secret: str) -> None:
    """Store a PENDING (encrypted) TOTP secret. 2FA is not active until a code confirms it."""
    user.totp_secret = enc_secret
    user.totp_enabled = False
    db.add(user); db.commit()


def enable_totp(db: Session, user: User, backup_hashes: list) -> None:
    user.totp_enabled = True
    user.totp_backup_codes = json.dumps(backup_hashes)
    db.add(user); db.commit()


def disable_totp(db: Session, user: User) -> None:
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    db.add(user); db.commit()


def hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode()[:72], bcrypt.gensalt()).decode()


def consume_backup_code(db: Session, user: User, code: str) -> bool:
    """Single-use recovery codes: if `code` matches an unused hash, remove it and return True."""
    if not user.totp_backup_codes:
        return False
    try:
        codes = json.loads(user.totp_backup_codes)
    except Exception:  # noqa: BLE001
        return False
    for i, h in enumerate(codes):
        try:
            if bcrypt.checkpw(code.encode()[:72], h.encode()):
                codes.pop(i)
                user.totp_backup_codes = json.dumps(codes)
                db.add(user); db.commit()
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def set_role(db: Session, username: str, role: str) -> str:
    if role not in ("buyer", "seller"):
        raise ValueError("role must be 'buyer' or 'seller'")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise ValueError("user not found")
    user.role = role; db.add(user); db.commit()
    return user.role


# ------------------ Specs ------------------

def save_specs(db: Session, owner: User, spec_data: dict) -> SellerSpec:
    units = int(spec_data.get("units", 1))
    db_spec = SellerSpec(
        user_id=owner.id,
        cpu=spec_data["cpu"],
        ram=spec_data["ram"],
        gpu_model=spec_data.get("gpu_model"),
        gpu_count=spec_data.get("gpu_count", 0),
        vram_gb=spec_data.get("vram_gb", 0),
        price_per_hour=spec_data["price_per_hour"],
        min_price=spec_data.get("min_price"),
        max_price=spec_data.get("max_price"),
        auto_price=bool(spec_data.get("auto_price", False)),
        duration=spec_data["duration"],
        provider=spec_data.get("provider"),
        region=spec_data.get("region"),
        country=spec_data.get("country"),
        total_units=units,
        available_units=units,
        status="offline",
    )
    db.add(db_spec); db.commit(); db.refresh(db_spec)
    return db_spec


def get_spec_by_id(db: Session, spec_id: int) -> SellerSpec | None:
    return db.query(SellerSpec).filter(SellerSpec.id == spec_id).first()


def spec_is_live(spec: SellerSpec, timeout_s: int = HEARTBEAT_TIMEOUT_S) -> bool:
    if spec.status != "online" or spec.last_seen is None:
        return False
    last = spec.last_seen
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (_utcnow() - last) <= timedelta(seconds=timeout_s)


# ------------------ Heartbeat / reaper ------------------

def touch_spec(db: Session, spec: SellerSpec) -> None:
    spec.last_seen = _utcnow()
    spec.status = "online"
    db.add(spec); db.commit()


def reap_stale_specs(db: Session, timeout_s: int = HEARTBEAT_TIMEOUT_S) -> int:
    """Mark specs offline if their heartbeat is stale. Returns rows affected."""
    cutoff = _utcnow() - timedelta(seconds=timeout_s)
    res = db.execute(
        update(SellerSpec)
        .where(SellerSpec.status == "online", SellerSpec.last_seen < cutoff)
        .values(status="offline")
    )
    db.commit()
    return res.rowcount


# ------------------ VM routing + failover ------------------
# A VMRoute is a rentable VM instance with a STABLE id (the vm_id in the URL).
# The platform proxies vm-<id>@petabyte.market to whatever node currently hosts
# it; on node death we re-point current_spec_id to a new node and the address is
# unchanged. (Gateway/tunnel + S3 restore need real machines — see vm-rental.md.)

def create_vm_route(db: Session, buyer_id: int, booking_id: int, template: str,
                    spec_id: int, app_port: int = 0, ssh_pubkey: str = None,
                    hourly_rate: float = 0, hours: int = 0) -> "VMRoute":
    now = _utcnow()
    vm = VMRoute(buyer_id=buyer_id, booking_id=booking_id, template=template,
                 current_spec_id=spec_id, app_port=app_port, status="starting",
                 ssh_pubkey=ssh_pubkey, hourly_rate=hourly_rate, started_at=now,
                 paid_until=now + timedelta(hours=hours) if hours else None)
    db.add(vm); db.commit(); db.refresh(vm)
    vm_event(db, vm.id, "created", f"template={template} spec={spec_id} rate=${hourly_rate}/hr hours={hours}")
    return vm


def get_vm_route(db: Session, vm_id: int) -> "VMRoute | None":
    return db.query(VMRoute).filter(VMRoute.id == vm_id).first()


def vm_routes_for_buyer(db: Session, buyer_id: int):
    return db.query(VMRoute).filter(VMRoute.buyer_id == buyer_id).order_by(
        VMRoute.id.desc()).all()


def register_vm_tunnel(db: Session, vm_id: int, spec_id: int, tunnel_port: int,
                       ip_address: str = None):
    """The hosting node reports its outbound tunnel port; VM becomes reachable."""
    vm = get_vm_route(db, vm_id)
    if not vm or vm.current_spec_id != spec_id or vm.status == "stopped":
        return None
    vm.tunnel_port = tunnel_port
    if ip_address:
        vm.node_ip = ip_address
    vm.status = "running"
    db.add(vm); db.commit(); db.refresh(vm)
    vm_event(db, vm.id, "tunnel_registered", f"spec={spec_id} tunnel_port={tunnel_port}")
    return vm


def stop_vm_route(db: Session, vm_id: int):
    vm = get_vm_route(db, vm_id)
    if not vm:
        return None
    vm.status = "stopped"; vm.tunnel_port = None
    db.add(vm); db.commit()
    return vm


def _pick_failover_spec(db: Session, vm: "VMRoute"):
    """Cheapest online, attested node (not the dead/current one, not the buyer's
    own) with free capacity — same eligibility a fresh launch would use."""
    cands = []
    for spec in db.query(SellerSpec).filter(
            SellerSpec.attested == True).all():  # noqa: E712
        if spec.id == vm.current_spec_id:
            continue
        if not spec_is_live(spec):
            continue
        if (spec.available_units or 0) < 1:
            continue
        if spec.user_id == vm.buyer_id:
            continue
        cands.append(spec)
    return min(cands, key=lambda s: s.price_per_hour) if cands else None


def failover_vm(db: Session, vm: "VMRoute"):
    """Re-point a VM to a new node, KEEPING vm.id (so the address is unchanged).
    The new node restores from snapshot_url (S3, stubbed) and re-registers its
    tunnel. Returns the new spec, or None if nothing eligible (VM -> 'failed')."""
    bk = db.query(Booking).filter(Booking.id == vm.booking_id).first()
    if not bk or bk.status not in ("escrowed", "active"):
        # Booking already settled (e.g. refunded by settle_dead_specs racing us):
        # there is nothing to migrate FOR — stop the VM instead of holding a unit.
        vm.status = "stopped"; vm.tunnel_port = None; vm.stopped_at = _utcnow()
        db.add(vm); db.commit()
        vm_event(db, vm.id, "stopped", "booking already settled; not migrating")
        return None
    new = _pick_failover_spec(db, vm)
    if not new or not try_reserve_unit(db, new.id):
        vm.status = "failed"; db.add(vm); db.commit()
        vm_event(db, vm.id, "failed", "no eligible node for failover")
        return None
    _old_spec = vm.current_spec_id
    # CAS on the spec pointer: exactly ONE concurrent failover may move this VM.
    res = db.execute(update(VMRoute)
                     .where(VMRoute.id == vm.id,
                            VMRoute.current_spec_id == _old_spec,
                            VMRoute.status.in_(["running", "starting", "migrating"]))
                     .values(current_spec_id=new.id, tunnel_port=None, node_ip=None,
                             status="migrating", migrations=VMRoute.migrations + 1))
    db.commit()
    if res.rowcount != 1:
        release_unit(db, new.id)      # lost the race — give back the unit we reserved
        db.refresh(vm)
        return None
    db.refresh(vm)
    # The booking must follow the VM: settlement releases capacity on Booking.spec_id
    # and pays Booking.seller_id — leave them on the dead node and you leak the new
    # node's unit and pay the wrong seller. GUARDED: if a racing stop settled the
    # booking between our CAS and here, the unit we reserved on the new node is
    # orphaned — release it and stop the VM instead of migrating a dead rental.
    res = db.execute(update(Booking)
                     .where(Booking.id == vm.booking_id,
                            Booking.status.in_(["escrowed", "active"]))
                     .values(spec_id=new.id, seller_id=new.user_id))
    db.commit()
    if res.rowcount != 1:
        release_unit(db, new.id)
        db.execute(update(VMRoute).where(VMRoute.id == vm.id)
                   .values(status="stopped", tunnel_port=None, stopped_at=_utcnow()))
        db.commit(); db.refresh(vm)
        vm_event(db, vm.id, "stopped", "booking settled during migration; not migrating")
        return None
    db.refresh(vm)
    # The VM left the old node — return that node's unit so its capacity
    # bookkeeping is correct when it comes back online.
    release_unit(db, _old_spec)
    vm_event(db, vm.id, "migrated", f"spec {_old_spec} -> {new.id} (node died); address unchanged")
    return new


def failover_vms_on_spec(db: Session, spec_id: int) -> int:
    """Migrate every live VM off a (now-dead) node. Returns count migrated."""
    n = 0
    for vm in db.query(VMRoute).filter(
            VMRoute.current_spec_id == spec_id,
            VMRoute.status.in_(["running", "starting", "migrating"])).all():
        if failover_vm(db, vm):
            n += 1
    return n


def reap_and_failover(db: Session, timeout_s: int = HEARTBEAT_TIMEOUT_S):
    """Reap stale specs, then migrate any live VMs off the newly-dead nodes.
    Returns (specs_reaped, vms_migrated). This is what the reaper service calls."""
    cutoff = _utcnow() - timedelta(seconds=timeout_s)
    dead = [s.id for s in db.query(SellerSpec).filter(
        SellerSpec.status == "online", SellerSpec.last_seen < cutoff).all()]
    reaped = reap_stale_specs(db, timeout_s)
    migrated = 0
    for sid in dead:
        migrated += failover_vms_on_spec(db, sid)
    return reaped, migrated


# ------------------ VM metering + lifecycle ------------------

def settle_metered(db: Session, booking_id: int, hours_used: float) -> bool:
    """Settle a rental by ACTUAL hours held: pay seller + platform for
    ceil(hours_used) (min 1h, capped at booked hours), refund the buyer the rest.
    Guarded so it fires at most once."""
    res = db.execute(update(Booking)
                     .where(Booking.id == booking_id,
                            Booking.status.in_(["escrowed", "active"]))
                     .values(status="released", released_at=_utcnow()))
    db.commit()
    if res.rowcount != 1:
        return False
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    used = max(1, min(math.ceil(hours_used), b.hours)) if b.hours else 1
    frac = (D(used) / D(b.hours)) if b.hours else Decimal(1)   # exact ratio, no float
    seller_earned = q(D(b.seller_payout) * frac)
    plat_earned = q(D(b.platform_fee) * frac)
    refund = q(D(b.gross_amount) - seller_earned - plat_earned)
    plat = get_or_create_platform(db)
    # atomic expression updates — never read-modify-write wallet fields, or a
    # concurrent atomic debit (e.g. a racing extend) gets erased by a stale read.
    db.execute(update(User).where(User.id == b.seller_id)
               .values(earnings=User.earnings + seller_earned))
    db.execute(update(Platform).where(Platform.id == plat.id)
               .values(revenue=Platform.revenue + plat_earned))
    if refund > 0:
        if b.org_id:
            org_refund(db, b.org_id, refund)
        else:
            db.execute(update(User).where(User.id == b.buyer_id)
                       .values(balance=User.balance + refund))
    # escrow drains EXACTLY into seller + platform + refund. If these don't add up,
    # post() raises and the settlement fails loudly rather than losing a cent.
    _back = acct_org(b.org_id) if b.org_id else acct_buyer(b.buyer_id)
    _legs = [(acct_escrow(b.id), DEBIT, D(b.gross_amount)),
             (acct_seller(b.seller_id), CREDIT, seller_earned, b.seller_id),
             (PLATFORM_REVENUE, CREDIT, plat_earned)]
    if refund > 0:
        _legs.append((_back, CREDIT, refund, b.buyer_id))
    post(db, "booking", legs=_legs, reference_id=b.id, booking_id=b.id,
         description="metered settlement", entry_type="release")
    db.commit()
    release_unit(db, b.spec_id)
    return True


def extend_booking(db: Session, booking_id: int, extra_hours: int,
                   take_rate: float = PLATFORM_TAKE_RATE) -> bool:
    """Add hours to a live rental: debit the buyer (personal wallet or org wallet,
    respecting the org budget cap), grow the escrow. Atomic against a racing
    stop/refund: the escrow grow is a guarded UPDATE; if the booking went terminal
    between our debit and the grow, the debit is refunded. False if terminal or
    insufficient funds/budget."""
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b or b.status not in ("escrowed", "active"):
        return False
    extra_gross = q(D(b.price_per_hour) * D(extra_hours))
    if b.org_id:
        if not try_org_debit(db, b.org_id, extra_gross):   # atomic, budget-capped
            return False
    else:
        # atomic conditional debit — no read-modify-write race on the wallet
        res = db.execute(update(User)
                         .where(User.id == b.buyer_id, User.balance >= extra_gross)
                         .values(balance=User.balance - extra_gross))
        db.commit()
        if res.rowcount != 1:
            return False
    extra_fee = q(extra_gross * D(take_rate))
    # guarded escrow grow: only lands if the booking is still live
    res = db.execute(update(Booking)
                     .where(Booking.id == booking_id,
                            Booking.status.in_(["escrowed", "active"]))
                     .values(hours=Booking.hours + extra_hours,
                             gross_amount=Booking.gross_amount + extra_gross,
                             platform_fee=Booking.platform_fee + extra_fee,
                             seller_payout=Booking.seller_payout + (extra_gross - extra_fee)))
    db.commit()
    if res.rowcount != 1:
        # lost the race to a stop/refund — give the debit back
        if b.org_id:
            org_refund(db, b.org_id, extra_gross)
        else:
            db.execute(update(User).where(User.id == b.buyer_id)
                       .values(balance=User.balance + extra_gross))
            db.commit()
        return False
    _src = acct_org(b.org_id) if b.org_id else acct_buyer(b.buyer_id)
    post(db, "booking", legs=[
        (_src,              DEBIT,  extra_gross, b.buyer_id),
        (acct_escrow(b.id), CREDIT, extra_gross),
    ], reference_id=b.id, booking_id=b.id,
       description="rental extended", entry_type="extend_escrow")
    db.commit()
    return True


def stop_vm_metered(db: Session, vm: "VMRoute") -> "VMRoute":
    """Stop a VM early: bill actual hours held, refund the unused prepay.
    Guarded so exactly ONE racing stop performs settlement + capacity release."""
    res = db.execute(update(VMRoute)
                     .where(VMRoute.id == vm.id,
                            VMRoute.status.in_(["starting", "running", "migrating"]))
                     .values(status="stopped", tunnel_port=None, stopped_at=_utcnow()))
    db.commit()
    db.refresh(vm)
    if res.rowcount != 1:
        return vm       # someone else won the stop race; they settle
    now = _utcnow()
    started = vm.started_at or vm.created_at or now
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    hours_used = max(0.0, (now - started).total_seconds() / 3600.0)
    settled = settle_metered(db, vm.booking_id, hours_used)
    if not settled:
        # Booking already terminal (refund/expiry/racing settle). That settle path
        # released capacity on the booking's spec_id — if the VM currently occupies
        # a DIFFERENT node (failover moved it after the booking was re-pointed or
        # before it), that node's unit is orphaned; release it. Comparing spec ids
        # (instead of just migrations>0) prevents double-release when the settle
        # already freed the same node the VM sits on.
        bk = db.query(Booking).filter(Booking.id == vm.booking_id).first()
        if bk and bk.spec_id != vm.current_spec_id:
            release_unit(db, vm.current_spec_id)
    vm_event(db, vm.id, "stopped", f"metered: {round(hours_used,2)}h held")
    return vm


def extend_vm(db: Session, vm: "VMRoute", extra_hours: int) -> bool:
    """Extend a VM's paid window if the buyer can afford it."""
    if not extend_booking(db, vm.booking_id, extra_hours):
        return False
    base = vm.paid_until or _utcnow()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    vm.paid_until = max(base, _utcnow()) + timedelta(hours=extra_hours)
    db.add(vm); db.commit()
    vm_event(db, vm.id, "extended", f"+{extra_hours}h")
    return True


def meter_and_expire(db: Session) -> int:
    """Auto-stop VMs whose prepaid window elapsed (funds exhausted) and pay the
    seller for the full window held. Returns count stopped."""
    now = _utcnow()
    n = 0
    for vm in db.query(VMRoute).filter(
            VMRoute.status.in_(["running", "starting", "migrating"])).all():
        if vm.paid_until is None:
            continue
        pu = vm.paid_until
        if pu.tzinfo is None:
            pu = pu.replace(tzinfo=timezone.utc)
        if now >= pu:
            release_booking(db, vm.booking_id)     # full window used -> seller paid in full
            vm.status = "stopped"; vm.tunnel_port = None; vm.stopped_at = now
            db.add(vm); db.commit()
            vm_event(db, vm.id, "expired", "prepaid window ended; auto-stopped")
            n += 1
    return n


# ------------------ Demand-based auto-pricing ------------------

def reprice_specs(db: Session, reference_price: float = None) -> int:
    """Recommend a price for each opted-in spec with the shared pricing engine and apply it.

    The old engine slid the listing around the midpoint of the seller's OWN [min,max] band with
    a demand multiplier — it never asked what the GPU is actually worth. This anchors on the
    per-GPU cloud on-demand rate (Petabyte's "cheaper than cloud, verified" value prop), then
    adjusts for demand, verified trust, and premiums via ``pricing_engine.recommend`` — the SAME
    pure function the /price/recommendation endpoint shows the seller, so the batch and the
    preview never disagree. Opt-in only (auto_price), always clamped inside the seller's own
    [min_price, max_price] and kept below cloud. Returns count repriced."""
    import pricing_engine   # local import: db.py must not depend on it at module load
    # Per-GPU-class demand: busy / total across live, attested specs of the same GPU model.
    busy_by, total_by = {}, {}
    for s in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(s):
            continue
        key = (s.gpu_model or "cpu").lower()
        total = s.total_units or 1
        busy = max(0, total - (s.available_units or 0))
        busy_by[key] = busy_by.get(key, 0) + busy
        total_by[key] = total_by.get(key, 0) + total

    auto = db.query(SellerSpec).filter(SellerSpec.auto_price == True).all()  # noqa: E712
    # Owner reputation in one query (avoid N+1) — a premium factor in the engine.
    owner_ids = {s.user_id for s in auto if s.user_id is not None}
    rep_by = {}
    if owner_ids:
        for u in db.query(User).filter(User.id.in_(owner_ids)).all():
            rep_by[u.id] = u.reputation

    n = 0
    for s in auto:
        if s.min_price is None or s.max_price is None or s.max_price < s.min_price:
            continue
        key = (s.gpu_model or "cpu").lower()
        total = total_by.get(key, 1)
        util = (busy_by.get(key, 0) / total) if total else 0.0     # 0..1
        cloud_ref = pricing_engine.cloud_reference_for(s.gpu_model)
        if cloud_ref is None and reference_price is not None:
            cloud_ref = float(reference_price)   # caller-supplied fallback anchor
        rec = pricing_engine.recommend(
            cloud_ref,
            perf_reference=pricing_engine.performance_reference_price(s.gpu_model),
            utilization=util,
            trust_level=trust_level_for(s).get("level"),
            benchmark_verdict=getattr(s, "benchmark_verdict", None),
            confidential=spec_confidential_active(s),
            region_verified=bool(getattr(s, "region_verified", False)),
            reputation=rep_by.get(s.user_id),
            min_price=float(s.min_price), max_price=float(s.max_price),
            current_price=float(s.price_per_hour or 0),
        )
        price = qc(D(str(rec["recommended_price"])))
        if abs(price - D(s.price_per_hour)) >= D("0.01"):
            db.add(PriceChange(spec_id=s.id, old_price=s.price_per_hour or 0,
                               new_price=price, utilization=round(util, 3),
                               reason="auto"))
            s.price_per_hour = price
            db.add(s); n += 1
    db.commit()
    return n


# ------------------ Atomic capacity reservation ------------------

def try_reserve_unit(db: Session, spec_id: int) -> bool:
    """Atomically decrement availability iff a unit is free.

    Single conditional UPDATE — safe under concurrency on both SQLite and
    Postgres without read-modify-write races or oversell.
    """
    res = db.execute(
        update(SellerSpec)
        .where(SellerSpec.id == spec_id, SellerSpec.available_units > 0)
        .values(available_units=SellerSpec.available_units - 1)
    )
    return res.rowcount == 1


def release_unit(db: Session, spec_id: int) -> None:
    db.execute(
        update(SellerSpec)
        .where(SellerSpec.id == spec_id,
               SellerSpec.available_units < SellerSpec.total_units)
        .values(available_units=SellerSpec.available_units + 1)
    )
    db.commit()


def create_booking(db: Session, buyer: User, spec: SellerSpec, hours: int,
                   vpn: bool, take_rate: float) -> Booking:
    """Insert the booking row. Caller must have already reserved a unit."""
    gross = q(D(spec.price_per_hour) * D(hours))
    fee = q(gross * D(take_rate))
    payout = q(gross - fee)
    booking = Booking(
        buyer_id=buyer.id, seller_id=spec.user_id, spec_id=spec.id,
        hours=hours, price_per_hour=spec.price_per_hour,
        gross_amount=gross, platform_fee=fee, seller_payout=payout,
        status="escrowed", vpn=vpn, org_id=org_id,
    )
    db.add(booking); db.commit(); db.refresh(booking)
    return booking


def get_booking_by_id(db: Session, booking_id: int) -> Booking | None:
    return db.query(Booking).filter(Booking.id == booking_id).first()


# ------------------ API key revocation ------------------

def revoke_jti(db: Session, jti: str, expires_at: datetime = None) -> None:
    if not db.query(RevokedApiKey).filter(RevokedApiKey.jti == jti).first():
        db.add(RevokedApiKey(jti=jti, expires_at=expires_at)); db.commit()


def is_jti_revoked(db: Session, jti: str) -> bool:
    return db.query(RevokedApiKey).filter(RevokedApiKey.jti == jti).first() is not None


def prune_expired_revocations(db: Session) -> int:
    """Drop denylist rows whose token is past its own recorded expiry — the token can no
    longer authenticate anyway, so the row only slows the per-request revocation lookup.
    Rows with no known expiry are kept forever (fail-safe)."""
    n = (db.query(RevokedApiKey)
         .filter(RevokedApiKey.expires_at.isnot(None), RevokedApiKey.expires_at < _utcnow())
         .delete(synchronize_session=False))
    db.commit()
    return int(n or 0)


# ------------------ WireGuard peer (race-safe allocation) ------------------

def add_wg_peer(db: Session, owner: User, public_key: str, max_attempts: int = 20) -> WGPeer:
    """Allocate a free /32 and insert the peer, retrying on the unique-constraint
    race so two concurrent requests never collide on the same address."""
    last_err = None
    for _ in range(max_attempts):
        used = {addr for (addr,) in db.query(WGPeer.address).all()}
        chosen = None
        for host in range(2, 255):
            cand = f"10.0.0.{host}/32"
            if cand not in used:
                chosen = cand
                break
        if chosen is None:
            raise ValueError("WireGuard /24 address pool exhausted")
        peer = WGPeer(owner_id=owner.id, public_key=public_key, address=chosen)
        db.add(peer)
        try:
            db.commit(); db.refresh(peer)
            return peer
        except IntegrityError as e:
            db.rollback(); last_err = e
            continue
    raise ValueError("could not allocate WireGuard address") from last_err


# ------------------ Idempotency ------------------

def idem_begin(db: Session, key: str, username: str, endpoint: str):
    """Claim an idempotency key atomically.

    Returns "new" if this caller owns the slot (proceed with side effects),
    otherwise returns the existing record (replay or in-progress)."""
    rec = IdempotencyRecord(key=key, username=username, endpoint=endpoint,
                            status_code=0, response="")
    db.add(rec)
    try:
        db.commit()
        return "new"
    except IntegrityError:
        db.rollback()
        return (db.query(IdempotencyRecord)
                .filter_by(key=key, username=username, endpoint=endpoint).first())


def idem_finish(db: Session, key: str, username: str, endpoint: str,
                status_code: int, response: dict) -> None:
    rec = (db.query(IdempotencyRecord)
           .filter_by(key=key, username=username, endpoint=endpoint).first())
    if rec:
        rec.status_code = status_code
        rec.response = json.dumps(response, default=_json_money)
        db.add(rec); db.commit()


def idem_abort(db: Session, key: str, username: str, endpoint: str) -> None:
    """Release a claimed-but-failed slot so a later retry can proceed."""
    db.query(IdempotencyRecord).filter_by(
        key=key, username=username, endpoint=endpoint, status_code=0).delete()
    db.commit()



# ------------------ Tasks / job dispatch ------------------

def create_task(db: Session, booking: "Booking", task_type: str, code: str = None,
                vm_type: str = None, cpu: int = None, ram: int = None,
                cuda: bool = False) -> "Task":
    task = Task(
        booking_id=booking.id, spec_id=booking.spec_id, buyer_id=booking.buyer_id,
        task_type=task_type, code=code, vm_type=vm_type, cpu=cpu, ram=ram, cuda=cuda,
        status="pending",
    )
    db.add(task); db.commit(); db.refresh(task)
    return task


def claim_next_task(db: Session, agent_user: "User", max_attempts: int = 5):
    """Atomically claim the oldest pending task whose spec the agent OWNS.

    Ownership binding (spec.user_id == agent_user.id) is the authz boundary:
    an agent can only ever execute work for hardware it registered.
    """
    for _ in range(max_attempts):
        candidate = (
            db.query(Task)
            .join(SellerSpec, Task.spec_id == SellerSpec.id)
            .filter(Task.status == "pending", SellerSpec.user_id == agent_user.id)
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .first()
        )
        if not candidate:
            return None
        res = db.execute(
            update(Task)
            .where(Task.id == candidate.id, Task.status == "pending")
            .values(status="assigned", claimed_by=agent_user.username,
                    assigned_at=_utcnow())
        )
        db.commit()
        if res.rowcount == 1:
            return db.query(Task).filter(Task.id == candidate.id).first()
        # lost the race; try the next candidate
    return None


def get_task_for_agent(db: Session, task_id: int, agent_user: "User"):
    """Fetch a task only if it belongs to a spec owned by this agent."""
    return (
        db.query(Task)
        .join(SellerSpec, Task.spec_id == SellerSpec.id)
        .filter(Task.id == task_id, SellerSpec.user_id == agent_user.id)
        .first()
    )


def mark_task_running(db: Session, task: "Task") -> None:
    task.status = "running"; db.add(task); db.commit()


def submit_task_result(db: Session, task: "Task", result: str,
                       status: str = "completed", content_hash: str = None,
                       signature: str = None, proof: dict = None) -> None:
    task.result = result
    task.status = status if status in ("completed", "failed", "running") else "completed"
    task.completed_at = _utcnow()
    if content_hash:
        # The seller-signed sha256 of the PLAINTEXT output bytes (from the signed proof). Stored
        # so a fraction of real jobs can be independently re-executed and compared (quorum),
        # instead of trusting a signed object-ref string. (#65)
        task.result_content_hash = str(content_hash)[:128]
    if signature:
        # Retain the node's Ed25519 signature + the exact signed payload so the BUYER can
        # verify the result offline against the node's attested pubkey (verifiable receipt).
        import json as _json
        task.result_signature = str(signature)[:256]
        try:
            task.result_proof = _json.dumps(proof or {}, sort_keys=True)[:4000]
        except Exception:
            task.result_proof = None
    db.add(task); db.commit()


def get_booking_for_buyer(db: Session, booking_id: int, buyer: "User"):
    return (db.query(Booking)
            .filter(Booking.id == booking_id, Booking.buyer_id == buyer.id).first())



# ------------------ Deterministic known-answer test ------------------

def compute_test_hash(size: int, seed: int) -> str:
    """Deterministic INTEGER reduction -> reproducible on any CPU/GPU/driver.

    Float GPU results are NOT bit-reproducible across hardware, so known-answer
    tests must use integer arithmetic. Server computes the expected value at
    dispatch; the honest agent computes the identical value.
    """
    MOD = (1 << 61) - 1
    a = (seed % MOD) or 1
    acc = 0
    for i in range(size):
        a = (a * 6364136223846793005 + 1442695040888963407) % MOD
        acc = (acc + a * (i + 1)) % MOD
    return hashlib.sha256(str(acc).encode()).hexdigest()


_DIFFICULTY_SIZE = {"easy": 5000, "medium": 50000, "hard": 500000}


def create_test_task(db: Session, spec: "SellerSpec", difficulty: str = "easy",
                     trigger: str = "manual"):
    import json as _json
    size = _DIFFICULTY_SIZE.get(difficulty, 5000)
    # The seed IS the security basis of the proof-of-work: a seller who can predict it precomputes
    # compute_test_hash(size, seed) and passes without doing fresh GPU work. Use a CSPRNG, not the
    # shared MT19937 global (whose state is recoverable from a handful of observed seeds).
    seed = secrets.randbelow(2_000_000_000) + 1
    expected = compute_test_hash(size, seed)
    task = Task(spec_id=spec.id, task_type="test",
                code=_json.dumps({"size": size, "seed": seed}), status="pending")
    db.add(task); db.commit(); db.refresh(task)
    tw = TestWorkload(task_id=task.id, spec_id=spec.id, seller_id=spec.user_id,
                      size=size, seed=seed, expected_hash=expected,
                      difficulty=difficulty, trigger=trigger, status="pending")
    db.add(tw); db.commit(); db.refresh(tw)
    return task, tw


def get_testworkload_by_task(db: Session, task_id: int):
    return db.query(TestWorkload).filter(TestWorkload.task_id == task_id).first()


# ------------------ Reputation ------------------

def _apply_gate(user: "User") -> None:
    user.can_accept_paid_jobs = user.reputation >= MIN_REPUTATION


def record_test_result(db: Session, tw: "TestWorkload", actual_hash: str) -> bool:
    seller = db.query(User).filter(User.id == tw.seller_id).first()
    passed = (actual_hash == tw.expected_hash)
    tw.status = "passed" if passed else "failed"
    tw.completed_at = _utcnow()
    if passed:
        seller.tests_passed += 1
        seller.reputation = min(100, seller.reputation + 2)
    else:
        seller.tests_failed += 1
        seller.reputation = max(0, seller.reputation - 15)
    _apply_gate(seller)
    db.add_all([tw, seller]); db.commit()
    return passed


def penalize_user(db: Session, user: "User", amount: int) -> None:
    user.reputation = max(0, user.reputation - amount)
    _apply_gate(user)
    db.add(user); db.commit()


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()



# ------------------ Settlement: wallet, escrow, ledger ------------------

def _gen_referral_code(db: Session) -> str:
    """Short, unambiguous, unique share code."""
    import secrets, string
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I
    for _ in range(20):
        code = "".join(secrets.choice(alpha) for _ in range(7))
        if not db.query(User).filter(User.referral_code == code).first():
            return code
    return "R" + secrets.token_hex(4).upper()


def ensure_referral_code(db: Session, user: "User") -> str:
    """Every user has a code; created lazily the first time they need it."""
    if not user.referral_code:
        user.referral_code = _gen_referral_code(db)
        db.add(user); db.commit(); db.refresh(user)
    return user.referral_code


def apply_referral(db: Session, new_user: "User", ref_code: str, signup_meta: str = None):
    """Link a new user to their referrer at signup. No reward yet — that only fires when
    the new user completes a qualifying paid rental (fraud-resistant)."""
    if not ref_code:
        return
    referrer = db.query(User).filter(User.referral_code == ref_code.strip().upper()).first()
    if not referrer or referrer.id == new_user.id:
        return                                  # unknown code, or self
    new_user.referred_by = referrer.id
    new_user.referral_signup_meta = (signup_meta or "")[:200]
    db.add(new_user); db.commit()


# Referral reward config (dollars of credit per side). Admin/env tunable.
def _referral_amount() -> Decimal:
    import os
    try:
        return q(D(os.getenv("REFERRAL_REWARD_USD", "20")))
    except Exception:
        return q(D(20))

def _referral_monthly_cap() -> int:
    import os
    try:
        return int(os.getenv("REFERRAL_MONTHLY_CAP", "25"))
    except Exception:
        return 25


def _grant_promo_credit(db: Session, user: "User", amount: Decimal, why: str, ref_id=None):
    """Add NON-withdrawable spendable credit to a user's balance, funded from promo
    expense so the ledger stays balanced. (balance is spend-only; only `earnings`
    can be withdrawn, so this can never be cashed out.)"""
    user.balance = q(D(user.balance) + amount)
    db.add(user)
    post(db, "referral_credit", legs=[
        (EXTERNAL_PROMO, DEBIT, amount),
        (acct_buyer(user.id), CREDIT, amount, user.id),
    ], reference_id=ref_id, description=why, entry_type="promo")


def maybe_reward_referral(db: Session, buyer: "User"):
    """Called AFTER a rental settles cleanly. If this buyer was referred and hasn't been
    rewarded yet, grant credit to BOTH sides — with self-referral + monthly-cap guards.
    Best-effort and fully isolated from settlement: any problem here must never affect
    the rental that already completed."""
    try:
        if not buyer or buyer.referral_rewarded or not buyer.referred_by:
            return
        referrer = db.query(User).filter(User.id == buyer.referred_by).first()
        if not referrer or referrer.id == buyer.id:
            return
        # self-referral guard: same signup fingerprint => refuse
        if (buyer.referral_signup_meta and referrer.referral_signup_meta
                and buyer.referral_signup_meta == referrer.referral_signup_meta):
            buyer.referral_rewarded = True; db.add(buyer); db.commit()
            return
        # monthly cap: how many rewards has this referrer already earned this month?
        month_start = _utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        already = db.query(LedgerTx).filter(
            LedgerTx.reference_type == "referral_credit",
            LedgerTx.reference_id == str(referrer.id),
            LedgerTx.created_at >= month_start).count()
        if already >= _referral_monthly_cap():
            return                              # leave rewarded=False; not their fault, don't burn it
        amt = _referral_amount()
        _grant_promo_credit(db, referrer, amt, f"referral: {buyer.username} qualified",
                            ref_id=referrer.id)
        _grant_promo_credit(db, buyer, amt, "welcome: referral bonus", ref_id=referrer.id)
        buyer.referral_rewarded = True
        db.add(buyer); db.commit()
    except Exception:
        db.rollback()
        logger.exception("referral reward failed for buyer %s", getattr(buyer, "id", "?"))


def get_or_create_platform(db: Session) -> "Platform":
    p = db.query(Platform).first()
    if not p:
        p = Platform(revenue=0.0); db.add(p); db.commit(); db.refresh(p)
    return p


def deposit(db: Session, user: "User", amount: float) -> float:
    """Sandbox top-up. In production this is a payment-provider webhook, not an API call."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    user.balance = q(D(user.balance) + D(amount))
    db.add(user)
    # money enters the system: the processor owes us less, the buyer's wallet grows
    post(db, "deposit", legs=[
        (EXTERNAL_PAYMENTS, DEBIT,  amount),
        (acct_buyer(user.id), CREDIT, amount, user.id),
    ], reference_id=user.id, description="wallet deposit", entry_type="deposit")
    db.commit()
    return user.balance


def try_debit(db: Session, user_id: int, amount: float) -> bool:
    """Atomic balance debit (conditional UPDATE) — no overspend under concurrency."""
    res = db.execute(
        update(User)
        .where(User.id == user_id, User.balance >= amount)
        .values(balance=User.balance - amount)
    )
    db.commit()
    return res.rowcount == 1


def book_with_escrow(db: Session, buyer: "User", spec: "SellerSpec", hours: int,
                     vpn: bool, take_rate: float, org_id: int = None) -> "Booking":
    """Create the booking and hold funds in escrow. Caller has already debited
    the buyer and reserved a unit; this records the booking + escrow ledger entry."""
    # KILL SWITCH. Refuse NEW bookings when paused. Running rentals are untouched and
    # settle normally — stopping the world must never destroy someone's 6-hour render.
    # Enforced HERE, at the one place every booking path converges, so no endpoint can
    # accidentally route around it.
    _paused, _reason = bookings_are_paused(db)
    if _paused:
        raise BookingsPaused(_reason)
    gross = q(D(spec.price_per_hour) * D(hours))
    fee = q(gross * D(take_rate))
    payout = q(gross - fee)
    booking = Booking(
        buyer_id=buyer.id, seller_id=spec.user_id, spec_id=spec.id,
        hours=hours, price_per_hour=spec.price_per_hour,
        gross_amount=gross, platform_fee=fee, seller_payout=payout,
        status="escrowed", vpn=vpn, org_id=org_id,
    )
    db.add(booking); db.commit(); db.refresh(booking)
    _src = acct_org(org_id) if org_id else acct_buyer(buyer.id)
    post(db, "booking", legs=[
        (_src,                       DEBIT,  gross, buyer.id),
        (acct_escrow(booking.id),    CREDIT, gross),
    ], reference_id=booking.id, booking_id=booking.id,
       description="funds held in escrow for rental", entry_type="escrow_hold")
    db.commit()
    return booking


def mark_booking_active(db: Session, booking_id: int) -> None:
    db.execute(update(Booking).where(Booking.id == booking_id, Booking.status == "escrowed")
               .values(status="active"))
    db.commit()


def release_booking(db: Session, booking_id: int) -> bool:
    """Pay the seller + platform. Guarded so it fires at most once per booking."""
    res = db.execute(
        update(Booking)
        .where(Booking.id == booking_id, Booking.status.in_(["escrowed", "active"]))
        .values(status="released", released_at=_utcnow())
    )
    db.commit()
    if res.rowcount != 1:
        return False  # already terminal (released/refunded) -> never double-pay
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    seller = db.query(User).filter(User.id == b.seller_id).first()
    plat = get_or_create_platform(db)
    seller.earnings = q(D(seller.earnings) + D(b.seller_payout))
    plat.revenue = q(D(plat.revenue) + D(b.platform_fee))
    db.add_all([seller, plat])
    post(db, "booking", legs=[
        (acct_escrow(b.id),        DEBIT,  D(b.gross_amount)),
        (acct_seller(seller.id),   CREDIT, D(b.seller_payout), seller.id),
        (PLATFORM_REVENUE,         CREDIT, D(b.platform_fee)),
    ], reference_id=b.id, booking_id=b.id,
       description="rental completed", entry_type="release")
    db.commit()
    release_unit(db, b.spec_id)  # rental finished -> free capacity
    # A real paid rental just completed. If this buyer was referred, THIS is the
    # qualifying event — reward both sides. Isolated: settlement already committed above,
    # so a referral hiccup can never undo the rental.
    if b.buyer_id:
        buyer = db.query(User).filter(User.id == b.buyer_id).first()
        maybe_reward_referral(db, buyer)
    return True


def refund_booking(db: Session, booking_id: int) -> bool:
    """Return escrowed funds to the buyer and free the capacity. Guarded -> once."""
    res = db.execute(
        update(Booking)
        .where(Booking.id == booking_id, Booking.status.in_(["escrowed", "active"]))
        .values(status="refunded", refunded_at=_utcnow())
    )
    db.commit()
    if res.rowcount != 1:
        return False
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if b.org_id:                                   # refund the org wallet
        org_refund(db, b.org_id, b.gross_amount)
    else:
        buyer = db.query(User).filter(User.id == b.buyer_id).first()
        buyer.balance = q(D(buyer.balance) + D(b.gross_amount))
        db.add(buyer)
    release_unit(db, b.spec_id)  # give the reserved unit back
    _back = acct_org(b.org_id) if b.org_id else acct_buyer(buyer.id)
    post(db, "booking", legs=[
        (acct_escrow(b.id), DEBIT,  D(b.gross_amount)),
        (_back,             CREDIT, D(b.gross_amount), buyer.id),
    ], reference_id=b.id, booking_id=b.id,
       description="rental refunded", entry_type="refund_buyer")
    db.commit()
    return True


def settle_dead_specs(db: Session, grace_s: int = None) -> int:
    """For every offline spec's in-flight bookings:
      - if a task has backups (backup_enabled + a checkpoint) and hasn't been
        interrupted longer than the grace window, RESCHEDULE it (resume from the
        last checkpoint when capacity returns) and keep the booking active;
      - otherwise refund the booking and fail its tasks (refund-on-reap).
    Idempotent."""
    import os as _os
    if grace_s is None:
        grace_s = int(_os.getenv("BACKUP_RESCHEDULE_GRACE_S", "900"))
    refunded = 0
    now = _utcnow()
    offline = db.query(SellerSpec).filter(SellerSpec.status == "offline").all()
    for spec in offline:
        bks = (db.query(Booking)
               .filter(Booking.spec_id == spec.id,
                       Booking.status.in_(["escrowed", "active"])).all())
        for b in bks:
            tasks = (db.query(Task)
                     .filter(Task.booking_id == b.id,
                             Task.status.in_(["pending", "assigned", "running"])).all())
            resched = []
            for t in tasks:
                if t.backup_enabled and t.latest_checkpoint_ref:
                    ia = t.interrupted_at
                    if ia is not None and ia.tzinfo is None:
                        ia = ia.replace(tzinfo=timezone.utc)
                    expired = ia is not None and (now - ia).total_seconds() > grace_s
                    if not expired:
                        resched.append(t)
            if resched:
                for t in resched:
                    t.status = "pending"; t.claimed_by = None
                    if t.interrupted_at is None:
                        t.interrupted_at = now
                    db.add(t)
                db.commit()
                continue                      # keep booking active; no refund
            if refund_booking(db, b.id):       # give up -> refund + fail
                refunded += 1
                db.execute(update(Task)
                           .where(Task.booking_id == b.id,
                                  Task.status.in_(["pending", "assigned", "running"]))
                           .values(status="failed"))
                db.commit()
    return refunded



# ------------------ Payment webhooks ------------------

def webhook_already_processed(db: Session, event_id: str) -> bool:
    """Atomically claim an event_id. Returns True if it was ALREADY processed."""
    rec = ProcessedWebhook(event_id=event_id)
    db.add(rec)
    try:
        db.commit()
        return False            # newly claimed -> proceed to credit
    except IntegrityError:
        db.rollback()
        return True             # seen before -> skip (idempotent)


def credit_user_by_username(db: Session, username: str, amount: float) -> bool:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return False
    deposit(db, user, amount)
    return True


def credit_user_from_webhook(db: Session, event_id: str, username: str, amount) -> str:
    """Claim the webhook event_id AND credit the user in ONE transaction (atomic claim-and-credit).

    The old flow claimed the id and credited in SEPARATE commits, so a crash between them marked
    the event processed without crediting — and the provider's retry was then silently deduped
    (lost credit). Here the ProcessedWebhook claim, the balance update, and the ledger legs share a
    single commit: either all land or none do. Returns 'ok' | 'duplicate' | 'unknown_user'."""
    amount = q(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    db.add(ProcessedWebhook(event_id=event_id))
    try:
        db.flush()                       # claim the id (unique constraint dedups)
    except IntegrityError:
        db.rollback()
        return "duplicate"
    user = db.query(User).filter(User.username == username).first()
    if not user:
        db.rollback()                    # release the claim so a corrected retry can still credit
        return "unknown_user"
    # Atomic server-side increment (try_debit's pattern): a concurrent spend between our read
    # of `user` and this commit must not be overwritten by a stale Python-side sum.
    db.execute(update(User).where(User.id == user.id)
               .values(balance=User.balance + amount))
    post(db, "deposit", legs=[
        (EXTERNAL_PAYMENTS,   DEBIT,  amount),
        (acct_buyer(user.id), CREDIT, amount, user.id),
    ], reference_id=user.id, description="wallet deposit (webhook)", entry_type="deposit")
    db.commit()
    return "ok"



# ------------------ Confidential computing (TEE) attestation ------------------

import secrets as _secrets


def create_challenge(db: Session, spec: "SellerSpec", ttl_s: int = 300) -> str:
    nonce = _secrets.token_hex(32)
    ch = AttestationChallenge(spec_id=spec.id, nonce=nonce,
                              expires_at=_utcnow() + timedelta(seconds=ttl_s))
    db.add(ch); db.commit()
    return nonce


def consume_challenge(db: Session, spec_id: int, nonce: str) -> bool:
    """Atomically mark a fresh, unused, matching challenge as used."""
    ch = (db.query(AttestationChallenge)
          .filter(AttestationChallenge.spec_id == spec_id,
                  AttestationChallenge.nonce == nonce,
                  AttestationChallenge.used == False).first())  # noqa: E712
    if not ch:
        return False
    exp = ch.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if _utcnow() > exp:
        return False
    res = db.execute(update(AttestationChallenge)
                     .where(AttestationChallenge.id == ch.id,
                            AttestationChallenge.used == False)  # noqa: E712
                     .values(used=True))
    db.commit()
    return res.rowcount == 1


def set_spec_confidential(db: Session, spec: "SellerSpec", vendor: str,
                          measurement: str, report: str) -> None:
    spec.confidential = True
    spec.tee_vendor = vendor
    spec.tee_measurement = measurement
    spec.tee_report = report
    spec.tee_attested_at = _utcnow()          # freshness clock — confidential status expires
    db.add(spec); db.commit()


def _tee_attestation_ttl_s() -> int:
    """How long a confidential (TEE) attestation is honored before re-attestation is
    required. Confidential computing is only meaningful if the enclave state is FRESH —
    a stale 'confidential=True' from months ago attests nothing about the machine today."""
    try:
        return int(os.getenv("TEE_ATTESTATION_TTL_S", str(24 * 3600)))
    except ValueError:
        return 24 * 3600


def spec_confidential_active(spec, now=None, ttl_s=None) -> bool:
    """True only if this spec is confidential AND its TEE attestation is still fresh.

    A confidential booking/dispatch must gate on THIS, not the raw `confidential` flag: the
    flag alone can be stale, and (combined with the production fail-closed verifier in
    utils.verify_tee_report) this keeps 'confidential' meaning a currently-attested enclave."""
    if not getattr(spec, "confidential", False):
        return False
    ts = getattr(spec, "tee_attested_at", None)
    if ts is None:
        return False                          # confidential but never stamped -> not fresh
    now = now or _utcnow()
    ttl = _tee_attestation_ttl_s() if ttl_s is None else ttl_s
    # SQLite round-trips datetimes tz-naive while _utcnow() is tz-aware — compare in naive UTC.
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    if ts.tzinfo is not None:
        ts = ts.replace(tzinfo=None)
    return (now - ts).total_seconds() <= ttl



# ------------------ Organizations ------------------

def create_org(db: Session, name: str, creator: "User"):
    if db.query(Organization).filter(Organization.name == name).first():
        return None
    org = Organization(name=name)
    db.add(org); db.commit(); db.refresh(org)
    db.add(OrgMember(org_id=org.id, user_id=creator.id, role="admin"))
    db.commit()
    return org


def get_org(db: Session, org_id: int):
    return db.query(Organization).filter(Organization.id == org_id).first()


def get_membership(db: Session, org_id: int, user_id: int):
    return (db.query(OrgMember)
            .filter(OrgMember.org_id == org_id, OrgMember.user_id == user_id).first())


def list_orgs_for_user(db: Session, user_id: int):
    """Every org the user belongs to, with their role and the org's live wallet/budget.
    Powers the console Teams panel — the user can't act on an org whose id they don't know,
    so the console needs a way to enumerate their memberships (there is no public org directory)."""
    rows = (db.query(OrgMember, Organization)
            .join(Organization, Organization.id == OrgMember.org_id)
            .filter(OrgMember.user_id == user_id)
            .order_by(Organization.id.asc()).all())
    out = []
    for m, org in rows:
        cap = float(org.budget_cap or 0)
        out.append({
            "org_id": org.id, "name": org.name, "your_role": m.role,
            "balance": round(float(org.balance or 0), 2),
            "budget_cap": (round(cap, 2) if cap else None),
            "spent": round(float(org.spent or 0), 2),
            "members": db.query(OrgMember).filter(OrgMember.org_id == org.id).count(),
        })
    return out


def org_members(db: Session, org_id: int):
    rows = db.query(OrgMember).filter(OrgMember.org_id == org_id).all()
    out = []
    for m in rows:
        u = db.query(User).filter(User.id == m.user_id).first()
        out.append({"username": u.username if u else "?", "role": m.role})
    return out


def add_org_member(db: Session, org: "Organization", username: str, role: str) -> bool:
    if role not in ("admin", "billing", "member"):
        raise ValueError("role must be admin|billing|member")
    u = db.query(User).filter(User.username == username).first()
    if not u:
        return False
    if get_membership(db, org.id, u.id):
        return True
    db.add(OrgMember(org_id=org.id, user_id=u.id, role=role)); db.commit()
    return True


def org_admin_count(db: Session, org_id: int) -> int:
    return db.query(OrgMember).filter(OrgMember.org_id == org_id,
                                      OrgMember.role == "admin").count()


def set_org_member_role(db: Session, org_id: int, username: str, role: str) -> str:
    """Change an existing member's role. Returns a status string the API maps to HTTP:
    'ok' | 'not_found' (user isn't a member) | 'last_admin' (would leave the org with no admin).
    An org must always keep at least one admin — demoting the sole admin is refused."""
    if role not in ("admin", "billing", "member"):
        raise ValueError("role must be admin|billing|member")
    u = db.query(User).filter(User.username == username).first()
    if not u:
        return "not_found"
    m = get_membership(db, org_id, u.id)
    if not m:
        return "not_found"
    if m.role == "admin" and role != "admin" and org_admin_count(db, org_id) <= 1:
        return "last_admin"
    m.role = role
    db.add(m); db.commit()
    return "ok"


def remove_org_member(db: Session, org_id: int, username: str) -> str:
    """Remove a member from an org. Returns 'ok' | 'not_found' | 'last_admin'.
    Removing the sole admin is refused so an org can never become unmanageable."""
    u = db.query(User).filter(User.username == username).first()
    if not u:
        return "not_found"
    m = get_membership(db, org_id, u.id)
    if not m:
        return "not_found"
    if m.role == "admin" and org_admin_count(db, org_id) <= 1:
        return "last_admin"
    db.delete(m); db.commit()
    return "ok"


# ------------------ Persistent volumes (content-addressed, incremental snapshots) ------------------

def create_volume(db: Session, buyer: "User", name: str, size_limit_gb=None, org_id=None):
    v = Volume(buyer_id=buyer.id, org_id=org_id, name=name,
               size_limit_gb=(int(size_limit_gb) if size_limit_gb else None))
    db.add(v); db.commit(); db.refresh(v)
    return v


def get_volume(db: Session, volume_id: int):
    return db.query(Volume).filter(Volume.id == volume_id).first()


def list_volumes(db: Session, buyer_id: int):
    from sqlalchemy import func
    rows = (db.query(Volume).filter(Volume.buyer_id == buyer_id)
            .order_by(Volume.id.desc()).all())
    out = []
    for v in rows:
        # dedup savings = sum of the LOGICAL size of every snapshot minus what we actually hold.
        logical = int(db.query(func.coalesce(func.sum(VolumeSnapshot.total_bytes), 0))
                      .filter(VolumeSnapshot.volume_id == v.id).scalar() or 0)
        out.append({"id": v.id, "name": v.name, "org_id": v.org_id,
                    "size_limit_gb": v.size_limit_gb, "bytes_stored": v.bytes_stored,
                    "snapshots": v.snapshot_count,
                    "dedup_saved_bytes": max(0, logical - int(v.bytes_stored or 0)),
                    "created_at": v.created_at.isoformat() if v.created_at else None})
    return out


def volume_blob_shas(db: Session, volume_id: int) -> set:
    return {r.sha256 for r in db.query(VolumeBlob.sha256).filter(VolumeBlob.volume_id == volume_id)}


def volume_blob_exists(db: Session, volume_id: int, sha256: str) -> bool:
    return db.query(VolumeBlob.id).filter(
        VolumeBlob.volume_id == volume_id, VolumeBlob.sha256 == sha256).first() is not None


def register_volume_blob(db: Session, volume_id: int, sha256: str, size: int) -> bool:
    """Add a blob to the index if new. Returns True iff newly added (i.e. it counts toward the
    delta / the volume's real stored bytes); False if it was already present (deduplicated)."""
    if volume_blob_exists(db, volume_id, sha256):
        return False
    db.add(VolumeBlob(volume_id=volume_id, sha256=sha256, size=int(size)))
    v = db.query(Volume).filter(Volume.id == volume_id).first()
    if v:
        v.bytes_stored = int(v.bytes_stored or 0) + int(size)
        db.add(v)
    db.commit()
    return True


def plan_snapshot(db: Session, volume_id: int, files: list) -> dict:
    """Given the manifest a client WANTS to snapshot, return which content blobs are MISSING (the
    delta to upload) vs. already held (deduped). Files are [{path, sha256, size, ...}]. This is the
    'only send the delta' step — unchanged content is never uploaded again."""
    have = volume_blob_shas(db, volume_id)
    seen, missing, missing_bytes, reused = set(), [], 0, 0
    for f in files:
        sha = f["sha256"]
        if sha in seen:
            continue
        seen.add(sha)
        if sha in have:
            reused += 1
        else:
            missing.append({"sha256": sha, "size": int(f.get("size", 0))})
            missing_bytes += int(f.get("size", 0))
    return {"missing": missing, "missing_bytes": missing_bytes,
            "reused_blobs": reused, "unique_blobs": len(seen),
            "total_bytes": sum(int(f.get("size", 0)) for f in files)}


def finalize_snapshot(db: Session, volume: "Volume", files: list, present_shas: set,
                      label=None, vm_id=None) -> "VolumeSnapshot":
    """Record a snapshot. `present_shas` is the set of sha256 the caller has VERIFIED exist in object
    storage (uploaded now or already held). Any referenced blob not yet indexed is registered here,
    and its bytes count as this snapshot's delta. Raises if a referenced blob isn't present."""
    delta = 0
    for f in files:
        sha, size = f["sha256"], int(f.get("size", 0))
        if volume_blob_exists(db, volume.id, sha):
            continue
        if sha not in present_shas:
            raise ValueError(f"blob {sha[:12]} was never uploaded")
        if register_volume_blob(db, volume.id, sha, size):
            delta += size
    seq = int(volume.snapshot_count or 0) + 1
    snap = VolumeSnapshot(
        volume_id=volume.id, seq=seq, label=label, vm_id=vm_id,
        manifest=json.dumps(files, separators=(",", ":")),
        total_bytes=sum(int(f.get("size", 0)) for f in files), delta_bytes=delta)
    db.add(snap)
    volume.snapshot_count = seq
    db.add(volume); db.commit(); db.refresh(snap)
    return snap


def list_snapshots(db: Session, volume_id: int):
    rows = (db.query(VolumeSnapshot).filter(VolumeSnapshot.volume_id == volume_id)
            .order_by(VolumeSnapshot.seq.desc()).all())
    return [{"id": s.id, "seq": s.seq, "label": s.label, "vm_id": s.vm_id,
             "total_bytes": s.total_bytes, "delta_bytes": s.delta_bytes,
             "files": len(json.loads(s.manifest or "[]")),
             "created_at": s.created_at.isoformat() if s.created_at else None} for s in rows]


def get_snapshot(db: Session, volume_id: int, snapshot_id: int):
    return (db.query(VolumeSnapshot)
            .filter(VolumeSnapshot.volume_id == volume_id, VolumeSnapshot.id == snapshot_id).first())


def restore_manifest(db: Session, volume_id: int, snap: "VolumeSnapshot", since=None) -> dict:
    """The files to reconstruct a snapshot. With `since` (an earlier snapshot), return ONLY the files
    whose content changed since then — the delta the client still needs (it already has the rest)."""
    files = json.loads(snap.manifest or "[]")
    full_size = sum(int(f.get("size", 0)) for f in files)
    out = files
    if since is not None:
        base = {f["path"]: f["sha256"] for f in json.loads(since.manifest or "[]")}
        out = [f for f in files if base.get(f["path"]) != f["sha256"]]
    return {"files": out, "full_size": full_size,
            "delta_size": sum(int(f.get("size", 0)) for f in out),
            "is_delta": since is not None, "file_count": len(files), "delta_count": len(out)}


def delete_volume(db: Session, volume: "Volume") -> list:
    """Delete the volume + its snapshots + blob index. Returns the list of blob sha256 that were
    held, so the caller can remove them from object storage."""
    shas = [r.sha256 for r in db.query(VolumeBlob.sha256).filter(VolumeBlob.volume_id == volume.id)]
    db.query(VolumeSnapshot).filter(VolumeSnapshot.volume_id == volume.id).delete()
    db.query(VolumeBlob).filter(VolumeBlob.volume_id == volume.id).delete()
    db.delete(volume); db.commit()
    return shas


def org_deposit(db: Session, org: "Organization", amount: float) -> float:
    if amount <= 0:
        raise ValueError("amount must be positive")
    org.balance = q(D(org.balance) + D(amount))
    db.add(org)
    post(db, "org_deposit", legs=[
        (EXTERNAL_PAYMENTS, DEBIT,  amount),
        (acct_org(org.id),  CREDIT, amount),
    ], reference_id=org.id, description="org wallet deposit", entry_type="deposit")
    db.commit()
    return org.balance


def try_org_debit(db: Session, org_id: int, amount: float) -> bool:
    """Atomic org-wallet debit respecting the budget cap (0 = unlimited)."""
    res = db.execute(
        update(Organization)
        .where(Organization.id == org_id,
               Organization.balance >= amount,
               (Organization.budget_cap == 0) |
               (Organization.spent + amount <= Organization.budget_cap))
        .values(balance=Organization.balance - amount,
                spent=Organization.spent + amount)
    )
    db.commit()
    return res.rowcount == 1


def org_refund(db: Session, org_id: int, amount: float) -> None:
    db.execute(update(Organization).where(Organization.id == org_id)
               .values(balance=Organization.balance + amount,
                       spent=Organization.spent - amount))
    db.commit()


def org_usage(db: Session, org_id: int):
    """Per-booking usage for invoicing/export."""
    bks = db.query(Booking).filter(Booking.org_id == org_id).all()
    return [{"booking_id": b.id, "spec_id": b.spec_id, "hours": b.hours,
             "gross_amount": b.gross_amount, "status": b.status,
             "created_at": str(b.created_at)} for b in bks]



# ------------------ Job management: retry / progress / logs ------------------

def retry_task(db: Session, task: "Task", max_retries: int = 3) -> bool:
    if task.status not in ("failed",):
        return False
    if (task.retries or 0) >= max_retries:
        return False
    task.status = "pending"; task.claimed_by = None
    task.progress = 0; task.retries = (task.retries or 0) + 1
    db.add(task); db.commit()
    return True


def set_task_progress(db: Session, task: "Task", percent: int, msg: str = None) -> None:
    task.progress = max(0, min(100, int(percent)))
    if msg is not None:
        task.progress_msg = msg[:500]
    db.add(task); db.commit()


def add_task_log(db: Session, task_id: int, line: str) -> None:
    db.add(TaskLog(task_id=task_id, line=line[:2000])); db.commit()


def get_task_logs(db: Session, task_id: int, after_id: int = 0):
    return (db.query(TaskLog)
            .filter(TaskLog.task_id == task_id, TaskLog.id > after_id)
            .order_by(TaskLog.id.asc()).all())


# ------------------ Benchmarks ------------------

def set_benchmark(db: Session, spec: "SellerSpec", tokens_sec: float, meta: dict,
                  verdict: str = None, elapsed_s: float = None) -> None:
    import json as _json
    spec.benchmark_tokens_sec = tokens_sec
    spec.benchmark_meta = _json.dumps(meta or {})
    spec.benchmark_at = _utcnow()
    if verdict is not None:
        # consistency of the reported number with the CLAIMED gpu_model's public band.
        spec.benchmark_verdict = str(verdict)[:32]
    if elapsed_s is not None:
        spec.benchmark_elapsed_s = float(elapsed_s)
    db.add(spec); db.commit()


def record_benchmark_sample(db: Session, spec: "SellerSpec", *, source: str,
                            metrics: dict = None, verdict: str = None,
                            pow_verified: bool = None, elapsed_s: float = None,
                            tokens_sec: float = None) -> "BenchmarkSample":
    """Append a labelled training example (features + context) to the authenticity dataset.
    Best-effort: a logging failure must never break the benchmark/idle path."""
    import json as _json
    seller = get_user_by_id(db, spec.user_id) if spec is not None else None
    row = BenchmarkSample(
        spec_id=(spec.id if spec is not None else None),
        seller_id=(spec.user_id if spec is not None else None),
        gpu_model=(spec.gpu_model if spec is not None else None),
        source=source, metrics=_json.dumps(metrics or {}), verdict=verdict,
        pow_verified=pow_verified, elapsed_s=elapsed_s, tokens_sec=tokens_sec,
        reputation=(getattr(seller, "reputation", None) if seller is not None else None),
        jobs_completed=(spec.jobs_completed if spec is not None else None),
        jobs_failed=(spec.jobs_failed if spec is not None else None),
        fraud_count=(spec.fraud_count if spec is not None else None),
        attested=(spec.attested if spec is not None else None),
        confidential=(spec.confidential if spec is not None else None),
        region_verified=(spec.region_verified if spec is not None else None),
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def create_benchmark_task(db: Session, spec: "SellerSpec"):
    import json as _json
    # A FRESH server challenge rides with every benchmark: the node must return
    # compute_test_hash(size, seed) for THIS seed, proving it actually ran seeded work now —
    # a pre-canned or replayed benchmark number can't answer a seed it never saw. Use a CSPRNG so
    # the seed can't be predicted/precomputed from prior observed seeds.
    challenge = {"bench_seed": secrets.randbelow(2_000_000_000) + 1, "bench_size": 50000}
    task = Task(spec_id=spec.id, task_type="benchmark", status="pending", priority=5,
                code=_json.dumps(challenge))
    db.add(task); db.commit(); db.refresh(task)
    return task


# ------------------ Org cost analytics ------------------

def org_analytics(db: Session, org_id: int):
    bks = db.query(Booking).filter(Booking.org_id == org_id).all()
    by_status = {}
    by_spec = {}
    total = Decimal(0)
    for b in bks:
        by_status[b.status] = q(D(by_status.get(b.status, 0)) + D(b.gross_amount))
        by_spec[b.spec_id] = q(D(by_spec.get(b.spec_id, 0)) + D(b.gross_amount))
        total += D(b.gross_amount)
    return {"total_spend": qc(total), "bookings": len(bks),
            "spend_by_status": by_status, "spend_by_spec": by_spec}



# ------------------ Backup / restore (any stateful task) ------------------

def get_or_create_task_enc_key(db: Session, task: "Task") -> str:
    """Per-task symmetric key for client-side backup encryption (sealed at rest)."""
    from utils import seal_secret, open_secret
    if task.enc_key:
        return open_secret(task.enc_key)
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    task.enc_key = seal_secret(key)
    db.add(task); db.commit()
    return key


def record_checkpoint(db: Session, task: "Task", snapshot_ref: str,
                      size_bytes: int = 0, content_hash: str = None) -> "Checkpoint":
    cp = Checkpoint(task_id=task.id, snapshot_ref=snapshot_ref,
                    size_bytes=size_bytes, content_hash=content_hash)
    db.add(cp)
    task.latest_checkpoint_ref = snapshot_ref      # newest backup to restore from
    db.add(task); db.commit(); db.refresh(cp)
    return cp


def list_checkpoints(db: Session, task_id: int):
    return (db.query(Checkpoint).filter(Checkpoint.task_id == task_id)
            .order_by(Checkpoint.id.desc()).all())


def reschedule_task(db: Session, task: "Task", restore_ref: str = None) -> None:
    """Re-queue a task so a node can pick it up and restore from its backup."""
    task.status = "pending"; task.claimed_by = None
    if restore_ref:
        task.latest_checkpoint_ref = restore_ref
    db.add(task); db.commit()



# ------------------ Reputation (event-sourced) ------------------

def record_rep_event(db: Session, spec: "SellerSpec", event_type: str,
                     value: float = 0.0, meta: str = None) -> None:
    db.add(ReputationEvent(spec_id=spec.id, owner_id=spec.user_id,
                           event_type=event_type, value=value, meta=meta))
    db.commit()


def note_heartbeat(db: Session, spec: "SellerSpec") -> None:
    spec.heartbeats = (spec.heartbeats or 0) + 1
    if spec.first_seen is None:
        spec.first_seen = _utcnow()
    db.add(spec); db.commit()


def note_job_completed(db: Session, spec: "SellerSpec", latency_s: float = None) -> None:
    spec.jobs_completed = (spec.jobs_completed or 0) + 1
    if latency_s is not None and latency_s >= 0:
        spec.latency_sum_s = (spec.latency_sum_s or 0.0) + latency_s
        spec.latency_n = (spec.latency_n or 0) + 1
    db.add(spec); db.commit()
    record_rep_event(db, spec, "completed", latency_s or 0.0)


def note_job_failed(db: Session, spec: "SellerSpec", reason: str = "") -> None:
    spec.jobs_failed = (spec.jobs_failed or 0) + 1
    db.add(spec); db.commit()
    record_rep_event(db, spec, "failed", 1.0, reason)


def note_fraud(db: Session, spec: "SellerSpec", reason: str = "") -> None:
    spec.fraud_count = (spec.fraud_count or 0) + 1
    db.add(spec); db.commit()
    record_rep_event(db, spec, "fraud", 1.0, reason)


def compute_reputation(db: Session, spec: "SellerSpec") -> dict:
    """Derive an auditable 0-100 score + breakdown from recorded signals."""
    done = spec.jobs_completed or 0
    failed = spec.jobs_failed or 0
    fraud = spec.fraud_count or 0
    total = done + failed
    completion_rate = (done / total) if total else None
    avg_latency = (spec.latency_sum_s / spec.latency_n) if (spec.latency_n or 0) else None
    # score: reward completion + a working benchmark; punish failures hard, fraud harder.
    score = 60.0
    if total:
        score += 30.0 * completion_rate - 15.0 * (failed / total)
    if spec.benchmark_tokens_sec:
        score += 5.0
    score -= 25.0 * fraud
    score = max(0.0, min(100.0, score))
    return {
        "score": round(score, 1),
        "jobs_completed": done, "jobs_failed": failed,
        "completion_rate": round(completion_rate, 3) if completion_rate is not None else None,
        "fraud_count": fraud,
        "avg_latency_s": round(avg_latency, 2) if avg_latency is not None else None,
        "benchmark_tokens_sec": spec.benchmark_tokens_sec,
        "heartbeats": spec.heartbeats or 0,
        "owner_reputation": None,   # filled by caller (User.reputation)
    }


def recent_rep_events(db: Session, spec_id: int, limit: int = 20):
    return (db.query(ReputationEvent).filter(ReputationEvent.spec_id == spec_id)
            .order_by(ReputationEvent.id.desc()).limit(limit).all())



# ------------------ Payouts (withdraw seller earnings) ------------------

def try_debit_earnings(db: Session, user_id: int, amount) -> bool:
    amount = q(amount)
    res = db.execute(update(User).where(User.id == user_id, User.earnings >= amount)
                     .values(earnings=User.earnings - amount))
    db.commit()
    return res.rowcount == 1


def credit_earnings(db: Session, user_id: int, amount: float) -> None:
    amount = q(amount)   # coerce to the money type — a float here breaks the in-session evaluator
    db.execute(update(User).where(User.id == user_id)
               .values(earnings=User.earnings + amount))
    db.commit()


def add_payout_method(db: Session, user: "User", kind: str, destination: str,
                      label: str = None) -> "SellerPayoutMethod":
    if kind not in ("gift_card", "usdc", "bank"):
        raise ValueError("kind must be gift_card|usdc|bank")
    m = SellerPayoutMethod(user_id=user.id, kind=kind, destination=destination, label=label)
    db.add(m); db.commit(); db.refresh(m)
    return m


def list_payout_methods(db: Session, user_id: int):
    return db.query(SellerPayoutMethod).filter(SellerPayoutMethod.user_id == user_id).all()


def get_payout_method(db: Session, method_id: int, user_id: int):
    return (db.query(SellerPayoutMethod)
            .filter(SellerPayoutMethod.id == method_id,
                    SellerPayoutMethod.user_id == user_id).first())


def instant_payout_fee(amount) -> Decimal:
    """The fee for an INSTANT (on-demand) payout of `amount`: max(flat floor, pct). Never exceeds
    the amount. Scheduled/batch payouts are free (fee 0) — this is charged only when the seller
    chooses instant cash-out."""
    amt = qc(amount)
    if amt <= 0:
        return qc(0)
    fee = INSTANT_PAYOUT_FEE_MIN if INSTANT_PAYOUT_FEE_MIN > (amt * INSTANT_PAYOUT_FEE_PCT) \
        else (amt * INSTANT_PAYOUT_FEE_PCT)
    return qc(fee if fee < amt else amt)


def seller_cleared_jobs(db: Session, user_id: int) -> int:
    """Count of this seller's completed (released) paid bookings — the 'verified jobs' bar."""
    return db.query(Booking).filter(Booking.seller_id == user_id,
                                    Booking.status == "released").count()


def is_payout_matured(db: Session, user) -> bool:
    """True once a seller is trusted enough for INSTANT (fast) payout: good reputation AND at
    least PAYOUT_MATURITY_MIN_JOBS completed jobs. New/low-rep sellers must use the free scheduled
    path (which still respects the clearing hold) — closing the fast-exit fraud window."""
    uid = getattr(user, "id", user)
    rep = int(getattr(user, "reputation", 0) or 0)
    return rep >= MIN_REPUTATION and seller_cleared_jobs(db, uid) >= PAYOUT_MATURITY_MIN_JOBS


def held_earnings(db: Session, user_id: int, *, now=None, hold_hours=None) -> Decimal:
    """Sum of payouts from bookings this seller completed within the clearing/dispute window —
    money that has been earned but is not yet withdrawable (a window to catch a bad job first)."""
    now = now or _utcnow()
    hrs = EARNINGS_HOLD_HOURS if hold_hours is None else int(hold_hours)
    cutoff = now - timedelta(hours=hrs)
    if getattr(cutoff, "tzinfo", None) is not None:
        cutoff = cutoff.replace(tzinfo=None)   # released_at is stored naive-UTC
    total = Decimal(0)
    for b in db.query(Booking).filter(Booking.seller_id == user_id,
                                      Booking.status == "released",
                                      Booking.released_at.isnot(None),
                                      Booking.released_at >= cutoff).all():
        total += D(b.seller_payout)
    return q(total)


def withdrawable_earnings(db: Session, user, *, now=None) -> Decimal:
    """Earnings a seller can withdraw RIGHT NOW = total earnings minus amounts still in the
    clearing/dispute hold. Never negative."""
    u = user if hasattr(user, "earnings") else get_user_by_id(db, user)
    w = D(u.earnings) - held_earnings(db, u.id, now=now)
    return q(w if w > 0 else Decimal(0))


def request_payout(db: Session, user: "User", method: "SellerPayoutMethod",
                   amount: float, *, fee=0.0) -> "Payout":
    """Atomically debit earnings and enqueue a payout. Returns None if short. `fee` > 0 is the
    instant-payout fee: the seller's earnings drop by the GROSS `amount`, the rail receives
    `amount - fee`, and `fee` is booked to PLATFORM_REVENUE (a real revenue leg). fee=0 is the
    free scheduled/normal path (unchanged)."""
    if amount <= 0 or not method.verified:
        return None
    gross = qc(amount)
    fee = qc(fee) if (fee and qc(fee) > 0) else qc(0)
    if fee >= gross:                       # the fee must be smaller than the amount
        return None
    net = gross - fee
    if not try_debit_earnings(db, user.id, gross):
        return None
    p = Payout(user_id=user.id, method_id=method.id, amount_usd=net, fee_usd=fee,
               kind=method.kind, status="requested")
    db.add(p); db.flush()
    # money LEAVES the system: seller earnings (gross) split into the rail (net) + our fee.
    legs = [(acct_seller(user.id), DEBIT, gross, user.id),
            (EXTERNAL_PAYOUTS,     CREDIT, net)]
    if fee > 0:
        legs.append((PLATFORM_REVENUE, CREDIT, fee))
    post(db, "payout", legs=legs, reference_id=p.id,
         description=f"payout via {method.kind}" + (" (instant)" if fee > 0 else ""),
         entry_type="payout")
    db.commit(); db.refresh(p)
    return p


def set_payout_status(db: Session, payout: "Payout", status: str,
                      provider_ref: str = None, reason: str = None) -> None:
    vals = {"status": status, "updated_at": _utcnow()}
    if provider_ref:
        vals["provider_ref"] = provider_ref
    if reason:
        vals["reason"] = reason
    # CLAIM the failed transition with a conditional UPDATE so exactly ONE caller wins even
    # under concurrency — an in-Python `prev != "failed"` guard reads a stale status, and two
    # racing 'failed' writers would then both run the reversal (double-credit).
    claimed_failed = False
    if status == "failed":
        claimed_failed = bool(db.execute(
            update(Payout).where(Payout.id == payout.id, Payout.status != "failed")
            .values(**vals)).rowcount)
        if not claimed_failed:                       # already failed: refresh refs only
            db.execute(update(Payout).where(Payout.id == payout.id)
                       .values(**{k: v for k, v in vals.items() if k != "status"}))
    else:
        db.execute(update(Payout).where(Payout.id == payout.id).values(**vals))
    db.commit()
    db.refresh(payout)
    # Return the money on failure, exactly ONCE (the atomic claim above guarantees it).
    if claimed_failed:
        gross = q(payout.amount_usd) + q(payout.fee_usd or 0)   # net that would ship + instant fee
        net = q(payout.amount_usd)
        fee = q(payout.fee_usd or 0)
        # 1) Restore the seller's spendable earnings scalar so they're made whole.
        credit_earnings(db, payout.user_id, gross)
        # 2) Post the REVERSING ledger legs (audit M3). request_payout recorded the money as having
        #    LEFT the system (seller_earnings DEBIT gross, EXTERNAL_PAYOUTS CREDIT net, PLATFORM_REVENUE
        #    CREDIT fee). A failed payout means nothing actually left the bank rail, so mirror those
        #    legs back — otherwise the ledger permanently overstates external payouts and diverges
        #    from both the seller_earnings scalar and reality. Balanced by construction (gross=net+fee).
        legs = [(acct_seller(payout.user_id), CREDIT, gross, payout.user_id),
                (EXTERNAL_PAYOUTS,            DEBIT,  net)]
        if fee > 0:
            legs.append((PLATFORM_REVENUE, DEBIT, fee))
        post(db, "payout", legs=legs, reference_id=payout.id,
             description=f"payout #{payout.id} failed — reversal ({payout.kind})",
             entry_type="payout_reversal")
        db.commit()


def pending_payouts(db: Session):
    return db.query(Payout).filter(Payout.status == "requested").all()


def list_payouts(db: Session, user_id: int):
    return (db.query(Payout).filter(Payout.user_id == user_id)
            .order_by(Payout.id.desc()).all())


# ------------------ Scheduled auto-withdraw ------------------

def compute_next_run(now_utc, day_of_week: int, hour: int, minute: int,
                     utc_offset_minutes: int):
    local = now_utc + timedelta(minutes=utc_offset_minutes)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (day_of_week - local.weekday()) % 7
    target = target + timedelta(days=days_ahead)
    if target <= local:
        target = target + timedelta(days=7)
    return target - timedelta(minutes=utc_offset_minutes)   # back to UTC


def create_schedule(db: Session, user: "User", method: "SellerPayoutMethod",
                    day_of_week: int, hour: int, minute: int,
                    utc_offset_minutes: int, min_amount: float) -> "PayoutSchedule":
    nxt = compute_next_run(_utcnow(), day_of_week, hour, minute, utc_offset_minutes)
    sch = PayoutSchedule(user_id=user.id, method_id=method.id, day_of_week=day_of_week,
                         hour=hour, minute=minute, utc_offset_minutes=utc_offset_minutes,
                         min_amount=min_amount, next_run_at=nxt, enabled=True)
    db.add(sch); db.commit(); db.refresh(sch)
    return sch


def list_schedules(db: Session, user_id: int):
    return db.query(PayoutSchedule).filter(PayoutSchedule.user_id == user_id).all()


def run_due_schedules(db: Session, now_utc=None) -> int:
    """Enqueue payouts for schedules whose time has arrived. Returns count enqueued."""
    now_utc = now_utc or _utcnow()
    fired = 0
    rows = db.query(PayoutSchedule).filter(PayoutSchedule.enabled == True).all()  # noqa: E712
    for sch in rows:
        nxt = sch.next_run_at
        if nxt is not None and nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        if nxt is None or now_utc < nxt:
            continue
        user = db.query(User).filter(User.id == sch.user_id).first()
        method = db.query(SellerPayoutMethod).filter(SellerPayoutMethod.id == sch.method_id).first()
        # Only pay out earnings that have CLEARED the hold window (scheduled payouts respect the
        # same anti-fraud hold as manual ones, so a schedule can't be used to dodge it).
        avail = withdrawable_earnings(db, user, now=now_utc) if user else Decimal(0)
        if user and method and method.verified and avail >= q(sch.min_amount) and avail > 0:
            request_payout(db, user, method, qc(avail))
            fired += 1
        sch.last_run_at = now_utc
        sch.next_run_at = compute_next_run(now_utc, sch.day_of_week, sch.hour,
                                           sch.minute, sch.utc_offset_minutes)
        db.add(sch); db.commit()
    return fired



# ------------------ Notifications ------------------

def record_notification(db: Session, user_id: int, event_type: str, subject: str,
                        body: str, status: str = "queued") -> "Notification":
    n = Notification(user_id=user_id, event_type=event_type, subject=subject,
                     body=body, status=status)
    db.add(n); db.commit(); db.refresh(n)
    return n


def set_notification_status(db: Session, n: "Notification", status: str) -> None:
    n.status = status; db.add(n); db.commit()


def list_notifications(db: Session, user_id: int, limit: int = 50):
    return (db.query(Notification).filter(Notification.user_id == user_id)
            .order_by(Notification.id.desc()).limit(limit).all())



# ------------------ Multi-node jobs (render / transcode) ------------------

def create_multinode_job(db: Session, buyer: "User", kind: str, params: dict, total: int):
    import json as _j
    job = MultiNodeJob(buyer_id=buyer.id, kind=kind, params=_j.dumps(params or {}),
                       total_segments=total, status="running")
    db.add(job); db.commit(); db.refresh(job)
    return job


def add_job_segment(db: Session, job: "MultiNodeJob", idx: int, task_id: int,
                    rstart, rend) -> "JobSegment":
    seg = JobSegment(job_id=job.id, idx=idx, task_id=task_id,
                     range_start=rstart, range_end=rend)
    db.add(seg); db.commit(); db.refresh(seg)
    return seg


def segment_for_task(db: Session, task_id: int):
    return db.query(JobSegment).filter(JobSegment.task_id == task_id).first()


def complete_segment(db: Session, seg: "JobSegment", output_ref: str):
    seg.output_ref = output_ref; seg.status = "done"
    db.add(seg); db.commit()
    return db.query(MultiNodeJob).filter(MultiNodeJob.id == seg.job_id).first()


def all_segments_done(db: Session, job: "MultiNodeJob") -> bool:
    segs = db.query(JobSegment).filter(JobSegment.job_id == job.id).all()
    return bool(segs) and all(s.status == "done" for s in segs)


def segment_output_refs(db: Session, job: "MultiNodeJob"):
    segs = (db.query(JobSegment).filter(JobSegment.job_id == job.id)
            .order_by(JobSegment.idx.asc()).all())
    return [s.output_ref for s in segs]


def set_job_status(db: Session, job: "MultiNodeJob", status: str,
                   output_ref: str = None, stitch_task_id: int = None):
    job.status = status
    if output_ref:
        job.output_ref = output_ref
    if stitch_task_id:
        job.stitch_task_id = stitch_task_id
    db.add(job); db.commit()


def get_multinode_job(db: Session, job_id: int):
    return db.query(MultiNodeJob).filter(MultiNodeJob.id == job_id).first()


# ------------------- DISTRIBUTED (multi-node cluster) coordination -------------------

def create_distributed_job(db: Session, buyer: "User", params: dict,
                           world_size: int, backend: str = "nccl"):
    """A coordinated N-rank cluster (kind='distributed'). total_segments == world_size."""
    import json as _j
    job = MultiNodeJob(buyer_id=buyer.id, kind="distributed", params=_j.dumps(params or {}),
                       total_segments=int(world_size), status="running", backend=backend)
    db.add(job); db.commit(); db.refresh(job)
    return job


def set_rendezvous(db: Session, job: "MultiNodeJob", addr: str, port: int) -> bool:
    """Record rank-0's VPN-reachable address so the other ranks can join. First writer wins:
    once set, a different address is refused (returns False) — the cluster has one master."""
    if job.master_addr and (job.master_addr != addr or job.master_port != int(port)):
        return False
    job.master_addr = addr
    job.master_port = int(port)
    if job.rendezvous_at is None:
        job.rendezvous_at = _utcnow()
    db.add(job); db.commit()
    return True


def rendezvous_info(db: Session, job: "MultiNodeJob") -> dict:
    return {"job_id": job.id, "status": job.status, "world_size": job.total_segments,
            "backend": job.backend, "master_addr": job.master_addr,
            "master_port": job.master_port, "ready": bool(job.master_addr)}


def distributed_job_for_task(db: Session, task_id: int):
    """The distributed cluster a task belongs to (via its segment), or None."""
    seg = db.query(JobSegment).filter(JobSegment.task_id == task_id).first()
    if not seg:
        return None
    job = db.query(MultiNodeJob).filter(MultiNodeJob.id == seg.job_id).first()
    return job if (job and job.kind == "distributed") else None


def rank_for_agent(db: Session, job: "MultiNodeJob", agent_user: "User"):
    """The (segment, rank) this agent owns in the job — the segment whose task runs on a spec
    owned by this agent. Rank == segment.idx. Returns (None, None) if the agent has no rank here."""
    segs = (db.query(JobSegment).filter(JobSegment.job_id == job.id)
            .order_by(JobSegment.idx.asc()).all())
    for seg in segs:
        t = db.query(Task).filter(Task.id == seg.task_id).first()
        if not t:
            continue
        spec = db.query(SellerSpec).filter(SellerSpec.id == t.spec_id).first()
        if spec and spec.user_id == agent_user.id:
            return seg, seg.idx
    return None, None


def register_peer(db: Session, seg: "JobSegment", host: str, port: int, slots: int = 1):
    """Record a rank's VPN-reachable address so the whole cluster can be exported to the tools an
    org already runs (an MPI hostfile, a Ray address, a torchrun rendezvous endpoint)."""
    seg.peer_host = host
    seg.peer_port = int(port)
    seg.slots = max(1, int(slots or 1))
    db.add(seg); db.commit()
    return seg


def cluster_peers(db: Session, job: "MultiNodeJob"):
    """Every rank of a distributed job, ordered by rank, with its registered VPN address."""
    segs = (db.query(JobSegment).filter(JobSegment.job_id == job.id)
            .order_by(JobSegment.idx.asc()).all())
    return [{"rank": s.idx, "host": s.peer_host, "port": s.peer_port,
             "slots": (s.slots or 1), "is_master": s.idx == 0,
             "registered": bool(s.peer_host), "status": s.status} for s in segs]


def cluster_ready(db: Session, job: "MultiNodeJob") -> bool:
    """True once every rank has registered its address (the cluster is fully addressable)."""
    peers = cluster_peers(db, job)
    return bool(peers) and all(p["registered"] for p in peers)


def job_segments(db: Session, job_id: int):
    return (db.query(JobSegment).filter(JobSegment.job_id == job_id)
            .order_by(JobSegment.idx.asc()).all())



# ------------------ Idle fallback (earn when unrented) ------------------

def set_idle_fallback(db: Session, spec: "SellerSpec", enabled: bool) -> None:
    spec.idle_fallback = bool(enabled); db.add(spec); db.commit()


def record_idle_report(db: Session, spec: "SellerSpec", algo: str,
                       hashrate: float, est_daily_usd: float) -> None:
    spec.idle_algo = algo
    spec.idle_hashrate = hashrate
    spec.idle_est_daily_usd = est_daily_usd
    spec.idle_reported_at = _utcnow()
    db.add(spec); db.commit()



# ------------------ Idle-mining reconciliation (unified balance) ------------------

def spec_id_from_worker(worker_id: str):
    try:
        return int(worker_id.rsplit("-", 1)[-1])   # "pb-<spec_id>"
    except (ValueError, AttributeError):
        return None


def reconcile_idle_earnings(db: Session, earnings: dict, take_rate: float) -> dict:
    """earnings = {worker_id: {"period": str, "amount": float}} of SETTLED NiceHash
    payouts. Credits each seller's unified balance (amount * (1-take)); idempotent
    per (worker, period). Returns {credited_workers, seller_total, platform_total}."""
    credited = 0
    seller_total = Decimal(0)
    platform_total = Decimal(0)
    plat = get_or_create_platform(db)
    for worker_id, info in earnings.items():
        period = str(info.get("period"))
        gross = q(info.get("amount", 0))
        if gross <= 0:
            continue
        rec = IdleSettlement(worker_id=worker_id, period=period,
                             spec_id=spec_id_from_worker(worker_id), gross_usd=gross)
        db.add(rec)
        try:
            db.commit()                     # unique(worker,period) -> idempotent claim
        except IntegrityError:
            db.rollback()
            continue                        # already settled this period
        spec = db.query(SellerSpec).filter(SellerSpec.id == rec.spec_id).first()
        owner = db.query(User).filter(User.id == spec.user_id).first() if spec else None
        if not owner:
            continue
        seller_cut = q(gross * (Decimal(1) - D(take_rate)))
        platform_cut = q(gross - seller_cut)
        owner.earnings = q(D(owner.earnings) + seller_cut)
        plat.revenue = q(D(plat.revenue) + platform_cut)
        rec.credited_usd = seller_cut
        db.add_all([owner, plat, rec])
        post(db, "idle_mining", legs=[
            (EXTERNAL_MINING,          DEBIT,  gross),
            (acct_seller(owner.id),    CREDIT, seller_cut, owner.id),
            (PLATFORM_REVENUE,         CREDIT, platform_cut),
        ], reference_id=rec.id, description="idle mining settlement",
           idempotency_key=f"idle:{worker_id}:{period}", entry_type="idle_mining")
        db.commit()
        credited += 1
        seller_total += seller_cut
        platform_total += platform_cut
    return {"credited_workers": credited, "seller_total": q(seller_total),
            "platform_total": q(platform_total)}


def idle_credited_total(db: Session, spec_id: int) -> float:
    rows = db.query(IdleSettlement).filter(IdleSettlement.spec_id == spec_id).all()
    return round(sum(r.credited_usd for r in rows), 6)



# ------------------ Spare-disk rental (web3/BitTorrent storage) ------------------

DISK_PROVIDERS = {"storj", "btfs", "sia"}   # supported storage-network adapters


def disk_node_name(spec: "SellerSpec") -> str:
    """The UNIQUE node name this spec contributes storage under — the attribution key that maps
    a settled storage payout back to exactly one seller (like the NiceHash worker `pb-<id>`)."""
    return f"pbdisk-{spec.id}"


def spec_id_from_disk_node(node_id: str):
    try:
        return int(node_id.rsplit("-", 1)[-1])   # "pbdisk-<spec_id>"
    except (ValueError, AttributeError):
        return None


def set_disk_rental(db: Session, spec: "SellerSpec", enabled: bool,
                    provider: str = None, alloc_gb: int = None) -> None:
    """Turn a node's disk rental on/off and set its provider + GB cap. Enabling is EXPLICIT and
    requires real args — the caller (API) rejects enable without a provider AND a cap; this helper
    just persists what it's given. Disabling leaves the config so re-enabling is one click;
    delete_disk_rental clears it."""
    spec.disk_enabled = bool(enabled)
    if provider is not None:
        spec.disk_provider = provider
    if alloc_gb is not None:
        spec.disk_alloc_gb = max(0, int(alloc_gb))
    db.add(spec); db.commit()


def delete_disk_rental(db: Session, spec: "SellerSpec") -> None:
    """Cancel + delete: disable and clear the config (the agent then removes the node container
    and wipes its data dir on the next heartbeat)."""
    spec.disk_enabled = False
    spec.disk_provider = None
    spec.disk_alloc_gb = None
    spec.disk_used_gb = None
    spec.disk_est_daily_usd = None
    db.add(spec); db.commit()


def record_disk_report(db: Session, spec: "SellerSpec", provider: str,
                       used_gb: float, est_daily_usd: float) -> None:
    spec.disk_provider = provider or spec.disk_provider
    spec.disk_used_gb = used_gb
    spec.disk_est_daily_usd = est_daily_usd
    spec.disk_reported_at = _utcnow()
    db.add(spec); db.commit()


# ------------------ Model cache-locality (scheduler signal) ------------------

MAX_CACHED_MODELS = 2000


def set_spec_cached_models(db: Session, spec: "SellerSpec", model_ids) -> int:
    """Record which model ids a node holds locally (reported by the agent). Deduped, bounded, and
    charset-checked so a compromised agent can't inject junk. Returns the stored count."""
    import re
    clean, seen = [], set()
    for m in (model_ids or []):
        s = str(m or "").strip()
        # a model id is publisher/name or a bare alias — same safe charset as ids.py
        if not s or len(s) > 200 or s in seen:
            continue
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$", s) or ".." in s:
            continue
        seen.add(s)
        clean.append(s)
        if len(clean) >= MAX_CACHED_MODELS:
            break
    spec.cached_models = json.dumps(clean)
    spec.cached_models_at = _utcnow()
    db.add(spec); db.commit()
    return len(clean)


def spec_cached_models(spec: "SellerSpec") -> list:
    try:
        v = json.loads(spec.cached_models) if spec.cached_models else []
        return v if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


def node_has_model_cached(spec: "SellerSpec", model_id: str) -> bool:
    return model_id in spec_cached_models(spec)


def specs_with_model_cached(db: Session, model_id: str):
    """Online specs that already hold `model_id` locally (the cache-locality candidates)."""
    rows = (db.query(SellerSpec)
            .filter(SellerSpec.cached_models.isnot(None), SellerSpec.status == "online").all())
    return [s for s in rows if node_has_model_cached(s, model_id)]


def rank_specs_for_model(specs, model_id: str):
    """Stable-partition candidate specs so those that already hold `model_id` come first (all other
    scheduling constraints being equal). Pure — the scheduler calls this as a final tiebreaker so a
    20-100 GB weight file isn't re-downloaded when an equally-good node already has it."""
    if not model_id:
        return list(specs)
    cached, rest = [], []
    for s in specs:
        (cached if node_has_model_cached(s, model_id) else rest).append(s)
    return cached + rest


def reconcile_disk_earnings(db: Session, earnings: dict, take_rate: float) -> dict:
    """earnings = {node_id: {"period": str, "amount": float, "provider": str}} of SETTLED storage
    payouts. Credits each seller's unified balance (amount * (1-take)); idempotent per
    (node, period). Same shape/guarantees as reconcile_idle_earnings."""
    credited = 0
    seller_total = Decimal(0)
    platform_total = Decimal(0)
    plat = get_or_create_platform(db)
    for node_id, info in earnings.items():
        period = str(info.get("period"))
        gross = q(info.get("amount", 0))
        if gross <= 0:
            continue
        rec = DiskSettlement(node_id=node_id, period=period,
                             spec_id=spec_id_from_disk_node(node_id),
                             provider=info.get("provider"), gross_usd=gross)
        db.add(rec)
        try:
            db.commit()                     # unique(node,period) -> idempotent claim
        except IntegrityError:
            db.rollback()
            continue                        # already settled this period
        spec = db.query(SellerSpec).filter(SellerSpec.id == rec.spec_id).first()
        owner = db.query(User).filter(User.id == spec.user_id).first() if spec else None
        if not owner:
            continue
        seller_cut = q(gross * (Decimal(1) - D(take_rate)))
        platform_cut = q(gross - seller_cut)
        owner.earnings = q(D(owner.earnings) + seller_cut)
        plat.revenue = q(D(plat.revenue) + platform_cut)
        rec.credited_usd = seller_cut
        db.add_all([owner, plat, rec])
        post(db, "disk_rental", legs=[
            (EXTERNAL_STORAGE,         DEBIT,  gross),
            (acct_seller(owner.id),    CREDIT, seller_cut, owner.id),
            (PLATFORM_REVENUE,         CREDIT, platform_cut),
        ], reference_id=rec.id, description="disk rental settlement",
           idempotency_key=f"disk:{node_id}:{period}", entry_type="disk_rental")
        db.commit()
        credited += 1
        seller_total += seller_cut
        platform_total += platform_cut
    return {"credited_nodes": credited, "seller_total": q(seller_total),
            "platform_total": q(platform_total)}


def disk_credited_total(db: Session, spec_id: int) -> float:
    rows = db.query(DiskSettlement).filter(DiskSettlement.spec_id == spec_id).all()
    return round(sum(r.credited_usd for r in rows), 6)



# ------------------ Issued key tracking (for the UI) ------------------

def record_issued_key(db: Session, user_id: int, jti: str, label: str,
                      scopes: list, days: int):
    from datetime import timedelta
    k = IssuedKey(user_id=user_id, jti=jti, label=label,
                  scopes=",".join(scopes) if scopes else "",
                  expires_at=_utcnow() + timedelta(days=days))
    db.add(k); db.commit(); db.refresh(k)
    return k


def list_issued_keys(db: Session, user_id: int):
    rows = (db.query(IssuedKey).filter(IssuedKey.user_id == user_id)
            .order_by(IssuedKey.id.desc()).all())
    revoked = {r.jti for r in db.query(RevokedApiKey).all()}
    return [{"jti": k.jti, "label": k.label, "scopes": k.scopes,
             "created_at": str(k.created_at), "expires_at": str(k.expires_at),
             "revoked": k.jti in revoked} for k in rows]


# ------------------ Google / passwordless users ------------------

def get_or_create_oauth_user(db: Session, email: str, provider: str = "google",
                             email_verified: bool = False) -> "User":
    # `email_verified` should reflect the PROVIDER's verification claim (e.g. Google's
    # `email_verified`), NOT a dev stub. A provider-verified email is a trusted identity
    # (it gates payouts and the admin allowlist), so honour it — but only ever UPGRADE a
    # user's flag, never downgrade one that was verified another way.
    u = db.query(User).filter(User.username == email).first()
    if u:
        changed = False
        if not u.email:
            u.email = email; changed = True
        if email_verified and not u.email_verified:
            u.email_verified = True; changed = True
        if changed:
            db.add(u); db.commit()
        return u
    import secrets as _s
    u = User(username=email, email=email, email_verified=bool(email_verified),
             password=hash_password("oauth:" + provider + ":" + _s.token_hex(16)),
             role="buyer")
    db.add(u); db.commit(); db.refresh(u)
    return u


# Build the schema on import (create_all + idempotent _ensure_* passes) — the runtime bootstrap.
# Alembic sets PETABYTE_SKIP_INIT_DB=1 so it can own schema creation during a migration run
# instead of it happening as an import side-effect. Default (unset) preserves prior behavior.
if os.getenv("PETABYTE_SKIP_INIT_DB", "").strip().lower() not in ("1", "true", "yes", "on"):
    init_db()


# ---------------------------------------------------------------------------
# Email verification.
# The point is NOT ceremony. It is that when a seller's machine starts emitting
# abuse traffic at 2am, you need to be able to reach a human. No verified email
# means no incident contact, no password reset, and no way to warn a host that
# their node is compromised.
# ---------------------------------------------------------------------------
EMAIL_TOKEN_TTL_MIN = int(os.getenv("EMAIL_TOKEN_TTL_MIN", "15"))
_DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "getnada.com",
    "temp-mail.org", "sharklasers.com", "dispostable.com", "fakeinbox.com",
}


def is_disposable_email(email: str) -> bool:
    return bool(email) and email.rsplit("@", 1)[-1].lower() in _DISPOSABLE


def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def start_email_verification(db: Session, user: "User", email: str):
    """Returns the RAW token (emailed to the user). Only its hash is stored."""
    tok = secrets.token_urlsafe(32)
    user.email = email
    user.email_verified = False
    user.email_token = _hash_token(tok)
    user.email_token_exp = _utcnow() + timedelta(minutes=EMAIL_TOKEN_TTL_MIN)
    db.add(user)
    db.commit()
    return tok


def confirm_email(db: Session, username: str, token: str) -> bool:
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.email_token or not u.email_token_exp:
        return False
    exp = u.email_token_exp
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < _utcnow():
        return False                                  # expired
    if not secrets.compare_digest(u.email_token, _hash_token(token)):
        return False                                  # wrong token, constant-time
    u.email_verified = True
    u.email_token = None                              # single use
    u.email_token_exp = None
    db.add(u)
    audit(db, "email.verified", actor=u, resource_type="user", resource_id=u.id,
          commit=False)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Payout destination changes = THE fraud vector in a marketplace. Take over an
# account, swap the bank details, drain the earnings. So: a new destination is
# quarantined for a cooling-off period before it can receive money, and the change
# is always audited.
# ---------------------------------------------------------------------------
PAYOUT_COOLING_OFF_H = int(os.getenv("PAYOUT_COOLING_OFF_H", "24"))


def payout_method_is_cooled_off(method) -> bool:
    created = getattr(method, "created_at", None)
    if not created:
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (_utcnow() - created) >= timedelta(hours=PAYOUT_COOLING_OFF_H)


def redact_destination(dest: str) -> str:
    """Never show a full bank/wallet destination back to anyone, ever."""
    if not dest:
        return ""
    if "@" in dest:
        name, _, dom = dest.partition("@")
        return (name[:2] + "***@" + dom) if len(name) > 2 else ("***@" + dom)
    return ("*" * max(0, len(dest) - 4)) + dest[-4:]
