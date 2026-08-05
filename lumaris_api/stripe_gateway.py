"""Stripe gateway seam.

All Stripe I/O goes through a `StripeGateway`. Two implementations:

  * `RealStripeGateway`  — thin wrapper over the official `stripe` SDK. Every mutating
    call takes an idempotency key. Used when real Stripe keys are configured.
  * `FakeStripeGateway`  — deterministic, in-process, no network. Mimics the manual-
    capture PaymentIntent lifecycle, Connect accounts + capabilities, transfers,
    refunds and transfer reversals. Used by tests and the offline demo.

Both construct webhook events with a signature that the REAL
`stripe.Webhook.construct_event` verifies, so signature/verification logic is exercised
identically offline and in production.

Choose the gateway with `get_gateway()`:
  * STRIPE_GATEWAY=real  -> RealStripeGateway (requires STRIPE_SECRET_KEY)
  * STRIPE_GATEWAY=fake  -> FakeStripeGateway
  * unset                -> fake unless STRIPE_SECRET_KEY looks live (sk_live_*)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time


class StripeError(Exception):
    """Any gateway-level failure (maps real stripe.error.* + fake failures)."""


class LiveModeForbidden(StripeError):
    """A live Stripe key/mode was detected without an explicit, deliberate opt-in.
    This is a blocking production-safety violation: the system refuses to move real
    money by accident."""


# --------------------------------------------------------------------------- test-mode guard
def assert_test_mode(*, secret_key: str = None, publishable_key: str = None) -> None:
    """Refuse LIVE Stripe keys/mode unless an operator explicitly opts in.

    Enforces the single-source-of-truth rule: Stripe runs in TEST MODE only. A key
    starting with `sk_live_` / `rk_live_` / `pk_live_` is a live key; detecting one is
    a hard failure (`LiveModeForbidden`) — there is NO silent fallback to live.

    The only escape hatch is a deliberate, loud production go-live: BOTH
    `STRIPE_ALLOW_LIVE=true` AND `ENVIRONMENT=production` must be set. Anything else
    (CI, tests, dev, staging) fails immediately on a live key."""
    sk = secret_key if secret_key is not None else os.getenv("STRIPE_SECRET_KEY", "")
    pk = publishable_key if publishable_key is not None else os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    live_markers = ("sk_live_", "rk_live_", "pk_live_")
    detected = [k[:8] + "…" for k in (sk, pk) if k and k.startswith(live_markers)]
    if not detected:
        return
    allowed = (os.getenv("STRIPE_ALLOW_LIVE", "").lower() == "true"
               and os.getenv("ENVIRONMENT", "").lower() == "production")
    if not allowed:
        raise LiveModeForbidden(
            "LIVE Stripe key detected (" + ", ".join(detected) + "). This system is "
            "TEST MODE ONLY. Refusing to run — no fallback to live. To deliberately go "
            "live in production, set STRIPE_ALLOW_LIVE=true AND ENVIRONMENT=production.")


# --------------------------------------------------------------------------- utils
def _sig_header(payload: bytes, secret: str, ts: int | None = None) -> str:
    """Build a Stripe-Signature header (t=,v1=) the real verifier accepts."""
    ts = ts or int(time.time())
    signed = f"{ts}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


# --------------------------------------------------------------------------- real
class RealStripeGateway:
    """Official SDK. Kept intentionally thin; the business logic lives in the service."""

    def __init__(self, api_key: str | None = None):
        import stripe
        key = api_key or os.environ["STRIPE_SECRET_KEY"]
        # Hard-fail on a live key before it can touch Stripe (no live fallback).
        assert_test_mode(secret_key=key)
        self._stripe = stripe
        stripe.api_key = key
        # Pin the API version so event shapes are stable across SDK upgrades.
        v = os.getenv("STRIPE_API_VERSION")
        if v:
            stripe.api_version = v

    # ---- Connect accounts ----
    def create_account(self, *, country: str, email: str | None, metadata: dict,
                       idempotency_key: str) -> dict:
        acct = self._stripe.Account.create(
            controller={"losses": {"payments": "application"},
                        "fees": {"payer": "application"},
                        "stripe_dashboard": {"type": "express"}},
            country=country, email=email,
            capabilities={"card_payments": {"requested": True},
                          "transfers": {"requested": True}},
            metadata=metadata, idempotency_key=idempotency_key)
        return dict(acct)

    def create_account_link(self, *, account_id: str, refresh_url: str,
                            return_url: str) -> dict:
        link = self._stripe.AccountLink.create(
            account=account_id, refresh_url=refresh_url, return_url=return_url,
            type="account_onboarding")
        return dict(link)

    def retrieve_account(self, account_id: str) -> dict:
        return dict(self._stripe.Account.retrieve(account_id))

    def create_login_link(self, account_id: str) -> dict:
        return dict(self._stripe.Account.create_login_link(account_id))

    # ---- PaymentIntents (manual capture, separate charges & transfers) ----
    def create_payment_intent(self, *, amount: int, currency: str, metadata: dict,
                              transfer_group: str, idempotency_key: str,
                              capture_method: str = "manual") -> dict:
        pi = self._stripe.PaymentIntent.create(
            amount=amount, currency=currency, capture_method=capture_method,
            metadata=metadata, transfer_group=transfer_group,
            automatic_payment_methods={"enabled": True},
            idempotency_key=idempotency_key)
        return dict(pi)

    def retrieve_payment_intent(self, pi_id: str) -> dict:
        return dict(self._stripe.PaymentIntent.retrieve(pi_id))

    def capture_payment_intent(self, *, pi_id: str, amount_to_capture: int,
                               idempotency_key: str) -> dict:
        pi = self._stripe.PaymentIntent.capture(
            pi_id, amount_to_capture=amount_to_capture,
            idempotency_key=idempotency_key)
        return dict(pi)

    def cancel_payment_intent(self, *, pi_id: str, idempotency_key: str) -> dict:
        return dict(self._stripe.PaymentIntent.cancel(pi_id, idempotency_key=idempotency_key))

    # ---- Transfers / refunds / reversals ----
    def create_transfer(self, *, amount: int, currency: str, destination: str,
                        transfer_group: str, source_transaction: str | None,
                        metadata: dict, idempotency_key: str) -> dict:
        kw = dict(amount=amount, currency=currency, destination=destination,
                  transfer_group=transfer_group, metadata=metadata,
                  idempotency_key=idempotency_key)
        if source_transaction:
            kw["source_transaction"] = source_transaction
        return dict(self._stripe.Transfer.create(**kw))

    def create_refund(self, *, payment_intent: str, amount: int, metadata: dict,
                      idempotency_key: str) -> dict:
        return dict(self._stripe.Refund.create(
            payment_intent=payment_intent, amount=amount, metadata=metadata,
            idempotency_key=idempotency_key))

    def create_transfer_reversal(self, *, transfer_id: str, amount: int,
                                 metadata: dict, idempotency_key: str) -> dict:
        return dict(self._stripe.Transfer.create_reversal(
            transfer_id, amount=amount, metadata=metadata,
            idempotency_key=idempotency_key))

    # ---- Webhooks ----
    def construct_event(self, payload: bytes, sig_header: str, secret: str) -> dict:
        # The real verifier: raises on bad signature / stale timestamp.
        ev = self._stripe.Webhook.construct_event(payload, sig_header, secret)
        return json.loads(str(ev))


# --------------------------------------------------------------------------- fake
class FakeStripeGateway:
    """Deterministic in-process Stripe for tests and the offline demo.

    Faithful to the parts we depend on: manual-capture PI lifecycle, partial capture
    with authorization release, transfers, refunds, reversals, and Connect account
    capabilities. IDs are stable-per-input where it matters; counters make repeats
    distinct. Idempotency keys are honored (same key -> same object)."""

    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.payment_intents: dict[str, dict] = {}
        self.transfers: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.reversals: dict[str, dict] = {}
        self._idem: dict[str, dict] = {}       # idempotency_key -> object
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_fake{self._n:06d}"

    def _idempotent(self, key: str, factory):
        if key and key in self._idem:
            return self._idem[key]
        obj = factory()
        if key:
            self._idem[key] = obj
        return obj

    # ---- Connect accounts ----
    def create_account(self, *, country, email, metadata, idempotency_key):
        def _make():
            aid = self._id("acct")
            acct = {"id": aid, "object": "account", "country": country,
                    "email": email, "metadata": metadata,
                    "details_submitted": False, "charges_enabled": False,
                    "payouts_enabled": False, "default_currency": country_currency(country),
                    "capabilities": {"card_payments": "inactive", "transfers": "inactive"},
                    "requirements": {"currently_due": ["external_account", "tos_acceptance.date"],
                                     "past_due": [], "disabled_reason": "requirements.past_due"}}
            self.accounts[aid] = acct
            return acct
        return self._idempotent(idempotency_key, _make)

    def create_account_link(self, *, account_id, refresh_url, return_url):
        return {"object": "account_link", "url": f"https://connect.stripe.test/setup/{account_id}",
                "expires_at": int(time.time()) + 300, "created": int(time.time())}

    def retrieve_account(self, account_id):
        if account_id not in self.accounts:
            raise StripeError(f"no such account {account_id}")
        return self.accounts[account_id]

    def create_login_link(self, account_id):
        return {"object": "login_link", "url": f"https://connect.stripe.test/dashboard/{account_id}"}

    # test helper: simulate the seller finishing Stripe onboarding
    def complete_onboarding(self, account_id: str, *, ok: bool = True):
        a = self.accounts[account_id]
        a["details_submitted"] = True
        a["charges_enabled"] = ok
        a["payouts_enabled"] = ok
        a["capabilities"] = {"card_payments": "active" if ok else "inactive",
                             "transfers": "active" if ok else "inactive"}
        a["requirements"] = {"currently_due": [], "past_due": [],
                             "disabled_reason": None if ok else "requirements.past_due"}
        return a

    # ---- PaymentIntents ----
    def create_payment_intent(self, *, amount, currency, metadata, transfer_group,
                              idempotency_key, capture_method="manual"):
        def _make():
            pid = self._id("pi")
            pi = {"id": pid, "object": "payment_intent", "amount": amount,
                  "currency": currency, "capture_method": capture_method,
                  "status": "requires_payment_method", "amount_capturable": 0,
                  "amount_received": 0, "metadata": metadata,
                  "transfer_group": transfer_group,
                  "client_secret": f"{pid}_secret_fake",
                  "latest_charge": None}
            self.payment_intents[pid] = pi
            return pi
        return self._idempotent(idempotency_key, _make)

    def retrieve_payment_intent(self, pi_id):
        if pi_id not in self.payment_intents:
            raise StripeError(f"no such payment_intent {pi_id}")
        return self.payment_intents[pi_id]

    # test helper: simulate the buyer confirming the card (client-side) -> authorized
    def confirm_payment_intent(self, pi_id: str, *, fail: bool = False):
        pi = self.payment_intents[pi_id]
        if fail:
            pi["status"] = "requires_payment_method"
            return pi
        pi["status"] = "requires_capture"
        pi["amount_capturable"] = pi["amount"]
        pi["latest_charge"] = self._id("ch")
        return pi

    def capture_payment_intent(self, *, pi_id, amount_to_capture, idempotency_key):
        def _make():
            pi = self.payment_intents[pi_id]
            if pi["status"] not in ("requires_capture",):
                raise StripeError(f"cannot capture PI in status {pi['status']}")
            cap = min(int(amount_to_capture), pi["amount_capturable"])
            pi["amount_received"] = cap
            pi["amount_capturable"] = 0
            pi["status"] = "succeeded"        # partial capture auto-releases the rest
            if not pi.get("latest_charge"):
                pi["latest_charge"] = self._id("ch")
            return pi
        return self._idempotent(idempotency_key, _make)

    def cancel_payment_intent(self, *, pi_id, idempotency_key):
        def _make():
            pi = self.payment_intents[pi_id]
            if pi["status"] == "succeeded":
                raise StripeError("cannot cancel a captured PaymentIntent")
            pi["status"] = "canceled"
            pi["amount_capturable"] = 0
            return pi
        return self._idempotent(idempotency_key, _make)

    # ---- Transfers / refunds / reversals ----
    def create_transfer(self, *, amount, currency, destination, transfer_group,
                        source_transaction, metadata, idempotency_key):
        def _make():
            tid = self._id("tr")
            tr = {"id": tid, "object": "transfer", "amount": amount,
                  "currency": currency, "destination": destination,
                  "transfer_group": transfer_group, "metadata": metadata,
                  "amount_reversed": 0, "reversed": False}
            self.transfers[tid] = tr
            return tr
        return self._idempotent(idempotency_key, _make)

    def create_refund(self, *, payment_intent, amount, metadata, idempotency_key):
        def _make():
            rid = self._id("re")
            pi = self.payment_intents.get(payment_intent)
            re = {"id": rid, "object": "refund", "amount": amount,
                  "payment_intent": payment_intent,
                  "charge": pi.get("latest_charge") if pi else None,
                  "status": "succeeded", "metadata": metadata}
            self.refunds[rid] = re
            return re
        return self._idempotent(idempotency_key, _make)

    def create_transfer_reversal(self, *, transfer_id, amount, metadata, idempotency_key):
        def _make():
            tr = self.transfers[transfer_id]
            avail = tr["amount"] - tr["amount_reversed"]
            amt = min(int(amount), avail)
            tr["amount_reversed"] += amt
            tr["reversed"] = tr["amount_reversed"] >= tr["amount"]
            rid = self._id("trr")
            rev = {"id": rid, "object": "transfer_reversal", "amount": amt,
                   "transfer": transfer_id, "metadata": metadata}
            self.reversals[rid] = rev
            return rev
        return self._idempotent(idempotency_key, _make)

    # ---- Webhooks ----
    def sign(self, event: dict, secret: str, ts: int | None = None) -> tuple[bytes, str]:
        """Return (raw_body, sig_header) for an event so tests can POST a valid webhook."""
        payload = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
        return payload, _sig_header(payload, secret, ts)

    def construct_event(self, payload: bytes, sig_header: str, secret: str) -> dict:
        # Use the REAL verifier even in fake mode, so signature checks are genuine.
        import stripe
        ev = stripe.Webhook.construct_event(payload, sig_header, secret)
        return json.loads(str(ev))


# Minimal country->default-currency map for the fake (extend as needed).
_COUNTRY_CCY = {"US": "usd", "GB": "gbp", "DE": "eur", "FR": "eur", "SA": "sar",
                "AE": "aed", "CA": "cad", "AU": "aud", "SG": "sgd", "JP": "jpy"}


def country_currency(country: str) -> str:
    return _COUNTRY_CCY.get((country or "US").upper(), "usd")


# --------------------------------------------------------------------------- factory
_GATEWAY = None


def get_gateway():
    """Process-wide gateway, selected by STRIPE_GATEWAY ('real' or fake).

    A live key is refused up front (`assert_test_mode`) so the system can never
    silently fall back to live mode — even a misconfigured `STRIPE_GATEWAY=real`
    with a live key hard-fails rather than moving real money."""
    global _GATEWAY
    if _GATEWAY is not None:
        return _GATEWAY
    mode = os.getenv("STRIPE_GATEWAY", "").strip().lower()
    # Enforce test mode regardless of which gateway is about to be selected.
    assert_test_mode()
    if mode == "real":
        _GATEWAY = RealStripeGateway()
    else:
        # Default to the offline fake unless 'real' is explicitly requested. We never
        # auto-select the live SDK from key shape — that was a silent live-mode path.
        _GATEWAY = FakeStripeGateway()
    return _GATEWAY


def set_gateway(gw):
    """Tests/demo inject a gateway explicitly."""
    global _GATEWAY
    _GATEWAY = gw
    return gw
