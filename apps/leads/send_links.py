"""Send-link / send-message helpers used by the leads "Send" actions.

These wrap `apps.notifications.services.queue_notification` so the
intent always lands in `NotificationDispatchLog`, and ALSO write a
`LeadCommunication` row so the activity timeline shows what was sent.

Outbound delivery is handled by the notifications dispatcher — on PA
free the row stays at status='QUEUED' until a real provider is wired.

Configuration lives in `settings`:

    LEAD_LINKS = {
        "JDIFT": {
            "label":     "JD Institute of Fashion Technology",
            "app_url":   "https://admin.jediiians.com/admission/jdift_application_link.php?sid={phone}",
            "fee_url":   "https://9cfb.short.gy/jdinst",
        },
        "JDSD": {
            "label":     "JD School of Design",
            "app_url":   "https://admin.jediiians.com/admission/jdsd_application_link.php?sid={phone}",
            "fee_url":   "https://9cfb.short.gy/jdsd",
        },
    }

Override per environment via env / config.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.utils import timezone

from apps.notifications.services import queue_notification

from .models import Lead, LeadCommunication


# --- Defaults — keep in sync with PHP `sendapplink.php` / `sendfeelink.php` ---

_DEFAULT_LINKS = {
    "JDIFT": {
        "label": "JD Institute of Fashion Technology",
        # `short_name` is the variable the DLT fee template expects.
        "short_name": "JD Institute",
        # Pre-shortened fee link from PHP — DLT-approved as-is.
        "fee_url": "https://9cfb.short.gy/jdinst",
    },
    "JDSD": {
        "label": "JD School of Design",
        "short_name": "JD School",
        "fee_url": "https://9cfb.short.gy/jdsd",
    },
}


def _institute_config(institute_key: str) -> dict:
    cfg = getattr(settings, "LEAD_LINKS", _DEFAULT_LINKS)
    if institute_key not in cfg:
        raise ValueError(
            f"Unknown institute '{institute_key}'. "
            f"Configure settings.LEAD_LINKS or pass one of: {list(cfg.keys())}."
        )
    return cfg[institute_key]


# --- Send actions -----------------------------------------------------------

def _ensure_token(lead: Lead) -> uuid.UUID:
    """Generate or reuse the lead's application token. Reuses the existing
    one if present so resending gives the same link."""
    if lead.application_token is None:
        lead.application_token = uuid.uuid4()
        lead.application_token_sent_at = timezone.now()
        lead.save(update_fields=["application_token", "application_token_sent_at"])
    else:
        lead.application_token_sent_at = timezone.now()
        lead.save(update_fields=["application_token_sent_at"])
    return lead.application_token


def send_application_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    """Queue SMS + email with the application form link, log a
    `LeadCommunication` row.

    SMS body matches the PHP-side DLT-approved template
    (template_id `1307167852052800815`), so the only variables are
    {name} and {url}, and {url} resolves to a `tinyurl.com/...` slug.
    """
    from apps.notifications.shorten import shorten

    cfg = _institute_config(institute_key)
    institute_label = cfg["label"]

    # Build the React app URL the student will open, then shorten it to
    # match the DLT template format (`tinyurl.com/{slug}`).
    # The SPA uses createHashRouter, so the route lives after `#`.
    # On static hosts (Netlify) without SPA fallback rewrites, a `#`-less
    # URL like `/apply/{token}` would 404 on direct hit.
    token = _ensure_token(lead)
    base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    long_url = f"{base}/#/apply/{token}"
    short_url = shorten(long_url)

    # PHP DLT template wording — keep verbatim.
    sms_body = (
        f"Dear {lead.name}, Thank you for selecting JD, Your inquiry has "
        f"been submitted. Please click the link to complete your "
        f"application - {short_url}"
    )
    email_subject = f"JD Student Application Link : {lead.name}"
    email_body = (
        "Greetings from JD!\n"
        f"Dear {lead.name},\n\n"
        "Thank you for selecting JD, Your inquiry has been submitted.\n\n"
        f"Please click the link to complete your application - {long_url}\n\n"
        "With Regards,\nJD"
    )

    sms_log = queue_notification(
        template_key="lead.application_link.sms",
        recipient=lead.phone,
        context={"name": lead.name, "url": short_url},
        related=lead,
    )
    email_log = None
    if lead.email:
        email_log = queue_notification(
            template_key="lead.application_link.email",
            recipient=lead.email,
            context={
                "name": lead.name, "url": long_url,
                "institute": institute_label,
            },
            related=lead,
        )

    comm = LeadCommunication.objects.create(
        lead=lead,
        type=LeadCommunication.Type.SMS,
        subject=email_subject,
        message=sms_body,
        sent_at=timezone.now(),
        logged_by=actor,
    )

    return {
        "sms_log_id": getattr(sms_log, "id", None),
        "email_log_id": getattr(email_log, "id", None),
        "communication_id": comm.id,
        "url": long_url,
        "short_url": short_url,
        "institute": institute_label,
    }


def send_fee_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    cfg = _institute_config(institute_key)
    url = cfg["fee_url"]
    short_name = cfg.get("short_name", cfg["label"])
    institute_label = cfg["label"]

    # PHP DLT template wording (template_id 1307168958796572350).
    sms_body = (
        f"Dear student, Greetings of the day! Thank you for choosing "
        f"{short_name} for your Design/Art/Media course. Click the "
        f"following link {url} to pay your fees and complete the "
        f"admission process. Best Regards JD Admissions Team"
    )

    sms_log = queue_notification(
        template_key="lead.fee_link.sms",
        recipient=lead.phone,
        context={
            "name": lead.name, "url": url, "institute": institute_label,
            "lead_id": lead.id,
        },
        related=lead,
    )

    comm = LeadCommunication.objects.create(
        lead=lead,
        type=LeadCommunication.Type.SMS,
        subject=f"{institute_label} — Fee Link",
        message=sms_body,
        sent_at=timezone.now(),
        logged_by=actor,
    )

    return {
        "sms_log_id": getattr(sms_log, "id", None),
        "communication_id": comm.id,
        "url": url,
        "institute": institute_label,
    }


def send_welcome_message(*, lead: Lead, actor=None) -> dict:
    if not lead.email:
        raise ValueError("Lead has no email on file.")

    subject = "Welcome Note for New Students and Parents"
    body = (
        f"Dear {lead.name},\n\n"
        "Thank you for choosing JD as the place to pursue further "
        "education! We are happy to welcome you onboard.\n\n"
        "Our endeavours have always been to provide our students with a "
        "cohesive learning environment that encompasses practical and "
        "theoretical education.\n\n"
        "For any clarifications or queries you can reach out to your "
        "administrative office.\n\n"
        "See you very soon!\n\nRegards,\nJD"
    )

    email_log = queue_notification(
        template_key="lead.welcome.email",
        recipient=lead.email,
        context={"name": lead.name, "lead_id": lead.id},
        related=lead,
    )

    comm = LeadCommunication.objects.create(
        lead=lead,
        type=LeadCommunication.Type.EMAIL,
        subject=subject,
        message=body,
        sent_at=timezone.now(),
        logged_by=actor,
    )

    return {
        "email_log_id": getattr(email_log, "id", None),
        "communication_id": comm.id,
    }
