"""Server-side compute pricing. INTEGER MINOR UNITS ONLY (e.g. USD cents).

Every amount that touches money here is an `int` in the currency's minor unit. No
floats. Decimal is used only transiently to convert an authoritative per-hour price
into minor units, then coerced to int with half-up rounding.

The browser never computes any of this. The frontend sends at most a GPU id, a
workload template, and a max-runtime preference; all amounts are derived here from
authoritative DB values and a *pricing snapshot* frozen onto the transaction, so a
later config or price change never rewrites a historical charge.

Fee rule (documented, configurable, snapshotted per transaction):
  * Buyer pays the final *compute* amount (actual metered usage x price).
  * Platform commission  = commission_bps/10000 * compute  (+ optional fixed fee),
    floored so it never exceeds the compute amount.
  * Seller net           = compute - platform commission.
  * The Stripe processing fee is borne by the PLATFORM (the charge lives on the
    platform account) and is tracked SEPARATELY — it is never subtracted from the
    seller's net. `buyer_compute_charge == platform_fee + seller_net`.
"""
from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP

SNAPSHOT_VERSION = 1


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class PricingConfig:
    """Current platform pricing config, read from env at snapshot time.

    Snapshotted onto each transaction so config changes never alter history.
    """

    def __init__(self,
                 currency: str | None = None,
                 commission_bps: int | None = None,
                 fixed_fee_minor: int | None = None,
                 min_charge_minor: int | None = None,
                 max_duration_s: int | None = None,
                 auth_margin_bps: int | None = None):
        # commission in basis points (1000 = 10.00%); default tracks PLATFORM_TAKE_RATE.
        default_bps = int(round(float(os.getenv("PLATFORM_TAKE_RATE", "0.10")) * 10000))
        self.currency = (currency or os.getenv("PLATFORM_CURRENCY", "usd")).lower()
        self.commission_bps = commission_bps if commission_bps is not None \
            else _env_int("PLATFORM_COMMISSION_BPS", default_bps)
        self.fixed_fee_minor = fixed_fee_minor if fixed_fee_minor is not None \
            else _env_int("PLATFORM_FIXED_FEE_MINOR", 0)
        self.min_charge_minor = min_charge_minor if min_charge_minor is not None \
            else _env_int("PLATFORM_MIN_CHARGE_MINOR", 50)          # e.g. $0.50
        self.max_duration_s = max_duration_s if max_duration_s is not None \
            else _env_int("PLATFORM_MAX_DURATION_S", 24 * 3600)
        # safety margin added to the estimate to set the authorization ceiling.
        self.auth_margin_bps = auth_margin_bps if auth_margin_bps is not None \
            else _env_int("PLATFORM_AUTH_MARGIN_BPS", 2000)         # +20%

    def snapshot(self, price_per_hour_minor: int) -> dict:
        """Freeze the config + the seller's per-hour price (in minor units) onto a
        transaction. Everything needed to recompute any amount later lives here."""
        return {
            "version": SNAPSHOT_VERSION,
            "currency": self.currency,
            "price_per_hour_minor": int(price_per_hour_minor),
            "commission_bps": self.commission_bps,
            "fixed_fee_minor": self.fixed_fee_minor,
            "min_charge_minor": self.min_charge_minor,
            "max_duration_s": self.max_duration_s,
            "auth_margin_bps": self.auth_margin_bps,
        }


def price_per_hour_to_minor(price_per_hour, currency: str = "usd") -> int:
    """Convert an authoritative per-hour price (Decimal/str/number) to minor units.
    Uses Decimal + half-up; never binary float."""
    minor_per_unit = 100  # currencies used here are 2-decimal; extend if adding JPY etc.
    d = price_per_hour if isinstance(price_per_hour, Decimal) else Decimal(str(price_per_hour))
    return int((d * minor_per_unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _compute_minor(price_per_hour_minor: int, seconds: int) -> int:
    """compute = price_per_hour_minor * seconds / 3600, half-up, integer minor units."""
    if seconds <= 0:
        return 0
    val = (Decimal(price_per_hour_minor) * Decimal(seconds) / Decimal(3600))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate(snapshot: dict, estimated_seconds: int) -> dict:
    """Estimated compute amount + the authorization ceiling (with safety margin).
    Duration is clamped to the snapshot's max; the authorization is what we ask the
    buyer's card to hold, never the final charge."""
    secs = max(0, min(int(estimated_seconds), int(snapshot["max_duration_s"])))
    est = _compute_minor(snapshot["price_per_hour_minor"], secs)
    est = max(est, int(snapshot["min_charge_minor"])) if secs > 0 else est
    margin = (est * int(snapshot["auth_margin_bps"])) // 10000
    authorization = est + margin + int(snapshot["fixed_fee_minor"])
    return {
        "currency": snapshot["currency"],
        "estimated_seconds": secs,
        "estimated_compute_amount": est,
        "authorization_amount": authorization,
        "price_per_hour_minor": int(snapshot["price_per_hour_minor"]),
    }


def settle(snapshot: dict, actual_seconds: int, authorization_amount: int) -> dict:
    """Compute the FINAL, capped amounts from the immutable snapshot and the trusted
    metered duration. Returns integer minor units:

      actual_compute_amount  buyer's final compute charge (>= min charge if any usage)
      capture_amount         what we actually capture (<= authorization)
      platform_fee_amount    Petabyte commission (pct + fixed), floored to <= compute
      seller_gross_amount    == actual_compute_amount
      seller_net_amount      compute - platform fee  (what the Transfer sends)
    Invariant: capture_amount == platform_fee_amount + seller_net_amount.
    """
    secs = max(0, min(int(actual_seconds), int(snapshot["max_duration_s"])))
    compute = _compute_minor(snapshot["price_per_hour_minor"], secs)
    if secs > 0:
        compute = max(compute, int(snapshot["min_charge_minor"]))
    # Never capture more than the buyer authorized.
    capture = min(compute, int(authorization_amount))
    # Commission is computed on the CAPTURED amount so the identity always holds
    # even after the authorization cap bites.
    pct = (capture * int(snapshot["commission_bps"])) // 10000
    fee = pct + int(snapshot["fixed_fee_minor"])
    fee = min(fee, capture)                 # fee can never exceed what we captured
    seller_net = capture - fee
    return {
        "currency": snapshot["currency"],
        "actual_seconds": secs,
        "actual_compute_amount": compute,
        "capture_amount": capture,
        "platform_fee_amount": fee,
        "seller_gross_amount": capture,
        "seller_net_amount": seller_net,
    }


def refund_split(settlement: dict, refund_amount: int) -> dict:
    """Given a captured settlement and a refund (minor units), compute how much of the
    seller's net must be clawed back (proportional) vs. platform fee returned. Used to
    drive a transfer reversal after a refund. Never returns negative or > available."""
    refund = max(0, min(int(refund_amount), int(settlement["capture_amount"])))
    capture = int(settlement["capture_amount"]) or 1
    seller_net = int(settlement["seller_net_amount"])
    # Proportional clawback of the seller's net for the refunded fraction.
    seller_reversal = (seller_net * refund) // capture
    platform_refund = refund - seller_reversal
    return {
        "refund_amount": refund,
        "seller_reversal_amount": seller_reversal,
        "platform_refund_amount": max(0, platform_refund),
    }
