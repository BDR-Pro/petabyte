"""email_integration_test.py — OPT-IN real send via the Mailgun HTTP API.

Sends a genuine transactional email (HTML + plain-text, inline logo) to the address
below and prints the Mailgun message id. SKIPS cleanly (exit 0) when MAILGUN_API_KEY is
absent, so CI without the secret, forks, and offline dev are unaffected.

Requires: MAILGUN_API_KEY (secret) and MAILGUN_DOMAIN (e.g. petabyte.market).
Run:      python email_integration_test.py
CI:       the `email-integration` job runs this when the repo secret is present.
"""
import os
import sys

TO = os.getenv("MAILGUN_TEST_RECIPIENT", "baderalotaibi3@gmail.com")
SUBJECT = "Petabyte Mailgun Integration Test"

_key = os.getenv("MAILGUN_API_KEY", "")
_domain = os.getenv("MAILGUN_DOMAIN", "")
if not _key:
    print("SKIP: MAILGUN_API_KEY not set — real send skipped "
          "(expected in CI without the secret, in forks, and offline).")
    sys.exit(0)
if not _domain:
    print("REFUSING: MAILGUN_DOMAIN is not set; cannot send.")
    sys.exit(1)

from email_service import EmailService, MailgunBackend, EmailError, render_email  # noqa: E402

html, text = render_email(
    "marketplace_notification",
    subject=SUBJECT,
    preheader="Confirming Petabyte's Mailgun HTTP API integration.",
    title="Mailgun integration test ✅",
    message=("This email was sent through Petabyte Cloud's Mailgun HTTP API integration. "
             "If you can read this with the logo in the header, HTML rendering, the "
             "plain-text fallback, and DKIM/SPF alignment are all working."),
    cta_label="Open Petabyte Cloud",
    cta_url="https://petabyte.market",
)

svc = EmailService(MailgunBackend())   # reads MAILGUN_API_KEY / MAILGUN_DOMAIN from env
try:
    res = svc.send(to=TO, subject=SUBJECT, html=html, text=text, tags=["integration-test"])
except EmailError as e:
    print(f"FAIL: send raised {type(e).__name__}: {e}")
    sys.exit(1)

ok = res.ok and bool(res.provider_message_id)
print(("PASS" if ok else "FAIL") +
      f": to={TO} status={res.status_code} mailgun_message_id={res.provider_message_id}")
print(f"    (HTML {len(html)} bytes, text fallback {len(text)} bytes, inline logo embedded)")
sys.exit(0 if ok else 1)
