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

import math
import os
from decimal import Decimal, ROUND_HALF_UP

SNAPSHOT_VERSION = 1

# Absolute ceiling on any single authorization/capture (minor units). Defence in depth: an
# absurd price_per_hour or duration (a fat-fingered listing, a bug, or an attack) must be
# REFUSED before it ever reaches a payment provider. Default: $1,000,000 in cents. Operators
# can raise it deliberately via PLATFORM_MAX_CHARGE_MINOR.
_DEFAULT_MAX_CHARGE_MINOR = 100_000_000


class PricingError(ValueError):
    """Raised on invalid pricing config or an amount that exceeds the absolute ceiling.
    Callers translate this into a 4xx — money must never move on a bad-config path."""


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _take_rate_bps(default_bps: int = 1000) -> int:
    """Parse PLATFORM_TAKE_RATE (a 0..1 fraction) into basis points, rejecting NaN/inf and
    out-of-range values rather than crashing or producing a nonsensical commission."""
    raw = os.getenv("PLATFORM_TAKE_RATE")
    if raw is None or raw.strip() == "":
        return default_bps
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        raise PricingError(f"PLATFORM_TAKE_RATE is not a number: {raw!r}")
    if not math.isfinite(rate):
        raise PricingError(f"PLATFORM_TAKE_RATE must be finite (got {raw!r})")
    return int(round(rate * 10000))


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
                 auth_margin_bps: int | None = None,
                 max_charge_minor: int | None = None):
        # commission in basis points (1000 = 10.00%); default tracks PLATFORM_TAKE_RATE.
        self.currency = (currency or os.getenv("PLATFORM_CURRENCY", "usd")).lower()
        self.commission_bps = commission_bps if commission_bps is not None \
            else _env_int("PLATFORM_COMMISSION_BPS", _take_rate_bps())
        self.fixed_fee_minor = fixed_fee_minor if fixed_fee_minor is not None \
            else _env_int("PLATFORM_FIXED_FEE_MINOR", 0)
        self.min_charge_minor = min_charge_minor if min_charge_minor is not None \
            else _env_int("PLATFORM_MIN_CHARGE_MINOR", 50)          # e.g. $0.50
        self.max_duration_s = max_duration_s if max_duration_s is not None \
            else _env_int("PLATFORM_MAX_DURATION_S", 24 * 3600)
        # safety margin added to the estimate to set the authorization ceiling.
        self.auth_margin_bps = auth_margin_bps if auth_margin_bps is not None \
            else _env_int("PLATFORM_AUTH_MARGIN_BPS", 2000)         # +20%
        self.max_charge_minor = max_charge_minor if max_charge_minor is not None \
            else _env_int("PLATFORM_MAX_CHARGE_MINOR", _DEFAULT_MAX_CHARGE_MINOR)
        self._validate()

    def _validate(self) -> None:
        """Reject nonsensical config BEFORE it can produce a bad charge. A negative or
        >100% commission would make the platform fee negative or swallow the whole capture
        (breaking `capture == fee + seller_net` in spirit); negative fixed/min/margin or a
        non-positive duration/ceiling are all money hazards."""
        if not 0 <= self.commission_bps <= 10000:
            raise PricingError(
                f"commission must be 0..100% (0..10000 bps); got {self.commission_bps} bps")
        if self.fixed_fee_minor < 0:
            raise PricingError(f"fixed_fee_minor must be >= 0; got {self.fixed_fee_minor}")
        if self.min_charge_minor < 0:
            raise PricingError(f"min_charge_minor must be >= 0; got {self.min_charge_minor}")
        if self.auth_margin_bps < 0:
            raise PricingError(f"auth_margin_bps must be >= 0; got {self.auth_margin_bps}")
        if self.max_duration_s <= 0:
            raise PricingError(f"max_duration_s must be > 0; got {self.max_duration_s}")
        if self.max_charge_minor <= 0:
            raise PricingError(f"max_charge_minor must be > 0; got {self.max_charge_minor}")

    def snapshot(self, price_per_hour_minor: int) -> dict:
        """Freeze the config + the seller's per-hour price (in minor units) onto a
        transaction. Everything needed to recompute any amount later lives here."""
        ppm = int(price_per_hour_minor)
        if ppm < 0:
            raise PricingError(f"price_per_hour_minor must be >= 0; got {ppm}")
        return {
            "version": SNAPSHOT_VERSION,
            "currency": self.currency,
            "price_per_hour_minor": ppm,
            "commission_bps": self.commission_bps,
            "fixed_fee_minor": self.fixed_fee_minor,
            "min_charge_minor": self.min_charge_minor,
            "max_duration_s": self.max_duration_s,
            "auth_margin_bps": self.auth_margin_bps,
            "max_charge_minor": self.max_charge_minor,
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
    # Absolute ceiling: refuse an absurd authorization BEFORE it reaches a provider.
    # (max_charge_minor may be absent on snapshots frozen before this field existed.)
    ceiling = int(snapshot.get("max_charge_minor", _DEFAULT_MAX_CHARGE_MINOR))
    if authorization > ceiling:
        raise PricingError(
            f"authorization {authorization} exceeds the maximum allowed charge {ceiling} "
            f"(minor units) — refusing to book")
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
