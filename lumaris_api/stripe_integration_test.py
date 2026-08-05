"""stripe_integration_test.py — OPT-IN integration test against REAL Stripe TEST mode.

Unlike stripe_test.py (offline, FakeStripeGateway), this drives the real Stripe SDK with
TEST-mode keys to prove that the configured keys authenticate and that GENUINE Stripe
test objects are created (acct_/pi_) — not fabricated IDs. It complements, and never
replaces, the offline suite that exercises the full state machine deterministically.

Marker: requires_stripe_credentials.

SAFETY:
  * SKIPS cleanly (exit 0) when STRIPE_SECRET_KEY is unset — so CI without secrets,
    forks, and offline dev are unaffected.
  * HARD-REFUSES to run on anything but a test key (must start with sk_test_). It never
    touches live mode; assert_test_mode() is the backstop.
  * Prints only object IDs (acct_/pi_), never key material.

Requires: STRIPE_SECRET_KEY=sk_test_...  (optionally STRIPE_PUBLISHABLE_KEY=pk_test_...).
Run:      python stripe_integration_test.py
CI:       runs in the `stripe-integration` job when the repo secrets are present.
"""
import os
import sys
import time

# --- skip/refuse BEFORE importing anything heavy, so the skip path needs no deps ---
_sk = os.getenv("STRIPE_SECRET_KEY", "")
_pk = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
if not _sk:
    print("SKIP: STRIPE_SECRET_KEY not set — integration test needs Stripe TEST creds. "
          "(This is expected in CI without secrets, in forks, and offline.)")
    sys.exit(0)
if not _sk.startswith("sk_test_"):
    print("REFUSING: STRIPE_SECRET_KEY is not a TEST key (must start with sk_test_). "
          "Integration tests must NEVER run against live mode.")
    sys.exit(1)
if _pk and not _pk.startswith("pk_test_"):
    print("REFUSING: STRIPE_PUBLISHABLE_KEY is not a TEST key (pk_test_).")
    sys.exit(1)

# Force the REAL gateway (the whole point of this suite) and keep the app importable.
os.environ["STRIPE_GATEWAY"] = "real"
os.environ.setdefault("STRIPE_MODE", "test")

from stripe_gateway import RealStripeGateway, assert_test_mode  # noqa: E402

# Backstop: hard-fail if a live key somehow slipped through the checks above.
assert_test_mode()

_uniq = f"{int(time.time())}-{os.getpid()}"
gw = RealStripeGateway()

PASSES = FAILS = 0
def ok(label, cond):
    global PASSES, FAILS
    print(("PASS " if cond else "FAIL ") + label)
    if cond:
        PASSES += 1
    else:
        FAILS += 1

# 1) Auth + Connect: create + retrieve a genuine test-mode connected account.
acct = gw.create_account(country="US", email=f"integration+{_uniq}@petabyte.test",
                         metadata={"petabyte_integration": _uniq},
                         idempotency_key=f"pb-int-acct-{_uniq}")
ok("real Stripe TEST connected account created (acct_)",
   isinstance(acct.get("id"), str) and acct["id"].startswith("acct_"))
got = gw.retrieve_account(acct["id"])
ok("connected account retrievable from Stripe", got.get("id") == acct["id"])

# 2) PaymentIntents API reachable: create a manual-capture PI (separate charges/transfers).
pi = gw.create_payment_intent(amount=500, currency="usd",
                              metadata={"petabyte_integration": _uniq},
                              transfer_group=f"pb-int-{_uniq}",
                              idempotency_key=f"pb-int-pi-{_uniq}",
                              capture_method="manual")
ok("real Stripe TEST PaymentIntent created (pi_)",
   isinstance(pi.get("id"), str) and pi["id"].startswith("pi_"))
ok("PaymentIntent is manual-capture (separate charges & transfers)",
   pi.get("capture_method") == "manual")

# 3) Idempotency is real: the same key returns the SAME PaymentIntent, not a second one.
pi2 = gw.create_payment_intent(amount=500, currency="usd",
                               metadata={"petabyte_integration": _uniq},
                               transfer_group=f"pb-int-{_uniq}",
                               idempotency_key=f"pb-int-pi-{_uniq}",
                               capture_method="manual")
ok("idempotency key returns the same PaymentIntent (no duplicate charge)",
   pi2.get("id") == pi["id"])

print(f"\n=== stripe integration (REAL test mode): {PASSES} passed, {FAILS} failed ===")
print(f"    proof objects: account={acct.get('id')} paymentintent={pi.get('id')}")
sys.exit(1 if FAILS else 0)
