from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, update, event,
)
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import bcrypt
import hashlib
import json
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
PLATFORM_TAKE_RATE = float(os.getenv("PLATFORM_TAKE_RATE", "0.10"))
HEARTBEAT_TIMEOUT_S = int(os.getenv("HEARTBEAT_TIMEOUT_S", "60"))
MIN_REPUTATION = int(os.getenv("MIN_REPUTATION", "50"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    balance = Column(Float, default=0.0, nullable=False)    # buyer spendable credits
    earnings = Column(Float, default=0.0, nullable=False)   # seller accrued payouts


class SellerSpec(Base):
    __tablename__ = "specs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    cpu = Column(Integer, nullable=False)
    ram = Column(Integer, nullable=False)            # GB
    gpu_model = Column(String, nullable=True)
    gpu_count = Column(Integer, default=0)
    vram_gb = Column(Integer, default=0)
    price_per_hour = Column(Float, nullable=False)   # USD/hr
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
    price_per_hour = Column(Float, nullable=False)
    gross_amount = Column(Float, nullable=False)
    platform_fee = Column(Float, nullable=False)
    seller_payout = Column(Float, nullable=False)
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
    balance = Column(Float, default=0.0, nullable=False)
    budget_cap = Column(Float, default=0.0, nullable=False)   # 0 = unlimited
    spent = Column(Float, default=0.0, nullable=False)
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
    amount_usd = Column(Float, nullable=False)
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
    min_amount = Column(Float, default=1.0)          # skip if balance below this
    enabled = Column(Boolean, default=True)
    next_run_at = Column(DateTime, nullable=False)
    last_run_at = Column(DateTime, nullable=True)


class LedgerEntry(Base):
    """Append-only money movement record. Never updated/deleted -> auditable."""
    __tablename__ = "ledger"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    account = Column(String, nullable=False)      # buyer|seller|platform|external
    entry_type = Column(String, nullable=False)   # deposit|escrow_hold|release_seller|release_platform|refund_buyer
    amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class Platform(Base):
    __tablename__ = "platform"
    id = Column(Integer, primary_key=True)
    revenue = Column(Float, default=0.0, nullable=False)


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
    gross_usd = Column(Float, default=0.0)
    credited_usd = Column(Float, default=0.0)
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

def init_db():
    Base.metadata.create_all(bind=engine)


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
    gross = round(spec.price_per_hour * hours, 4)
    fee = round(gross * take_rate, 4)
    payout = round(gross - fee, 4)
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
        rec.response = json.dumps(response)
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
    user.balance = round(user.balance + amount, 4)
    db.add(user)
    db.add(LedgerEntry(user_id=user.id, account="buyer", entry_type="deposit", amount=amount))
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
    gross = round(spec.price_per_hour * hours, 4)
    fee = round(gross * take_rate, 4)
    payout = round(gross - fee, 4)
    booking = Booking(
        buyer_id=buyer.id, seller_id=spec.user_id, spec_id=spec.id,
        hours=hours, price_per_hour=spec.price_per_hour,
        gross_amount=gross, platform_fee=fee, seller_payout=payout,
        status="escrowed", vpn=vpn, org_id=org_id,
    )
    db.add(booking); db.commit(); db.refresh(booking)
    db.add(LedgerEntry(booking_id=booking.id, user_id=buyer.id, account="escrow",
                       entry_type="escrow_hold", amount=gross))
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
    seller.earnings = round(seller.earnings + b.seller_payout, 4)
    plat.revenue = round(plat.revenue + b.platform_fee, 4)
    db.add_all([seller, plat])
    db.add(LedgerEntry(booking_id=b.id, user_id=seller.id, account="seller",
                       entry_type="release_seller", amount=b.seller_payout))
    db.add(LedgerEntry(booking_id=b.id, account="platform",
                       entry_type="release_platform", amount=b.platform_fee))
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
        buyer.balance = round(buyer.balance + b.gross_amount, 4)
        db.add(buyer)
    release_unit(db, b.spec_id)  # give the reserved unit back
    db.add(LedgerEntry(booking_id=b.id, user_id=buyer.id, account="buyer",
                       entry_type="refund_buyer", amount=b.gross_amount))
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
    org.balance = round(org.balance + amount, 4)
    db.add(org)
    db.add(LedgerEntry(account="org", entry_type="deposit", amount=amount))
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
    total = 0.0
    for b in bks:
        by_status[b.status] = round(by_status.get(b.status, 0.0) + b.gross_amount, 4)
        by_spec[b.spec_id] = round(by_spec.get(b.spec_id, 0.0) + b.gross_amount, 4)
        total += b.gross_amount
    return {"total_spend": round(total, 4), "bookings": len(bks),
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

def try_debit_earnings(db: Session, user_id: int, amount: float) -> bool:
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
    p = Payout(user_id=user.id, method_id=method.id, amount_usd=round(amount, 2),
               kind=method.kind, status="requested")
    db.add(p); db.commit(); db.refresh(p)
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
            request_payout(db, user, method, round(user.earnings, 2))
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
    seller_total = 0.0
    platform_total = 0.0
    plat = get_or_create_platform(db)
    for worker_id, info in earnings.items():
        period = str(info.get("period"))
        gross = round(float(info.get("amount", 0.0)), 6)
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
        seller_cut = round(gross * (1.0 - take_rate), 6)
        platform_cut = round(gross - seller_cut, 6)
        owner.earnings = round((owner.earnings or 0.0) + seller_cut, 6)
        plat.revenue = round((plat.revenue or 0.0) + platform_cut, 6)
        rec.credited_usd = seller_cut
        db.add_all([owner, plat, rec])
        db.add(LedgerEntry(account="idle_mining", entry_type="idle_mining",
                           amount=seller_cut, user_id=owner.id))
        db.commit()
        credited += 1
        seller_total += seller_cut
        platform_total += platform_cut
    return {"credited_workers": credited, "seller_total": round(seller_total, 6),
            "platform_total": round(platform_total, 6)}


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
