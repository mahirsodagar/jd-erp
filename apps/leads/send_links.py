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

from django.conf import settings
from django.utils import timezone

from apps.notifications.services import queue_notification

from .models import Lead, LeadCommunication


# --- Defaults — keep in sync with PHP `sendapplink.php` / `sendfeelink.php` ---

_DEFAULT_LINKS = {
    "JDIFT": {
        "label": "JD Institute of Fashion Technology",
        "app_url": "https://admin.jediiians.com/admission/jdift_application_link.php?sid={phone}",
        "fee_url": "https://9cfb.short.gy/jdinst",
    },
    "JDSD": {
        "label": "JD School of Design",
        "app_url": "https://admin.jediiians.com/admission/jdsd_application_link.php?sid={phone}",
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

def send_application_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    """Queue SMS + email with the application form link, log a
    `LeadCommunication` row.

    Returns dict with ids of the dispatch log + communication row.
    """
    cfg = _institute_config(institute_key)
    url = cfg["app_url"].format(phone=lead.phone, lead_id=lead.id)
    institute_label = cfg["label"]

    sms_body = (
        f"Dear {lead.name}, thank you for selecting {institute_label}. "
        f"Please complete your application: {url}"
    )
    email_subject = f"{institute_label} — Application Link"
    email_body = (
        f"Dear {lead.name},\n\n"
        f"Thank you for selecting {institute_label}. Please click the "
        f"link below to complete your application:\n\n{url}\n\n"
        f"With regards,\n{institute_label}"
    )

    sms_log = queue_notification(
        template_key="lead.application_link.sms",
        recipient=lead.phone,
        context={
            "name": lead.name, "url": url, "institute": institute_label,
            "lead_id": lead.id,
        },
        related=lead,
    )
    email_log = None
    if lead.email:
        email_log = queue_notification(
            template_key="lead.application_link.email",
            recipient=lead.email,
            context={
                "name": lead.name, "url": url, "institute": institute_label,
                "lead_id": lead.id,
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
        "url": url,
        "institute": institute_label,
    }


def send_fee_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    cfg = _institute_config(institute_key)
    url = cfg["fee_url"]
    institute_label = cfg["label"]

    sms_body = (
        f"Dear {lead.name}, greetings from {institute_label}. "
        f"Please click {url} to pay your fees and complete admission."
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
