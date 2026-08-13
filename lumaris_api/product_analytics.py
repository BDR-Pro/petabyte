"""product_analytics.py — degrade-safe product-funnel capture (PostHog).

Petabyte already emits a stable structured-event taxonomy (`observability.EVENTS`) to logs
and OpenTelemetry. This module mirrors the handful of events an investor's growth funnel cares
about — signup → activation → usage → revenue — to PostHog, and is a total NO-OP when not
configured. It never raises, never blocks the request path (fire-and-forget in a daemon
thread), and never sends secrets or PII beyond a stable numeric distinct id.

Wiring is centralized: `observability.event()` calls `maybe_capture(name, fields)` once, so
adding a funnel event is just adding it to `FUNNEL` below — no endpoint touches needed.

No new hard dependency: uses httpx (already required). Enable with POSTHOG_API_KEY (+ optional
POSTHOG_HOST); disable entirely with PRODUCT_ANALYTICS_ENABLED=false.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger("petabyte.analytics")

# event_name (observability.EVENTS value)  ->  human PostHog event label.
# This IS the funnel: signup, activation, core usage, revenue.
FUNNEL = {
    "user.signed_up":                "user signed up",          # acquisition
    "seller.gpu.detected":           "gpu online",              # seller activation
    "wallet.funded":                 "wallet funded",           # buyer activation
    "gpu.reservation.created":       "compute booked",          # core usage
    "job.dispatched":                "job dispatched",          # core usage
    "job.execution.completed":       "job completed",           # aha moment
    "settlement.capture.completed":  "compute paid",            # revenue
    "transaction.completed":         "transaction completed",   # revenue
}

# property keys that must never leave the box, matched as substrings (case-insensitive).
_DENY = ("password", "token", "secret", "api_key", "apikey", "authorization",
         "email", "card", "pan", "cvc", "signature", "pubkey", "private")

# id fields to use as the PostHog distinct id, in preference order (numeric, not PII).
_ID_KEYS = ("user_id", "buyer_id", "seller_id", "org_id", "distinct_id")


def _enabled() -> bool:
    if os.getenv("PRODUCT_ANALYTICS_ENABLED", "true").lower() not in ("1", "true", "yes", "on"):
        return False
    return bool(os.getenv("POSTHOG_API_KEY"))


def _host() -> str:
    return os.getenv("POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")


def _distinct_id(fields: dict) -> str:
    for k in _ID_KEYS:
        v = fields.get(k)
        if v not in (None, ""):
            return str(v)[:200]
    return "anonymous"


def _clean_props(fields: dict) -> dict:
    out = {}
    for k, v in (fields or {}).items():
        lk = str(k).lower()
        if any(d in lk for d in _DENY):
            continue
        if k in ("message",):
            continue
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, (int, float, str)):
            out[k] = v if not isinstance(v, str) else v[:200]
        else:
            out[k] = str(v)[:200]
    return out


def build_payload(name: str, fields: dict):
    """Pure: the PostHog /capture/ body for a funnel event, or None if `name` is not a
    funnel event (so most telemetry is ignored). Testable without any network."""
    label = FUNNEL.get(name)
    if not label:
        return None
    return {
        "api_key": os.getenv("POSTHOG_API_KEY", ""),
        "event": label,
        "distinct_id": _distinct_id(fields or {}),
        "properties": {**_clean_props(fields or {}), "event_name": name,
                       "$lib": "petabyte-server"},
    }


def _send(payload: dict) -> None:
    try:
        import httpx
        httpx.post(f"{_host()}/capture/", json=payload, timeout=3.0)
    except Exception:  # noqa: BLE001 — analytics must never surface an error
        logger.debug("posthog capture failed (non-fatal)", exc_info=True)


def maybe_capture(name: str, fields: dict) -> bool:
    """Fire-and-forget a funnel event to PostHog. Returns True if it was dispatched (a funnel
    event AND configured), False otherwise. Never raises, never blocks the caller."""
    try:
        if not _enabled():
            return False
        payload = build_payload(name, fields or {})
        if not payload:
            return False
        threading.Thread(target=_send, args=(payload,), daemon=True).start()
        return True
    except Exception:  # noqa: BLE001
        logger.debug("posthog enqueue failed (non-fatal)", exc_info=True)
        return False
