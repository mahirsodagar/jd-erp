"""Email the application fee receipt PDF to the lead the moment the fee
is marked paid — by the gateway (`payments.services._mark_lead_fee_paid`)
or by hand (`leads.views.LeadMarkFeePaidView`).

Twin of `receipt_email.send_receipt_email` for a fee that has no
FeeReceipt row: the PDF comes from `application_receipt`, the number
from `Lead.application_fee_receipt_no`. To the lead, campus receipts
inbox + accounts in CC, Reply-To per policy (CAMPUS_RECEIPTS). Never
raises — a mail failure must not undo the payment.

Idempotent per lead: a replayed webhook or a second mark-paid does not
mail twice (a SENT dispatch-log row for the lead already exists).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .application_receipt import (
    ApplicationFeeReceipt, ensure_application_fee_receipt_no,
    render_application_fee_receipt,
)
from .receipt_email import campus_inbox_for

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "fees.application_fee_receipt.email"


def _compose(lead, receipt: ApplicationFeeReceipt) -> tuple[str, str]:
    inst = receipt.enrollment.student.institute
    inst_name = getattr(inst, "name", "") or "JD Institute"
    amount = f"{Decimal(receipt.amount):,.2f}"
    subject = f"Application fee receipt {receipt.receipt_no} — {lead.name}"
    body = (
        f"Dear {lead.name},\n\n"
        f"We have received your application fee. The receipt is attached.\n\n"
        f"Receipt no:   {receipt.receipt_no}\n"
        f"Amount:       Rs. {amount}\n"
        f"Towards:      {receipt.particular}\n"
        f"Date:         {receipt.received_date.strftime('%d-%m-%Y')}\n"
        f"Mode:         {receipt.get_payment_mode_display()}\n"
        + (f"Program:      {lead.program.name}\n" if lead.program_id else "")
        + f"Campus:       {lead.campus.name}\n\n"
        f"Please keep this receipt for your records. Our admissions team "
        f"will share the application form link with you.\n\n"
        f"Regards,\nAccounts Office\n{inst_name}"
    )
    return subject, body


def already_sent(lead) -> bool:
    ct = ContentType.objects.get_for_model(lead.__class__)
    return NotificationDispatchLog.objects.filter(
        content_type=ct, object_id=str(lead.pk), template_key=TEMPLATE_KEY,
        status=NotificationDispatchLog.Status.SENT,
    ).exists()


def send_application_fee_receipt(lead) -> NotificationDispatchLog | None:
    """Mail the application fee receipt to the lead. Returns the dispatch
    log, or None when nothing was sent (not paid, nobody to send to, or
    already sent). Never raises."""
    try:
        if lead.application_fee_paid_at is None:
            return None
        if already_sent(lead):
            return None
        ensure_application_fee_receipt_no(lead)
        receipt = ApplicationFeeReceipt(lead)

        lead_email = (lead.email or "").strip()
        campus_email = campus_inbox_for(lead.campus)
        accounts = (getattr(settings, "ACCOUNTS_INBOX", "") or "").strip()
        to = lead_email or campus_email
        cc = [e for e in (campus_email, accounts)
              if e and e.lower() != to.lower()]
        if not to:
            logger.info("Application fee receipt %s: no recipient.",
                        receipt.receipt_no)
            return None

        subject, body = _compose(lead, receipt)
        log = NotificationDispatchLog.objects.create(
            channel=NotificationTemplate.Channel.EMAIL,
            template_key=TEMPLATE_KEY, recipient=to, cc=", ".join(cc),
            subject=subject, body=body, related_object=lead,
        )

        from apps.notifications.email import send_email
        from apps.notifications.reply_to import resolve_reply_to

        pdf = render_application_fee_receipt(lead)
        ok, detail = send_email(
            recipient=to, cc=", ".join(cc), subject=subject, body=body,
            attachments=[(f"{receipt.receipt_no}.pdf", pdf, "application/pdf")],
            reply_to=resolve_reply_to(
                TEMPLATE_KEY, {"campus_code": getattr(lead.campus, "code", "")},
            ),
        )
        log.status = (NotificationDispatchLog.Status.SENT if ok
                      else NotificationDispatchLog.Status.FAILED)
        log.sent_at = timezone.now() if ok else None
        log.error = "" if ok else detail
        log.save(update_fields=["status", "sent_at", "error"])
        if not ok:
            logger.warning("Application fee receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, detail)
        return log
    except Exception:  # noqa: BLE001 — never break the payment
        logger.exception("Application fee receipt email failed for lead id=%s",
                         getattr(lead, "pk", None))
        return None
