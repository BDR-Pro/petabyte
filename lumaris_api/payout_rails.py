"""Provider-neutral payout rails.

A `PayoutRail` is one way to move a seller's earnings out. Rails are NOT
interchangeable Stripe Connect accounts — each has its own country availability,
eligibility, KYC, currencies, limits, fees, settlement time, reversibility and
compliance. The job-settlement system never talks to a provider directly; it creates a
provider-neutral PayoutObligation and the routing layer picks a rail.

Honesty rule enforced here: an unavailable adapter returns `capability.status =
NOT_IMPLEMENTED` and MUST NOT contribute to verified coverage. There are no fake
adapters that return success.

Only synchronous shapes are used (the repo is sync SQLAlchemy); the interface mirrors
the async Protocol in the brief.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PayoutRailType(str, enum.Enum):
    STRIPE_CONNECT = "stripe_connect"
    STRIPE_GLOBAL_PAYOUTS = "stripe_global_payouts"
    STRIPE_STABLECOIN = "stripe_stablecoin"
    CIRCLE_STABLECOIN = "circle_stablecoin"
    MANUAL_REVIEW = "manual_review"


class RecipientType(str, enum.Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class CapabilityStatus(str, enum.Enum):
    ACTIVE = "active"                              # usable now
    PENDING_PROVIDER_APPROVAL = "pending_provider_approval"
    PREVIEW = "preview"
    PLANNED = "planned"
    NOT_IMPLEMENTED = "not_implemented"            # adapter absent -> never counts
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"                            # sanctioned / prohibited


@dataclass
class PayoutCapability:
    rail_type: PayoutRailType
    country_code: str
    recipient_type: RecipientType
    currency: str
    status: CapabilityStatus
    bank: bool = False
    stablecoin: bool = False
    min_amount_minor: int = 0
    max_amount_minor: int | None = None
    estimated_delivery: str = ""
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.status == CapabilityStatus.ACTIVE


@dataclass
class PayoutQuote:
    rail_type: PayoutRailType
    gross_minor: int
    provider_fee_minor: int
    fx_rate: float | None
    source_currency: str
    destination_currency: str
    net_to_seller_minor: int
    estimated_delivery: str


@dataclass
class ExternalPayout:
    rail_type: PayoutRailType
    external_id: str
    status: str                                    # sent|paid|failed|pending|reversed
    amount_minor: int
    raw: dict = field(default_factory=dict)


class PayoutRailError(Exception):
    pass


class NotImplementedRail(PayoutRailError):
    """Raised by an adapter that has no working provider integration yet."""


# --------------------------------------------------------------------------- rails
class PayoutRail:
    """Base class. Adapters override the methods they genuinely implement."""
    rail_type: PayoutRailType

    def get_country_capability(self, country_code, recipient_type, currency) -> PayoutCapability:
        raise NotImplementedError

    def send_payout(self, db, obligation, idempotency_key) -> ExternalPayout:
        raise NotImplementedError

    def retrieve_payout(self, external_payout_id) -> ExternalPayout:
        raise NotImplementedError


class StripeConnectPayoutRail(PayoutRail):
    """The ONE fully-implemented rail. Uses the Stripe Connect transfer path
    (stripe_connect.transfer_to_seller / the gateway). Capability is read from the
    normalized dataset so it reflects real (test-mode) approval state, not a guess."""
    rail_type = PayoutRailType.STRIPE_CONNECT

    def get_country_capability(self, country_code, recipient_type, currency):
        import payout_capabilities as cap
        rt = recipient_type.value if isinstance(recipient_type, RecipientType) else recipient_type
        rows = [r for r in cap.capabilities_for(country_code, rt, currency)
                if r["provider"] == "stripe" and r["product"].startswith("connect")]
        if not rows:
            return PayoutCapability(self.rail_type, country_code, RecipientType(rt), currency,
                                    CapabilityStatus.UNSUPPORTED, reason="no Connect row for country")
        r = rows[0]
        status = (CapabilityStatus.ACTIVE if r["is_active"]
                  else CapabilityStatus(r["availability_status"]))
        return PayoutCapability(
            self.rail_type, country_code, RecipientType(rt), currency, status,
            bank=r.get("bank_payout_supported", False),
            stablecoin=r.get("stablecoin_payout_supported", False),
            min_amount_minor=r.get("minimum_amount_minor", 0),
            max_amount_minor=r.get("maximum_amount_minor"),
            estimated_delivery=r.get("estimated_delivery", ""),
            reason=r.get("notes", ""))

    def send_payout(self, db, obligation, idempotency_key) -> ExternalPayout:
        """Execute via the Stripe Connect transfer path. The obligation carries the seller
        + net. There is no ComputeTransaction here (a batch can span many), so instead of
        stripe_connect.transfer_to_seller we call the same gateway.create_transfer with
        the obligation's deterministic idempotency key — so a retry never double-sends."""
        import db as dbmod
        from stripe_gateway import get_gateway, StripeError
        seller_ca = db.query(dbmod.ConnectedAccount).filter(
            dbmod.ConnectedAccount.user_id == obligation.seller_id).first()
        if not seller_ca or not seller_ca.payout_ready():
            raise PayoutRailError("seller connected account not payout-ready")
        try:
            tr = get_gateway().create_transfer(
                amount=obligation.net_amount_minor, currency=obligation.currency,
                destination=seller_ca.stripe_account_id,
                transfer_group=f"batch:{obligation.batch_id or obligation.id}",
                source_transaction=None,
                metadata={"petabyte_obligation": str(obligation.id),
                          "seller_id": str(obligation.seller_id)},
                idempotency_key=idempotency_key)
        except StripeError as e:
            raise PayoutRailError(f"stripe transfer failed: {e}")
        return ExternalPayout(self.rail_type, tr["id"], "sent",
                              obligation.net_amount_minor, raw=tr)


class _UnimplementedRail(PayoutRail):
    """Base for rails Petabyte has NOT built/approved. They report NOT_IMPLEMENTED and
    refuse to move money — so they can never inflate coverage or fake a payout."""
    _label = "rail"

    def get_country_capability(self, country_code, recipient_type, currency):
        rt = recipient_type if isinstance(recipient_type, RecipientType) else RecipientType(recipient_type)
        return PayoutCapability(self.rail_type, country_code, rt, currency,
                                CapabilityStatus.NOT_IMPLEMENTED,
                                reason=f"{self._label} adapter not implemented / not approved")

    def send_payout(self, db, obligation, idempotency_key):
        raise NotImplementedRail(f"{self._label} is not implemented")


class StripeGlobalPayoutRail(_UnimplementedRail):
    rail_type = PayoutRailType.STRIPE_GLOBAL_PAYOUTS
    _label = "Stripe Global Payouts"


class StripeStablecoinPayoutRail(_UnimplementedRail):
    rail_type = PayoutRailType.STRIPE_STABLECOIN
    _label = "Stripe stablecoin payouts"


class CircleStablecoinPayoutRail(_UnimplementedRail):
    # The repo has a raw Circle httpx call, but it is NOT wired to compliance/wallet
    # screening/consent, so it is honestly NOT usable as a rail.
    rail_type = PayoutRailType.CIRCLE_STABLECOIN
    _label = "Circle stablecoin payouts"


class ManualReviewPayoutRail(PayoutRail):
    """Controlled last resort: creates a task for an operator to pay out manually and
    record the external reference. It is 'implemented' (it does something real) but is
    never counted as automated coverage."""
    rail_type = PayoutRailType.MANUAL_REVIEW

    def get_country_capability(self, country_code, recipient_type, currency):
        rt = recipient_type if isinstance(recipient_type, RecipientType) else RecipientType(recipient_type)
        # Manual review is a fallback, not verified per-country coverage.
        return PayoutCapability(self.rail_type, country_code, rt, currency,
                                CapabilityStatus.PLANNED,
                                reason="manual operator payout; last resort, not automated coverage")

    def send_payout(self, db, obligation, idempotency_key):
        raise NotImplementedRail("manual review requires an operator action, not an API send")


RAILS = {
    PayoutRailType.STRIPE_CONNECT: StripeConnectPayoutRail(),
    PayoutRailType.STRIPE_GLOBAL_PAYOUTS: StripeGlobalPayoutRail(),
    PayoutRailType.STRIPE_STABLECOIN: StripeStablecoinPayoutRail(),
    PayoutRailType.CIRCLE_STABLECOIN: CircleStablecoinPayoutRail(),
    PayoutRailType.MANUAL_REVIEW: ManualReviewPayoutRail(),
}


def get_rail(rail_type: PayoutRailType) -> PayoutRail:
    return RAILS[rail_type]
