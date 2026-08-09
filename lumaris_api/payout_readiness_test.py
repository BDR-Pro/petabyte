"""payout_readiness_test.py — the provider-agnostic seller eligibility pivot.

Proves the core business rule is now "seller has >= 1 verified, enabled, payout-ready RAIL",
NOT "Stripe Connect account is payout-ready":

  * readiness matrix per Connect account state (ready / restricted / capabilities-pending /
    verification-required / no-rail);
  * a FUTURE rail can make a seller eligible with NO Connect account (extensibility);
  * authorize() depends on the centralized service — a Connect-ready seller is still REFUSED
    when the service says not-ready, and accepted when it says ready.

Offline only: forced SQLite + FakeStripeGateway. Run: python payout_readiness_test.py
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./payout_readiness_test.db"
os.environ["SECRET_KEY"] = "test-jwt-secret"
os.environ["SERVER_PRIVATE_KEY"] = __import__(
    "cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
os.environ["PAYMENT_WEBHOOK_SECRET"] = "whsec_legacy"
os.environ["WG_PUBLIC_KEY"] = "x"; os.environ["WG_ENDPOINT"] = "y"
os.environ["STRIPE_GATEWAY"] = "fake"
os.environ["REAPER_DISABLED"] = "true"

for f in ("payout_readiness_test.db", "payout_readiness_test.db-wal", "payout_readiness_test.db-shm"):
    if os.path.exists(f):
        os.remove(f)

import datetime as _dt  # noqa: E402

import db as dbmod  # noqa: E402
from stripe_gateway import FakeStripeGateway, set_gateway  # noqa: E402
import stripe_connect as sc  # noqa: E402
import payout_readiness as pr  # noqa: E402

set_gateway(FakeStripeGateway())
dbmod.init_db()

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


PW = "hunter2-correct-horse-xyz"
_uid = [0]


def new_seller():
    _uid[0] += 1
    return dbmod.create_user(dbmod_session, f"pr_seller{_uid[0]}", PW)


dbmod_session = dbmod.SessionLocal()


def mk_ca(seller_id, **fields):
    # Default to a FRESH sync time so capability-based reasons surface (a None/old sync would
    # fail closed as readiness_stale). The stale case below overrides last_synced_at explicitly.
    fields.setdefault("last_synced_at", _dt.datetime.now(_dt.timezone.utc))
    ca = dbmod.ConnectedAccount(
        user_id=seller_id, stripe_account_id=f"acct_fake_pr{seller_id}",
        gateway_mode="fake", onboarding_state="created", **fields)
    dbmod_session.add(ca); dbmod_session.commit()
    return ca


# ---- no rail at all -> not ready ----
s0 = new_seller()
r = pr.get_seller_payout_readiness(dbmod_session, s0)
ok("no payout rail -> not ready, reason=no_payout_rail",
   r["ready"] is False and r["reason"] == "no_payout_rail" and r["rail"] is None)

# ---- Connect fully ready -> ready via stripe_connect ----
s1 = new_seller()
mk_ca(s1.id, details_submitted=True, charges_enabled=True, payouts_enabled=True,
      transfers_capability="active", country="US")
r = pr.get_seller_payout_readiness(dbmod_session, s1)
ok("Connect ready -> ready via rail=stripe_connect",
   r["ready"] is True and r["rail"] == "stripe_connect" and r["provider"] == "stripe"
   and r["reason"] is None and r["country"] == "US")
ok("is_seller_payout_ready bool matches (ready seller)",
   pr.is_seller_payout_ready(dbmod_session, s1.id) is True)
ok("get_seller_payout_readiness accepts a bare seller_id too",
   pr.get_seller_payout_readiness(dbmod_session, s1.id)["ready"] is True)

# ---- Connect restricted (disabled_reason) -> not ready ----
s2 = new_seller()
mk_ca(s2.id, details_submitted=True, charges_enabled=False, payouts_enabled=False,
      transfers_capability="inactive", disabled_reason="requirements.past_due")
r = pr.get_seller_payout_readiness(dbmod_session, s2)
ok("Connect restricted -> not ready, reason=restricted",
   r["ready"] is False and r["reason"] == "restricted" and "restricted" in r["why_blocked"].lower())

# ---- Connect capabilities pending (submitted, caps not active) -> not ready ----
s3 = new_seller()
mk_ca(s3.id, details_submitted=True, charges_enabled=True, payouts_enabled=False,
      transfers_capability="pending")
r = pr.get_seller_payout_readiness(dbmod_session, s3)
ok("Connect capabilities pending -> not ready, reason=capabilities_pending",
   r["ready"] is False and r["reason"] == "capabilities_pending")

# ---- Connect verification required (not submitted) -> not ready ----
s4 = new_seller()
mk_ca(s4.id, details_submitted=False, charges_enabled=False, payouts_enabled=False,
      requirements_due='["individual.id_number"]')
r = pr.get_seller_payout_readiness(dbmod_session, s4)
ok("Connect not onboarded -> not ready, reason=verification_required",
   r["ready"] is False and r["reason"] == "verification_required"
   and "individual.id_number" in r["requirements_due"])

# ---- STALE provider state (capable, but last synced long ago) -> FAIL CLOSED ----
s_stale = new_seller()
mk_ca(s_stale.id, details_submitted=True, charges_enabled=True, payouts_enabled=True,
      transfers_capability="active",
      last_synced_at=_dt.datetime(2000, 1, 1, tzinfo=_dt.timezone.utc))
r = pr.get_seller_payout_readiness(dbmod_session, s_stale)
ok("stale provider state -> not ready, reason=readiness_stale (fail closed)",
   r["ready"] is False and r["reason"] == "readiness_stale" and r["stale"] is True)

# ---- EXTENSIBILITY: a future rail makes a seller eligible with NO Connect account ----
s5 = new_seller()   # no ConnectedAccount at all
def _future_rail(db, seller_id, **_):
    if seller_id == s5.id:
        return {"ready": True, "provider": "future", "rail": "future_rail",
                "country": "SA", "reason": None, "why_blocked": None,
                "requirements_due": [], "requirements_past_due": []}
    return None
_orig_resolvers = pr._RAIL_RESOLVERS
pr._RAIL_RESOLVERS = (pr._connect_rail_readiness, _future_rail)
try:
    r = pr.get_seller_payout_readiness(dbmod_session, s5)
    ok("a FUTURE rail makes a seller eligible with NO Connect account (abstraction works)",
       r["ready"] is True and r["rail"] == "future_rail" and r["provider"] == "future")
finally:
    pr._RAIL_RESOLVERS = _orig_resolvers

dbmod_session.close()


# ---- authorize() depends on the SERVICE, not on Connect directly ----
# Build a Connect-READY seller + attested/online spec + buyer, then flip the service verdict.
s = dbmod.SessionLocal()
seller = dbmod.create_user(s, "pr_auth_seller", PW)
buyer = dbmod.create_user(s, "pr_auth_buyer", PW)
mk_ca_seller = dbmod.ConnectedAccount(
    user_id=seller.id, stripe_account_id="acct_fake_prauth", gateway_mode="fake",
    onboarding_state="enabled", details_submitted=True, charges_enabled=True,
    payouts_enabled=True, transfers_capability="active", country="US",
    last_synced_at=_dt.datetime.now(_dt.timezone.utc))
s.add(mk_ca_seller)
spec = dbmod.save_specs(s, seller, {"cpu": 8, "ram": 32, "duration": 24, "price_per_hour": 2.0,
                                    "provider": "pr_auth_seller", "gpu_model": "NVIDIA L4",
                                    "gpu_count": 1, "vram_gb": 24, "units": 2})
spec.attested = True
spec.attest_pubkey = "x"
spec.status = "online"
spec.last_seen = _dt.datetime.now(_dt.timezone.utc)
s.add(spec); s.commit()

# sanity: with the real service, the Connect-ready seller IS eligible -> authorize succeeds
ok("baseline: Connect-ready seller is eligible via the service",
   pr.is_seller_payout_ready(s, seller.id) is True)
tx = sc.authorize(s, buyer, spec, 60)
ok("authorize SUCCEEDS for a service-ready seller", tx is not None and tx.status)

# now the service says NOT ready (e.g. a rail-level restriction) even though Connect looks fine:
# authorize must refuse — proving marketplace eligibility flows through the service.
_orig_ready = pr.get_seller_payout_readiness
pr.get_seller_payout_readiness = lambda db, seller, **kw: {
    "ready": False, "provider": "stripe", "rail": "stripe_connect", "rail_mode": "fake",
    "country": "US", "stale": False, "synced_at": None, "reason": "capabilities_pending",
    "why_blocked": "x", "requirements_due": [], "requirements_past_due": []}
_refused = False
try:
    sc.authorize(s, buyer, spec, 60)
except sc.TransactionError as e:
    _refused = "payout-ready" in str(e)
finally:
    pr.get_seller_payout_readiness = _orig_ready
ok("authorize REFUSES when the readiness SERVICE says not-ready (even with a ready Connect acct)",
   _refused)
s.close()

for f in ("payout_readiness_test.db", "payout_readiness_test.db-wal", "payout_readiness_test.db-shm"):
    try:
        os.remove(f)
    except OSError:
        pass

print(f"\n=== payout_readiness: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
