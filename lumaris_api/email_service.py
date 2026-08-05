"""Transactional email for Petabyte Cloud (Mailgun HTTP API).

Design goals
------------
* Only two env vars are required: MAILGUN_API_KEY and MAILGUN_DOMAIN. Everything else is
  hardcoded so config cannot silently drift: the API base is https://api.mailgun.net and
  the default sender is "Petabyte Support <support@petabyte.market>".
* Provider-neutral by construction. Callers use EmailService; all Mailgun specifics live
  in MailgunBackend behind the EmailBackend protocol, so another provider (SES, Postmark,
  …) can be dropped in without touching callers or templates.
* Every send is HTML + plain-text (multipart), with the Petabyte mark embedded inline
  (cid:) so the logo renders in Gmail and Outlook without external image loading.
* Secrets are never logged. Sends emit one structured log line (success or failure) with
  the masked recipient, subject, provider message id, and status — never the API key.

Usage
-----
    svc = get_email_service()
    svc.send_welcome("user@example.com", name="Ada", dashboard_url="https://…/app")
"""
from __future__ import annotations

import html as _html
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

import httpx

logger = logging.getLogger("petabyte.email")

# --- hardcoded (NOT env-configurable, on purpose) ---------------------------------------
MAILGUN_API_BASE = "https://api.mailgun.net"
DEFAULT_FROM = "Petabyte Support <support@petabyte.market>"
_DEFAULT_TIMEOUT = 20.0
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "emails"
_LOGO_FILENAME = "petabyte-logo.png"          # inline cid reference is cid:petabyte-logo.png


# --- errors -----------------------------------------------------------------------------
class EmailError(Exception):
    """Base class for all email failures."""


class EmailConfigError(EmailError):
    """Missing/invalid configuration (e.g. no API key or domain)."""


class EmailSendError(EmailError):
    """The provider rejected the message or was unreachable (network/timeout/API error)."""


@dataclass
class EmailResult:
    ok: bool
    provider_message_id: str | None = None
    status_code: int | None = None
    detail: str = ""


# --- helpers ----------------------------------------------------------------------------
def _mask(addr) -> str:
    """Mask an address for logs: 'ada@example.com' -> 'a***@example.com'. Lists are joined."""
    if isinstance(addr, (list, tuple)):
        return ", ".join(_mask(a) for a in addr)
    local, _, dom = str(addr).partition("@")
    if not dom:
        return "***"
    return f"{local[:1]}***@{dom}"


def html_to_text(html: str) -> str:
    """Best-effort plain-text fallback derived from an HTML email. Keeps link URLs so the
    text version is still actionable in clients that don't render HTML."""
    s = re.sub(r"(?is)<(script|style|title)[^>]*>.*?</\1>", "", html)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|h[1-6]|li|table)>", "\n", s)
    s = re.sub(r'(?is)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
               lambda m: f"{re.sub(r'<[^>]+>', '', m.group(2)).strip()} ({m.group(1)})", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t​]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _read_template(name: str) -> str:
    path = _TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8")


def _fill(template: str, ctx: dict) -> str:
    """Substitute {{key}} placeholders. Using {{ }} avoids clashing with CSS braces and
    with '$' in money amounts. Any placeholder left unfilled is stripped, never leaked."""
    out = template
    for key, val in ctx.items():
        out = out.replace("{{" + key + "}}", "" if val is None else str(val))
    return re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "", out)


_LOGO_BYTES: bytes | None = None


def _logo_bytes() -> bytes | None:
    global _LOGO_BYTES
    if _LOGO_BYTES is None:
        try:
            _LOGO_BYTES = (_TEMPLATES_DIR / _LOGO_FILENAME).read_bytes()
        except OSError:
            logger.warning("email logo asset missing at %s; sending without inline logo",
                           _TEMPLATES_DIR / _LOGO_FILENAME)
            _LOGO_BYTES = b""
    return _LOGO_BYTES or None


def render_email(template_name: str, *, subject: str, preheader: str = "",
                 footer_note: str = "You're receiving this because you have a Petabyte "
                                    "Cloud account.", **ctx) -> tuple[str, str]:
    """Render a full HTML email (base chrome + content fragment) and its text fallback.
    Returns (html, text). User-supplied values must be pre-escaped by the caller."""
    fragment = _fill(_read_template(f"{template_name}.html"), ctx)
    year = ctx.get("year") or datetime.now(timezone.utc).year
    html = _fill(_read_template("base.html"), {
        "subject": subject, "preheader": preheader or subject,
        "content": fragment, "year": year, "footer_note": footer_note,
    })
    return html, html_to_text(html)


def _esc(v) -> str:
    return _html.escape("" if v is None else str(v))


# --- backends (provider-specific; swappable) --------------------------------------------
class EmailBackend(Protocol):
    def send(self, *, to, subject: str, html: str, text: str, from_addr: str,
             reply_to: str | None = None,
             inline: Iterable[tuple[str, bytes, str]] | None = None,
             tags: Iterable[str] | None = None) -> EmailResult: ...


class MailgunBackend:
    """All Mailgun-specific logic lives here. Reads MAILGUN_API_KEY / MAILGUN_DOMAIN from
    the environment; the API base is hardcoded. Nothing here is logged that could leak the
    key."""

    def __init__(self, *, api_key: str | None = None, domain: str | None = None,
                 api_base: str = MAILGUN_API_BASE, timeout: float = _DEFAULT_TIMEOUT):
        self._api_key = api_key if api_key is not None else os.getenv("MAILGUN_API_KEY", "")
        self._domain = domain if domain is not None else os.getenv("MAILGUN_DOMAIN", "")
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout

    def _require_config(self) -> None:
        missing = [n for n, v in (("MAILGUN_API_KEY", self._api_key),
                                  ("MAILGUN_DOMAIN", self._domain)) if not v]
        if missing:
            raise EmailConfigError("Mailgun is not configured: missing " + ", ".join(missing))

    def send(self, *, to, subject, html, text, from_addr, reply_to=None,
             inline=None, tags=None) -> EmailResult:
        self._require_config()
        url = f"{self._api_base}/v3/{self._domain}/messages"
        data: dict = {
            "from": from_addr,
            "to": to if isinstance(to, str) else ",".join(to),
            "subject": subject,
            "html": html,
            "text": text,
        }
        if reply_to:
            data["h:Reply-To"] = reply_to
        if tags:
            data["o:tag"] = list(tags)          # httpx repeats the field per tag
        files = [("inline", (name, content, ctype)) for name, content, ctype in (inline or [])]
        try:
            resp = httpx.post(url, auth=("api", self._api_key), data=data,
                              files=files or None, timeout=self._timeout)
        except httpx.TimeoutException as e:
            logger.error("email send TIMEOUT to=%s subject=%r: %s", _mask(to), subject, e)
            raise EmailSendError(f"mailgun request timed out: {e}") from e
        except httpx.HTTPError as e:            # DNS, connection, TLS, etc.
            logger.error("email send NETWORK error to=%s subject=%r: %s", _mask(to), subject, e)
            raise EmailSendError(f"mailgun request failed: {e}") from e

        if resp.status_code // 100 != 2:
            body = (resp.text or "")[:300]
            logger.error("email send FAILED status=%s to=%s subject=%r detail=%s",
                         resp.status_code, _mask(to), subject, body)
            raise EmailSendError(f"mailgun returned {resp.status_code}: {body}")

        message_id = None
        try:
            message_id = resp.json().get("id")
        except Exception:                       # noqa: BLE001 - body may not be JSON
            pass
        logger.info("email SENT id=%s status=%s to=%s subject=%r",
                    message_id, resp.status_code, _mask(to), subject)
        return EmailResult(ok=True, provider_message_id=message_id,
                           status_code=resp.status_code)


# --- high-level service -----------------------------------------------------------------
class EmailService:
    """Template-aware transactional email. Provider-neutral: give it any EmailBackend."""

    def __init__(self, backend: EmailBackend | None = None, *, default_from: str = DEFAULT_FROM):
        self._backend = backend if backend is not None else MailgunBackend()
        self._from = default_from

    def send(self, *, to, subject: str, html: str, text: str | None = None,
             reply_to: str | None = None, tags: Iterable[str] | None = None,
             embed_logo: bool = True) -> EmailResult:
        """Send a raw HTML email. A plain-text fallback is derived automatically when not
        given, and the Petabyte mark is embedded inline (cid:petabyte-logo.png)."""
        if not text:
            text = html_to_text(html)
        inline = None
        if embed_logo:
            data = _logo_bytes()
            if data:
                inline = [(_LOGO_FILENAME, data, "image/png")]
        return self._backend.send(to=to, subject=subject, html=html, text=text,
                                  from_addr=self._from, reply_to=reply_to,
                                  inline=inline, tags=tags)

    def send_template(self, template_name: str, *, to, subject: str, preheader: str = "",
                      tags: Iterable[str] | None = None, reply_to: str | None = None,
                      **ctx) -> EmailResult:
        html, text = render_email(template_name, subject=subject, preheader=preheader, **ctx)
        return self.send(to=to, subject=subject, html=html, text=text, reply_to=reply_to,
                         tags=tags)

    # ---- convenience senders (user-supplied strings are escaped) ----
    def send_welcome(self, to, *, name: str, dashboard_url: str) -> EmailResult:
        return self.send_template("welcome", to=to,
                                  subject="Welcome to Petabyte Cloud",
                                  preheader="Your Petabyte Cloud account is ready.",
                                  tags=["welcome"],
                                  name=_esc(name), cta_url=_esc(dashboard_url))

    def send_email_verification(self, to, *, verify_url: str, ttl_minutes: int = 15) -> EmailResult:
        return self.send_template("verification", to=to,
                                  subject="Verify your Petabyte Cloud email",
                                  preheader="Confirm your email to activate your account.",
                                  tags=["verification"],
                                  cta_url=_esc(verify_url), ttl_minutes=int(ttl_minutes))

    def send_password_reset(self, to, *, reset_url: str, ttl_minutes: int = 30) -> EmailResult:
        return self.send_template("password_reset", to=to,
                                  subject="Reset your Petabyte Cloud password",
                                  preheader="Choose a new password for your account.",
                                  tags=["password_reset"],
                                  cta_url=_esc(reset_url), ttl_minutes=int(ttl_minutes))

    def send_login_otp(self, to, *, code: str, ttl_minutes: int = 10) -> EmailResult:
        return self.send_template("login_otp", to=to,
                                  subject="Your Petabyte Cloud login code",
                                  preheader=f"Your one-time code is {code}.",
                                  tags=["login_otp"],
                                  code=_esc(code), ttl_minutes=int(ttl_minutes))

    def send_payment_receipt(self, to, *, amount: str, description: str, date: str,
                             reference: str, transaction_url: str) -> EmailResult:
        return self.send_template("payment_receipt", to=to,
                                  subject=f"Your Petabyte Cloud receipt ({reference})",
                                  preheader=f"Receipt {reference} — {amount}.",
                                  tags=["payment_receipt"],
                                  amount=_esc(amount), description=_esc(description),
                                  date=_esc(date), reference=_esc(reference),
                                  cta_url=_esc(transaction_url))

    def send_marketplace_notification(self, to, *, title: str, message: str,
                                      cta_label: str, cta_url: str) -> EmailResult:
        return self.send_template("marketplace_notification", to=to,
                                  subject=title,
                                  preheader=message[:120],
                                  tags=["marketplace"],
                                  title=_esc(title), message=_esc(message),
                                  cta_label=_esc(cta_label), cta_url=_esc(cta_url))


_SERVICE: EmailService | None = None


def get_email_service() -> EmailService:
    """Process-wide EmailService (Mailgun backend by default)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = EmailService()
    return _SERVICE
