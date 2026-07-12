from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, update, event, Numeric,
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
    notify_email = Column(Boolean, default=True)
    tests_passed = Column(Integer, default=0, nullable=False)
    tests_failed = Column(Integer, default=0, nullable=False)
    can_accept_paid_jobs = Column(Boolean, default=True, nullable=False)
    balance = Column(Money, default=Decimal(0), nullable=False)   # buyer spendable credits
    earnings = Column(Money, default=Decimal(0), nullable=False)  # seller accrued payouts


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
    amount_usd = Column(Money, nullable=False)
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


# ---- account naming ----------------------------------------------------------
DEBIT, CREDIT = "debit", "credit"


def acct_buyer(uid):      return f"buyer_available:{uid}"
def acct_escrow(bid):     return f"escrow:{bid}"
def acct_seller(uid):     return f"seller_earnings:{uid}"
def acct_org(oid):        return f"org_available:{oid}"
PLATFORM_REVENUE   = "platform_revenue"
EXTERNAL_PAYMENTS  = "external:payments"    # the card processor
EXTERNAL_PAYOUTS   = "external:payouts"     # the bank / USDC rail
EXTERNAL_MINING    = "external:mining"      # NiceHash


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


class Platform(Base):
    __tablename__ = "platform"
    id = Column(Integer, primary_key=True)
    revenue = Column(Money, default=Decimal(0), nullable=False)


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


class MultiNodeJob(Base):
    """A fan-out job (render frames / transcode segments) assembled from N parts."""
    __tablename__ = "multinode_jobs"
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)              # render|transcode
    params = Column(Text, nullable=True)
    total_segments = Column(Integer, default=0)
    status = Column(String, default="running")         # running|assembling|complete|failed
    output_ref = Column(String, nullable=True)
    stitch_task_id = Column(Integer, nullable=True)
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


# ------------------ Session plumbing ------------------

def _ensure_columns():
    """Forward-migrate columns added to a model AFTER its table already exists.
    create_all() only creates missing TABLES, never columns — so on an older DB a
    newly-added column (e.g. bookings.test) is absent and every query on that table
    500s. This idempotently adds known-missing columns. Safe on SQLite and Postgres."""
    from sqlalchemy import inspect as _inspect, text as _text
    wanted = {
        "bookings": [("test", "BOOLEAN NOT NULL DEFAULT true")],
        "specs": [("min_price", "FLOAT"), ("max_price", "FLOAT"),
                  ("auto_price", "BOOLEAN DEFAULT false"), ("public_id", "VARCHAR")],
        "vm_routes": [("hourly_rate", "FLOAT DEFAULT 0"), ("started_at", "TIMESTAMP"),
                      ("paid_until", "TIMESTAMP"), ("stopped_at", "TIMESTAMP")],
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


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    _ensure_indexes()
    _backfill_public_ids()


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
    """Move each opted-in spec's price with demand for its GPU class, clamped to
    [min_price, max_price] and always kept below the cloud reference. Opt-in only,
    always within the seller's own bounds. Returns count repriced."""
    ref = reference_price if reference_price is not None else \
        float(os.getenv("AWS_REFERENCE_PRICE", "12.29"))
    busy_by, total_by = {}, {}
    for s in db.query(SellerSpec).filter(SellerSpec.attested == True).all():  # noqa: E712
        if not spec_is_live(s):
            continue
        key = (s.gpu_model or "cpu").lower()
        total = s.total_units or 1
        busy = max(0, total - (s.available_units or 0))
        busy_by[key] = busy_by.get(key, 0) + busy
        total_by[key] = total_by.get(key, 0) + total
    n = 0
    for s in db.query(SellerSpec).filter(SellerSpec.auto_price == True).all():  # noqa: E712
        if s.min_price is None or s.max_price is None or s.max_price < s.min_price:
            continue
        key = (s.gpu_model or "cpu").lower()
        total = total_by.get(key, 1)
        util = (busy_by.get(key, 0) / total) if total else 0.0     # 0..1
        mult = D("0.85") + D("0.40") * D(util)          # idle 0.85x -> full 1.25x
        base = (D(s.min_price) + D(s.max_price)) / Decimal(2)
        price = max(D(s.min_price), min(D(s.max_price), base * mult))
        price = qc(min(price, D(ref) * D("0.95")))     # never >= cloud reference
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

def revoke_jti(db: Session, jti: str) -> None:
    if not db.query(RevokedApiKey).filter(RevokedApiKey.jti == jti).first():
        db.add(RevokedApiKey(jti=jti)); db.commit()


def is_jti_revoked(db: Session, jti: str) -> bool:
    return db.query(RevokedApiKey).filter(RevokedApiKey.jti == jti).first() is not None


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
                       status: str = "completed") -> None:
    task.result = result
    task.status = status if status in ("completed", "failed", "running") else "completed"
    task.completed_at = _utcnow()
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
    import random as _random
    size = _DIFFICULTY_SIZE.get(difficulty, 5000)
    seed = _random.randint(1, 2_000_000_000)
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
    db.add(spec); db.commit()



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

def set_benchmark(db: Session, spec: "SellerSpec", tokens_sec: float, meta: dict) -> None:
    import json as _json
    spec.benchmark_tokens_sec = tokens_sec
    spec.benchmark_meta = _json.dumps(meta or {})
    spec.benchmark_at = _utcnow()
    db.add(spec); db.commit()


def create_benchmark_task(db: Session, spec: "SellerSpec"):
    task = Task(spec_id=spec.id, task_type="benchmark", status="pending", priority=5)
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


def request_payout(db: Session, user: "User", method: "SellerPayoutMethod",
                   amount: float) -> "Payout":
    """Atomically debit earnings and enqueue a payout. Returns None if short."""
    if amount <= 0 or not method.verified:
        return None
    if not try_debit_earnings(db, user.id, amount):
        return None
    p = Payout(user_id=user.id, method_id=method.id, amount_usd=qc(amount),
               kind=method.kind, status="requested")
    db.add(p); db.flush()
    # money LEAVES the system: seller earnings drain to the external payout rail.
    # This was previously not ledgered at all — earnings simply vanished from the books.
    post(db, "payout", legs=[
        (acct_seller(user.id), DEBIT,  qc(amount), user.id),
        (EXTERNAL_PAYOUTS,     CREDIT, qc(amount)),
    ], reference_id=p.id, description=f"payout via {method.kind}",
       entry_type="payout")
    db.commit(); db.refresh(p)
    return p


def set_payout_status(db: Session, payout: "Payout", status: str,
                      provider_ref: str = None, reason: str = None) -> None:
    payout.status = status
    payout.updated_at = _utcnow()
    if provider_ref:
        payout.provider_ref = provider_ref
    if reason:
        payout.reason = reason
    db.add(payout); db.commit()
    if status == "failed":                       # return the money on failure
        credit_earnings(db, payout.user_id, payout.amount_usd)


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
        if user and method and method.verified and (user.earnings or 0) >= sch.min_amount:
            request_payout(db, user, method, qc(user.earnings))
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

def get_or_create_oauth_user(db: Session, email: str, provider: str = "google") -> "User":
    u = db.query(User).filter(User.username == email).first()
    if u:
        if not u.email:
            u.email = email; db.add(u); db.commit()
        return u
    import secrets as _s
    u = User(username=email, email=email,
             password=hash_password("oauth:" + provider + ":" + _s.token_hex(16)),
             role="buyer")
    db.add(u); db.commit(); db.refresh(u)
    return u


init_db()
