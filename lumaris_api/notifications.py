"""Notification dispatch: render an event -> record -> send via the email provider.
Respects the user's email + opt-out. Safe no-op if the user has no email."""
from db import (get_user_by_id, record_notification, set_notification_status)
from notify_providers import get_email_provider

TEMPLATES = {
    "payout.requested": ("Your withdrawal is processing",
                         "We received your withdrawal of ${amount} via {kind}. "
                         "You'll get another email when it completes."),
    "payout.confirmed": ("Your withdrawal is complete",
                         "${amount} has been sent via {kind}. Reference: {ref}."),
    "payout.failed":    ("Your withdrawal failed",
                         "We couldn't complete your ${amount} {kind} withdrawal "
                         "({reason}). The amount was returned to your balance."),
    "booking.refunded": ("You were refunded",
                         "A node handling your job went offline; ${amount} was "
                         "refunded to your balance."),
    "job.completed":    ("Your job finished",
                         "Task #{task_id} completed on {provider}."),
}


def notify(db, user_id: int, event_type: str, **ctx) -> None:
    subject_t, body_t = TEMPLATES.get(event_type, (event_type, "{body}"))
    subject = subject_t.format(**ctx)
    body = body_t.format(**{**{"body": ""}, **ctx})
    user = get_user_by_id(db, user_id)
    if not user or not user.email or not user.notify_email:
        record_notification(db, user_id, event_type, subject, body, status="skipped")
        return
    n = record_notification(db, user_id, event_type, subject, body, status="queued")
    try:
        ok = get_email_provider().send(user.email, subject, body)
        set_notification_status(db, n, "sent" if ok else "failed")
    except Exception:
        set_notification_status(db, n, "failed")
