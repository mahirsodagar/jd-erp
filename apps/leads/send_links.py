"""Send-link / send-message helpers used by the leads "Send" actions.

These wrap `apps.notifications.services.queue_notification` so the
intent always lands in `NotificationDispatchLog`, and ALSO write a
`LeadCommunication` row so the activity timeline shows what was sent.

Per-institute payment account details (UPI VPA + bank) live in
``settings.INSTITUTE_PAYMENT_DETAILS``, keyed by the institute code
(``JDIFT`` / ``JDSD``). Override per environment via ``.env``.
"""

from __future__ import annotations

import io
import uuid
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from apps.notifications.services import queue_notification

from .models import Lead, LeadCommunication


# --- Dispatch-status helpers ------------------------------------------------

def _sms_result(log) -> dict:
    """Flatten a queued SMS dispatch log into the API fields the UI reads.

    `queue_notification` returns a NotificationDispatchLog whose status is
    already SENT / FAILED (SMS dispatches synchronously) — surface it so
    the counsellor sees the real outcome, not a static "queued". On the
    off chance a ScheduledNotification comes back (future fire_at), report
    it as QUEUED with no error.
    """
    return {
        "sms_log_id": getattr(log, "id", None),
        "sms_status": getattr(log, "status", "QUEUED"),
        "sms_error": getattr(log, "error", "") or "",
    }


def _wa_result(log) -> dict:
    """Flatten the WhatsApp leg into the API fields the UI reads.

    WhatsApp dispatches synchronously through XIRCLS, so the log status is
    already SENT / FAILED. While `WHATSAPP_ENABLED` is off the row stays
    QUEUED (nothing sent) — surfaced here as status=QUEUED, no error.
    """
    return {
        "wa_log_id": getattr(log, "id", None),
        "wa_status": getattr(log, "status", "QUEUED"),
        "wa_error": getattr(log, "error", "") or "",
    }


def _email_result(log) -> dict:
    """Flatten the email leg. `log` is None when the lead has no email."""
    if log is None:
        return {"email_log_id": None, "email_sent": False, "email_error": ""}
    sent = getattr(log, "status", "") == "SENT"
    return {
        "email_log_id": getattr(log, "id", None),
        "email_sent": sent,
        "email_error": "" if sent else (getattr(log, "error", "") or ""),
    }


def _first_name(full_name: str) -> str:
    """First whitespace-delimited token of a name, for SMS greetings.

    "Disha Jivani" -> "Disha", "Jethva Hemangi" -> "Jethva". Falls back to
    the whole value when there's no space (single name) or it's blank.
    """
    parts = (full_name or "").split()
    return parts[0] if parts else (full_name or "")


# --- Institute lookup -------------------------------------------------------

def _payment_details(institute_key: str) -> dict:
    """Return UPI / bank details for the institute. Raises if not configured."""
    cfg = getattr(settings, "INSTITUTE_PAYMENT_DETAILS", {})
    if institute_key not in cfg:
        raise ValueError(
            f"No INSTITUTE_PAYMENT_DETAILS entry for '{institute_key}'. "
            f"Configure it in settings/env. Known keys: {list(cfg.keys())}.",
        )
    return cfg[institute_key]


def _application_fee_for_lead(lead: Lead, payment: dict) -> str:
    """Resolve the application-fee amount to print on the fee link email.

    Lookup order:
      1. Active FeeTemplate matching (campus, program) — pick the most
         recent if several years exist (lead has no academic_year FK).
      2. Static `default_amount` from settings.INSTITUTE_PAYMENT_DETAILS,
         used only as a last-resort fallback so the email can still go.
      3. Empty string — UPI URI then drops the amount and the student
         types it in their app.
    """
    from apps.master.models import FeeTemplate

    if lead.campus_id and lead.program_id:
        tmpl = (
            FeeTemplate.objects
            .filter(
                campus_id=lead.campus_id,
                program_id=lead.program_id,
                is_active=True,
            )
            .order_by("-academic_year__id", "-id")
            .first()
        )
        if tmpl and tmpl.application_fee:
            return str(tmpl.application_fee)
    return str(payment.get("default_amount") or "")


# --- Token plumbing for the public application form ------------------------

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


# --- Application form link --------------------------------------------------

def send_application_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    """Queue SMS + email with the application form link, log a
    `LeadCommunication` row.

    Gated: the application fee MUST be marked paid first. Counsellors
    use `send_fee_link` to email payment instructions, then mark the
    fee paid via the leads API once it's received in the bank.
    """
    if lead.application_fee_paid_at is None:
        raise ValueError(
            "Application fee must be marked paid before the application "
            "link can be sent. Use 'Send Fee Link' first, collect the "
            "payment, then mark it paid on the lead.",
        )

    from apps.notifications.shorten import shorten

    payment = _payment_details(institute_key)
    institute_label = payment["payee_name"]

    token = _ensure_token(lead)
    base = getattr(settings, "FRONTEND_BASE_URL", "https://jdsd.netlify.app").rstrip("/")
    long_url = f"{base}/#/apply/{token}"
    short_url = shorten(long_url)

    first_name = _first_name(lead.name)
    sms_body = (
        f"Dear{first_name}, Thank you for selecting JD, Your inquiry has been submitted. Please click the link to complete your application - {short_url}"
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
        context={"name": first_name, "url": short_url},
        related=lead,
    )
    # WhatsApp leg — same recipient/link as the SMS. Routed through XIRCLS
    # (trigger "application_form"); stays QUEUED until WHATSAPP_ENABLED
    # is on, so this never breaks the SMS/email send if WhatsApp is off.
    wa_log = queue_notification(
        template_key="lead.application_link.wa",
        recipient=lead.phone,
        context={"name": first_name, "url": short_url},
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
                # Drives the From domain (Diploma → jdinstitute.edu.in,
                # Degree/Bachelors → jdindia.com). See notifications.sender.
                "degree_type": (
                    lead.program.degree_type if lead.program_id else ""
                ),
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
        **_sms_result(sms_log),
        **_wa_result(wa_log),
        **_email_result(email_log),
        "communication_id": comm.id,
        "url": long_url,
        "short_url": short_url,
        "institute": institute_label,
    }


# --- Fee instructions email + SMS notice -----------------------------------

def _upi_deeplink(*, vpa: str, payee_name: str, amount: str, note: str) -> str:
    """Build a UPI intent URI per NPCI spec.

    Most Indian UPI apps will scan the QR built from this URI and
    pre-fill payee + amount.
    """
    parts = [
        f"pa={quote(vpa)}",
        f"pn={quote(payee_name)}",
        f"cu=INR",
    ]
    if amount:
        parts.append(f"am={quote(str(amount))}")
    if note:
        parts.append(f"tn={quote(note)}")
    return "upi://pay?" + "&".join(parts)


def _qr_png_bytes(uri: str) -> bytes:
    """Render the UPI URI as a PNG QR. Uses `qrcode[pil]` (already in reqs)."""
    import qrcode

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fee_email_html(*, lead: Lead, payment: dict, amount: str, qr_cid: str) -> str:
    """Inline-styled HTML so it survives most mail clients."""
    amount_line = (
        f'<p style="margin: 4px 0 0 0; font-size: 13px;">Amount: '
        f'<strong>&#8377;{amount}</strong></p>'
        if amount
        else ""
    )
    return f"""\
<!doctype html>
<html><body style="font-family: Arial, sans-serif; color: #1f2937; max-width: 560px;">
<p>Dear {lead.name},</p>

<p>Thank you for choosing <strong>{payment['payee_name']}</strong>.
To complete your application, please pay the application fee using
any of the options below.</p>

<table style="border-collapse: collapse; margin-top: 16px;">
  <tr>
    <td style="padding-right: 24px; vertical-align: top;">
      <p style="margin: 0 0 4px 0; font-weight: 600;">Scan to pay (any UPI app)</p>
      <img src="cid:{qr_cid}" alt="UPI QR" style="width: 220px; height: 220px; border: 1px solid #e5e7eb; border-radius: 8px;">
      <p style="margin: 8px 0 0 0; font-size: 13px;">UPI ID: <strong>{payment['vpa']}</strong></p>
      {amount_line}
    </td>
    <td style="vertical-align: top;">
      <p style="margin: 0 0 4px 0; font-weight: 600;">Bank transfer (NEFT / RTGS / IMPS)</p>
      <table style="font-size: 13px; border-collapse: collapse;">
        <tr><td style="padding: 2px 12px 2px 0; color: #6b7280;">Account name</td><td style="padding: 2px 0;">{payment['ac_name']}</td></tr>
        <tr><td style="padding: 2px 12px 2px 0; color: #6b7280;">Account no</td><td style="padding: 2px 0; font-family: monospace;">{payment['ac_no']}</td></tr>
        <tr><td style="padding: 2px 12px 2px 0; color: #6b7280;">IFSC</td><td style="padding: 2px 0; font-family: monospace;">{payment['ifsc']}</td></tr>
        <tr><td style="padding: 2px 12px 2px 0; color: #6b7280;">Bank</td><td style="padding: 2px 0;">{payment['bank']}</td></tr>
        <tr><td style="padding: 2px 12px 2px 0; color: #6b7280;">Branch</td><td style="padding: 2px 0;">{payment['branch']}</td></tr>
      </table>
    </td>
  </tr>
</table>

<p style="margin-top: 20px;">After paying, please reply to this email with
the payment reference (UPI transaction ID / bank reference number) so
we can verify and send your application form link.</p>

<p style="margin-top: 24px;">With Regards,<br>JD Admissions Team</p>
</body></html>
"""


def _fee_email_text(*, lead: Lead, payment: dict, amount: str) -> str:
    """Plain-text fallback for clients that won't render HTML."""
    fee_phrase = (
        f"the application fee of Rs.{amount}"
        if amount
        else "the application fee"
    )
    return (
        f"Dear {lead.name},\n\n"
        f"Thank you for choosing {payment['payee_name']}. To complete "
        f"your application, please pay {fee_phrase} using any of the "
        f"options below.\n\n"
        f"UPI\n"
        f"  UPI ID: {payment['vpa']}\n"
        f"  Payee:  {payment['payee_name']}\n\n"
        f"Bank transfer\n"
        f"  Account name: {payment['ac_name']}\n"
        f"  Account no:   {payment['ac_no']}\n"
        f"  IFSC:         {payment['ifsc']}\n"
        f"  Bank:         {payment['bank']}\n"
        f"  Branch:       {payment['branch']}\n\n"
        f"After paying, please reply with the transaction / reference "
        f"number so we can verify and send your application form link.\n\n"
        f"With Regards,\nJD Admissions Team"
    )


def send_fee_link(*, lead: Lead, institute_key: str, actor=None) -> dict:
    """Send the fee-payment link to the lead by both SMS and email.

    Matches `send_application_link`'s pattern: both legs go through
    `queue_notification(...)` (so they land in the dispatch log and use
    the registered templates), and both reference the same per-institute
    short URL from `settings.FEE_LINK_URLS`. The SMS body matches the
    legacy PHP DLT-approved wording (template_id 1307168958796572350).
    """
    payment = _payment_details(institute_key)
    institute_label = payment["payee_name"]
    short_name = payment.get("short_name", institute_label)

    fee_urls = getattr(settings, "FEE_LINK_URLS", {}) or {}
    url = fee_urls.get(institute_key)
    if not url:
        raise ValueError(
            f"No fee-link URL configured for institute '{institute_key}'. "
            f"Set FEE_LINK_URLS[{institute_key!r}] in settings or env.",
        )

    # SMS — verbatim DLT wording from PHP (`sendfeelink.php`).
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
            # First name only for the SMS greeting. The current DLT body
            # greets "Dear student" (no name), so this has no visible
            # effect today — it keeps the fee-link SMS correct if the
            # template is ever swapped for a name-bearing one.
            "name": _first_name(lead.name), "url": url,
            "institute": institute_label, "short_name": short_name,
        },
        related=lead,
    )

    # WhatsApp leg — same recipient/link as the SMS. Routed through XIRCLS
    # (trigger from XIRCLS_WA_TRIGGERS["lead.fee_link.wa"]). Dormant until
    # that trigger is filled in settings, so it never breaks SMS/email.
    wa_log = queue_notification(
        template_key="lead.fee_link.wa",
        recipient=lead.phone,
        context={
            "name": _first_name(lead.name), "url": url,
            "institute": institute_label, "short_name": short_name,
        },
        related=lead,
    )

    # Email — same pattern as send_application_link: short body, link
    # in plain text, routed through the dispatcher.
    email_subject = f"{institute_label} — Application fee payment link"
    email_body = (
        f"Dear {lead.name},\n\n"
        f"Thank you for choosing {institute_label} for your Design/Art/"
        f"Media course.\n\n"
        f"Click the link below to pay your fees and complete the "
        f"admission process:\n\n{url}\n\n"
        f"Best Regards,\nJD Admissions Team"
    )
    email_log = None
    if lead.email:
        email_log = queue_notification(
            template_key="lead.fee_link.email",
            recipient=lead.email,
            context={
                "name": lead.name, "url": url,
                "institute": institute_label,
                # Drives the From domain (Diploma → jdinstitute.edu.in,
                # Degree/Bachelors → jdindia.com). See notifications.sender.
                "degree_type": (
                    lead.program.degree_type if lead.program_id else ""
                ),
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

    lead.fee_link_sent_at = timezone.now()
    lead.save(update_fields=["fee_link_sent_at"])

    return {
        **_sms_result(sms_log),
        **_wa_result(wa_log),
        **_email_result(email_log),
        "communication_id": comm.id,
        "url": url,
        "institute": institute_label,
    }


# Kept for any callers that still want a rich UPI/QR HTML email — not
# wired into send_fee_link any more. Use this directly when you need
# the embedded QR + bank-transfer block.
def send_fee_payment_instructions_email(
    *, lead: Lead, institute_key: str, actor=None,
) -> dict:
    """Rich HTML email with UPI deeplink, QR code, and bank-transfer
    details. Use this when a counsellor wants the student to have full
    payment-method options instead of just a short URL."""
    payment = _payment_details(institute_key)
    institute_label = payment["payee_name"]
    amount = _application_fee_for_lead(lead, payment)

    if not lead.email:
        raise ValueError("Lead has no email on file.")

    upi_uri = _upi_deeplink(
        vpa=payment["vpa"],
        payee_name=payment["payee_name"],
        amount=amount,
        note=f"Application fee L{lead.id}",
    )
    qr_bytes = _qr_png_bytes(upi_uri)
    qr_cid = f"qr-{lead.id}-{int(timezone.now().timestamp())}"

    subject = f"{institute_label} — Application fee payment instructions"
    text_body = _fee_email_text(lead=lead, payment=payment, amount=amount)
    html_body = _fee_email_html(
        lead=lead, payment=payment, amount=amount, qr_cid=qr_cid,
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[lead.email],
    )
    msg.attach_alternative(html_body, "text/html")
    qr_attachment = _build_inline_image(qr_bytes, qr_cid, "fee-qr.png")
    msg.attach(qr_attachment)
    msg.mixed_subtype = "related"

    email_ok = False
    email_err = ""
    try:
        sent = msg.send(fail_silently=False)
        email_ok = bool(sent)
    except Exception as e:
        email_err = f"{type(e).__name__}: {e}"

    comm = LeadCommunication.objects.create(
        lead=lead,
        type=LeadCommunication.Type.EMAIL,
        subject=subject,
        message=text_body,
        sent_at=timezone.now(),
        logged_by=actor,
    )

    return {
        "email_sent": email_ok,
        "email_error": email_err,
        "communication_id": comm.id,
        "institute": institute_label,
        "amount": amount,
    }


def _build_inline_image(data: bytes, cid: str, filename: str):
    """Wrap PNG bytes as a MIME image with a CID for HTML inline use."""
    from email.mime.image import MIMEImage

    img = MIMEImage(data, _subtype="png")
    img.add_header("Content-ID", f"<{cid}>")
    img.add_header("Content-Disposition", "inline", filename=filename)
    return img


# --- Welcome ----------------------------------------------------------------

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
