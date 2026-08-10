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
    is_demo = Column(Boolean, default=False, nullable=False, index=True)  # seeded demo node


def trust_level_for(spec: "SellerSpec") -> dict:
    """The honest trust ladder for a listing. A level is awarded ONLY when its
    technical requirement is actually satisfied by evidence we hold:

      self_reported       registered via the API; nothing proven.
      agent_verified      the node's agent signed a hardware report with its
                          Ed25519 device key (/prove) — proves a keyholder on the
                          node claims this hardware, NOT that the silicon is real.
      benchmark_verified  agent_verified + a signed benchmark result exists, so
                          throughput was measured, not declared.

    'hardware_attested' (real vendor TEE chain: NVIDIA NRAS / AMD SEV-SNP / Intel
    TDX) is deliberately NOT awardable today: the current verifier is a structural
    stub (stub.md #3). spec.confidential therefore surfaces separately as
    'cc_pilot' evidence and must never be marketed as hardware attestation."""
    if not spec.attested:
        return {"level": "self_reported", "rank": 0, "label": "Self-reported",
                "evidence": "Listing details supplied by the seller; no proof held."}
    if spec.benchmark_tokens_sec:
        return {"level": "benchmark_verified", "rank": 2, "label": "Benchmark-verified",
                "evidence": "Agent-signed hardware report + a signed benchmark "
                            f"({round(spec.benchmark_tokens_sec)} tok/s) on record."}
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
    created_at = Column(DateTime, default=_utcnow, index=True)


def audit(db: Session, action: str, actor=None, actor_type="user", resource_type=None,
          resource_id=None, ip=None, request_id=None, detail=None, commit=True):
    """Write an audit event. Never log secrets, tokens, or full payout destinations."""
    ev = AuditEvent(
        actor_user_id=getattr(actor, "id", None),
        actor_username=getattr(actor, "username", None),
        actor_type=actor_type, action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        ip_address=ip, request_id=request_id,
        detail=json.dumps(detail) if isinstance(detail, dict) else detail)
    db.add(ev)
    if commit:
        db.commit()
    return ev


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
    fx_rate = Column(Float, nullable=True)
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
        deposit(db, user, topup.amount_minor / 100.0)   # minor -> major (2-dp currencies)
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
                  ("is_demo", "BOOLEAN NOT NULL DEFAULT false")],
        "users": [("referral_code", "VARCHAR"), ("referred_by", "INTEGER"),
                  ("referral_rewarded", "BOOLEAN DEFAULT false"),
                  ("referral_signup_meta", "VARCHAR"),("email_verified", "BOOLEAN DEFAULT false"), ("email_token", "VARCHAR"),
                  ("email_token_exp", "TIMESTAMP"),
                  ("is_demo", "BOOLEAN NOT NULL DEFAULT false")],
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
        "connected_accounts": [("gateway_mode", "VARCHAR")],
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
        import datetime as _dt
        month_start = _dt.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
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
