"""Email delivery as swappable adapters. STUB records without sending; wire a real
provider for production (SendGrid / AWS SES / Postmark)."""
import os


class EmailProvider:
    def send(self, to: str, subject: str, body: str) -> bool:
        raise NotImplementedError


class StubEmailProvider(EmailProvider):
    def send(self, to: str, subject: str, body: str) -> bool:
        return True                     # no external call; caller records it


import httpx

_FROM = lambda: os.getenv("EMAIL_FROM", "no-reply@petabyte.market")


class SendGridProvider(EmailProvider):
    def send(self, to, subject, body):
        r = httpx.post("https://api.sendgrid.com/v3/mail/send", timeout=20,
                       headers={"Authorization": f"Bearer {os.environ['SENDGRID_API_KEY']}",
                                "Content-Type": "application/json"},
                       json={"personalizations": [{"to": [{"email": to}]}],
                             "from": {"email": _FROM()}, "subject": subject,
                             "content": [{"type": "text/plain", "value": body}]})
        return r.status_code in (200, 202)


class SESProvider(EmailProvider):
    def send(self, to, subject, body):
        import boto3
        ses = boto3.client("ses", region_name=os.getenv("AWS_REGION", "us-east-1"))
        ses.send_email(Source=_FROM(), Destination={"ToAddresses": [to]},
                       Message={"Subject": {"Data": subject},
                                "Body": {"Text": {"Data": body}}})
        return True


class PostmarkProvider(EmailProvider):
    def send(self, to, subject, body):
        r = httpx.post("https://api.postmarkapp.com/email", timeout=20,
                       headers={"X-Postmark-Server-Token": os.environ["POSTMARK_TOKEN"],
                                "Content-Type": "application/json"},
                       json={"From": _FROM(), "To": to, "Subject": subject,
                             "TextBody": body})
        return r.status_code == 200


def get_email_provider() -> EmailProvider:
    if os.getenv("NOTIFY_STUB", "").lower() == "true":
        return StubEmailProvider()
    which = os.getenv("EMAIL_PROVIDER", "ses").lower()
    return {"sendgrid": SendGridProvider, "ses": SESProvider,
            "postmark": PostmarkProvider}.get(which, StubEmailProvider)()
