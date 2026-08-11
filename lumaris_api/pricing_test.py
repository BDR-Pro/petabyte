"""Offline unit tests for pricing-config validation + the absolute charge ceiling.

Money-path guards (findings #40/#41):
 * a bad take rate can NEVER produce a negative fee (the platform paying the seller more
   than it captured) — such config is refused outright;
 * an absurd price/duration is REFUSED before it ever reaches a payment provider.

Run: python pricing_test.py
"""
import os

from pricing import (PricingConfig, PricingError, estimate, settle,
                     estimate_processing_fee_minor)

_fail = 0


def ok(label, cond):
    global _fail
    print(("ok  " if cond else "FAIL") + "  " + label)
    if not cond:
        _fail += 1


def _raises(fn):
    try:
        fn()
        return False
    except PricingError:
        return True


# ---- take-rate / commission range (#40) ----
ok("valid commission (10%) is accepted", PricingConfig(commission_bps=1000).commission_bps == 1000)
ok("negative commission is rejected", _raises(lambda: PricingConfig(commission_bps=-1)))
ok(">100% commission is rejected", _raises(lambda: PricingConfig(commission_bps=10001)))
ok("negative fixed fee is rejected", _raises(lambda: PricingConfig(fixed_fee_minor=-1)))
ok("negative min charge is rejected", _raises(lambda: PricingConfig(min_charge_minor=-1)))
ok("non-positive max duration is rejected", _raises(lambda: PricingConfig(max_duration_s=0)))
ok("non-positive max charge is rejected", _raises(lambda: PricingConfig(max_charge_minor=0)))
ok("a negative take rate is refused at config time (no negative-fee path)",
   _raises(lambda: PricingConfig(commission_bps=-500)))

# NaN / inf / non-numeric / out-of-range PLATFORM_TAKE_RATE is rejected as a PricingError,
# never crashed-through (a finite-but-huge 1e308 would overflow the bps conversion) or
# silently accepted (1.1 would mean a 110% commission).
os.environ.pop("PLATFORM_COMMISSION_BPS", None)
for bad in ("nan", "inf", "-inf", "abc", "1e308", "1.1", "-0.5"):
    os.environ["PLATFORM_TAKE_RATE"] = bad
    ok(f"PLATFORM_TAKE_RATE={bad!r} is rejected", _raises(lambda: PricingConfig()))
os.environ.pop("PLATFORM_TAKE_RATE", None)

# ---- absolute max-charge ceiling (#41) ----
cfg = PricingConfig(commission_bps=1000, max_charge_minor=1_000_00)   # $1,000 ceiling
snap = cfg.snapshot(price_per_hour_minor=500_00)                       # $500 / hr
under = estimate(snap, 3600)                                           # ~1h -> under the cap
ok("an authorization under the ceiling is allowed",
   0 < under["authorization_amount"] <= 1_000_00)

# an absurd price x duration blows past the cap -> refused BEFORE any provider call.
big = PricingConfig(commission_bps=1000, max_charge_minor=1_000_00, max_duration_s=10**9)
bigsnap = big.snapshot(price_per_hour_minor=10_000_00)                 # $10,000 / hr
ok("an authorization over the ceiling is refused (PricingError)",
   _raises(lambda: estimate(bigsnap, 10**8)))

# a price snapshot can never carry a negative per-hour price.
ok("a negative per-hour price is rejected at snapshot time",
   _raises(lambda: cfg.snapshot(price_per_hour_minor=-1)))

# ---- settle stays float-free + honours the identity even at the authorization cap ----
s = settle(snap, actual_seconds=1800, authorization_amount=under["authorization_amount"])
ok("settle identity holds: capture == fee + seller_net",
   s["capture_amount"] == s["platform_fee_amount"] + s["seller_net_amount"])
ok("settle fee is never negative", s["platform_fee_amount"] >= 0)
ok("settle never captures more than the authorization",
   s["capture_amount"] <= under["authorization_amount"])
ok("all settle amounts are integer minor units (no float)",
   all(isinstance(s[k], int) for k in
       ("capture_amount", "platform_fee_amount", "seller_net_amount", "actual_compute_amount")))

# ---- processing-fee estimate (unit economics visibility) ----
ok("processing fee = 2.9% + 30c on $2.50 (250 minor) -> 37", estimate_processing_fee_minor(250) == 37)
ok("processing fee on the 50c minimum charge -> 31 (fixed 30c dominates)",
   estimate_processing_fee_minor(50) == 31)
ok("processing fee is 0 for a non-positive amount", estimate_processing_fee_minor(0) == 0
   and estimate_processing_fee_minor(-5) == 0)
ok("processing fee is a non-negative int (minor units)",
   isinstance(estimate_processing_fee_minor(1000), int) and estimate_processing_fee_minor(1000) >= 0)
# The break-even truth: below ~$4.23 gross a 10% commission (< fee) loses money.
ok("small job loses money: 10% commission < processing fee",
   (100 // 10) < estimate_processing_fee_minor(100))
ok("large job is profitable: 10% commission > processing fee",
   (100000 // 10) > estimate_processing_fee_minor(100000))
# Configurable via env (parsed at call time).
os.environ["STRIPE_FEE_BPS"] = "0"; os.environ["STRIPE_FEE_FIXED_MINOR"] = "0"
ok("processing fee honors env overrides (0 bps + 0 fixed -> 0)",
   estimate_processing_fee_minor(1000) == 0)
os.environ.pop("STRIPE_FEE_BPS", None); os.environ.pop("STRIPE_FEE_FIXED_MINOR", None)

print(f"\n=== pricing: {'0 failures' if _fail == 0 else str(_fail) + ' FAILED'} ===")
raise SystemExit(1 if _fail else 0)
