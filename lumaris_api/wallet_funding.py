"""Wallet 'Add funds' via Stripe Checkout (the hosted card page).

Clicking Add funds creates a Stripe Checkout Session and sends the buyer to Stripe to
enter their card — we never touch card data. The wallet is credited when the payment
completes (the checkout.session.completed webhook, or the sandbox simulate-pay).

TEST (demo) vs LIVE: the configured gateway + keys decide which Stripe environment the
checkout runs in (assert_test_mode refuses live keys unless explicitly opted in). Every
top-up is stamped with payments_mode() so demo funds are never counted as live money.
"""
from __future__ import annotations

import logging
import os

import db as dbmod
from db import WalletTopup, payments_mode
from stripe_gateway import get_gateway, FakeStripeGateway, StripeError

logger = logging.getLogger("petabyte.wallet")

MIN_TOPUP_MINOR = int(os.getenv("WALLET_MIN_TOPUP_MINOR", "500"))       # $5.00
MAX_TOPUP_MINOR = int(os.getenv("WALLET_MAX_TOPUP_MINOR", "500000"))    # $5,000.00


class WalletError(Exception):
    pass


def start_topup(db, user, *, amount_minor: int, currency: str = "usd",
                success_url: str, cancel_url: str) -> dict:
    """Create a pending top-up + a Stripe Checkout Session. Returns the checkout URL to
    redirect the buyer to, plus the mode so the UI can badge TEST vs LIVE."""
    amt = int(amount_minor)
    if amt < MIN_TOPUP_MINOR or amt > MAX_TOPUP_MINOR:
        raise WalletError(
            f"amount must be between {MIN_TOPUP_MINOR} and {MAX_TOPUP_MINOR} minor units")
    mode = payments_mode()
    topup = WalletTopup(user_id=user.id, amount_minor=amt, currency=currency, mode=mode)
    db.add(topup); db.commit(); db.refresh(topup)

    meta = {"petabyte_user_id": str(user.id), "purpose": "wallet_topup",
            "topup_id": topup.public_id, "mode": mode}
    try:
        sess = get_gateway().create_checkout_session(
            amount=amt, currency=currency, metadata=meta,
            success_url=success_url, cancel_url=cancel_url,
            idempotency_key=f"petabyte:topup:{topup.public_id}")
    except StripeError as e:
        topup.status = "failed"; db.add(topup); db.commit()
        raise WalletError(f"could not start checkout: {e}")
    topup.stripe_session_id = sess["id"]; db.add(topup); db.commit()
    logger.info("wallet topup started id=%s user=%s amount=%s mode=%s",
                topup.public_id, user.id, amt, mode)
    return {"topup_id": topup.public_id, "session_id": sess["id"],
            "checkout_url": sess.get("url"), "amount_minor": amt, "currency": currency,
            "mode": mode, "test_mode": mode == "TEST",
            "publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", "")}


def credit_from_session(db, session: dict) -> bool:
    """Idempotently credit the wallet for a PAID wallet_topup checkout session. Safe to
    call from the webhook and from simulate-pay; returns True only on the crediting call."""
    meta = session.get("metadata") or {}
    if meta.get("purpose") != "wallet_topup":
        return False
    if (session.get("payment_status") or "").lower() != "paid":
        return False
    topup = dbmod.get_topup_by_session(db, session.get("id"))
    if not topup:
        return False
    return dbmod.mark_topup_paid_and_credit(
        db, topup, payment_intent_id=session.get("payment_intent"))


def simulate_pay(db, topup: WalletTopup) -> dict:
    """SANDBOX/TEST ONLY: complete the hosted card page against the fake gateway and
    credit the wallet (offline demo / CI). Refuses in real Stripe mode."""
    gw = get_gateway()
    if not isinstance(gw, FakeStripeGateway):
        raise WalletError("simulate-pay is only available with the fake gateway")
    if not topup.stripe_session_id:
        raise WalletError("top-up has no checkout session")
    sess = gw.complete_checkout_session(topup.stripe_session_id)
    credit_from_session(db, sess)
    return sess
