"""Email the receipt PDF when a fee payment is recorded.

Fires for both ways a receipt comes into being — keyed at the counter
(`FeeReceiptListCreateView`) and settled online through the portal
(`payments.services._record_installment_receipt`). One message goes to
the student with the campus receipts inbox in CC, so both parties hold
the same copy. The campus inbox comes from `FEE_RECEIPT_CAMPUS_INBOXES`
(keyed on `Campus.code`); a campus with no inbox configured still gets
the student copy.

Best-effort: a mail problem is logged in `NotificationDispatchLog` and
never fails the receipt itself.
"""

import logging

from django.conf import settings

from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .pdf import render_receipt_pdf

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "fees.receipt.email"


def campus_inbox_for(campus) -> str:
    """The receipts mailbox for this campus, or "" when none is set."""
    inboxes = getattr(settings, "FEE_RECEIPT_CAMPUS_INBOXES", {}) or {}
    code = (getattr(campus, "code", "") or "").strip().upper()
    return (inboxes.get(code) or "").strip()


def _transport(degree_type: str):
    """(smtp_config, from_email) for the receipt trigger. The policy is
    course-aware (diploma vs degree domain); MSG91 cannot carry a PDF,
    so a MSG91 verdict falls back to the default SMTP connection."""
    from apps.notifications.sender import resolve_sender, transport_for

    sender = resolve_sender(TEMPLATE_KEY, degree_type=degree_type)
    if sender is None:
        return None, ""
    kind, smtp_cfg = transport_for(sender.domain)
    if kind != "smtp":
        smtp_cfg = None
    return smtp_cfg, (sender.from_email if sender.is_live else "")


def _compose(receipt) -> tuple[str, str]:
    enrollment = receipt.enrollment
    student = enrollment.student
    institute = getattr(student, "institute", None)
    inst_name = getattr(institute, "name", "") or "JD Institute"
    amount = f"{receipt.amount:,.2f}"
    particular = (
        receipt.installment.description
        if receipt.installment_id and getattr(receipt.installment, "description", "")
        else (receipt.other_fee.name if receipt.other_fee_id else "Fee payment")
    )
    subject = f"Fee receipt {receipt.receipt_no} — {student.student_name}"
    body = (
        f"Dear {student.student_name},\n\n"
        f"We have received your payment. The receipt is attached.\n\n"
        f"Receipt no:   {receipt.receipt_no}\n"
        f"Amount:       Rs. {amount}\n"
        f"Towards:      {particular}\n"
        f"Date:         {receipt.received_date.strftime('%d-%m-%Y')}\n"
        f"Mode:         {receipt.get_payment_mode_display()}\n"
        f"Program:      {enrollment.program.name}\n"
        f"Campus:       {enrollment.campus.name}\n\n"
        f"Please keep this receipt for your records.\n\n"
        f"Regards,\nAccounts Office\n{inst_name}"
    )
    return subject, body


def send_receipt_email(receipt) -> NotificationDispatchLog | None:
    """Send the receipt PDF to the student and the campus inbox.

    Returns the dispatch log row, or None when there was nobody to send
    to. Never raises.
    """
    try:
        enrollment = receipt.enrollment
        student = enrollment.student
        student_email = (student.student_email or "").strip()
        campus_email = campus_inbox_for(enrollment.campus)
        accounts = (getattr(settings, "ACCOUNTS_INBOX", "") or "").strip()

        # Student in To; campus (and the optional accounts group) in CC.
        # With no student address the campus copy still goes out.
        to = student_email or campus_email
        cc = [e for e in (campus_email, accounts)
              if e and e.lower() != to.lower()]
        if not to:
            logger.info("Receipt %s: no recipient (student has no email, "
                        "campus %s has no inbox).", receipt.receipt_no,
                        enrollment.campus.code)
            return None

        subject, body = _compose(receipt)
        log = NotificationDispatchLog.objects.create(
            channel=NotificationTemplate.Channel.EMAIL,
            template_key=TEMPLATE_KEY, recipient=to, cc=", ".join(cc),
            subject=subject, body=body, related_object=receipt,
        )

        if not getattr(settings, "EMAIL_SMTP_OUTBOUND_ENABLED", True):
            log.error = "SMTP outbound disabled on this host."
            log.save(update_fields=["error"])
            return log

        from django.utils import timezone

        from apps.notifications.email import send_email

        pdf = render_receipt_pdf(receipt)
        smtp_cfg, from_email = _transport(
            getattr(enrollment.program, "degree_type", "") or "",
        )
        ok, detail = send_email(
            recipient=to, cc=", ".join(cc), subject=subject, body=body,
            attachments=[(f"{receipt.receipt_no}.pdf", pdf, "application/pdf")],
            smtp=smtp_cfg, from_email=from_email,
        )
        log.status = (NotificationDispatchLog.Status.SENT if ok
                      else NotificationDispatchLog.Status.FAILED)
        log.sent_at = timezone.now() if ok else None
        log.error = "" if ok else detail
        log.save(update_fields=["status", "sent_at", "error"])
        if not ok:
            logger.warning("Receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, detail)
        return log
    except Exception:  # noqa: BLE001 — never break receipt creation
        logger.exception("Receipt email failed for receipt id=%s",
                         getattr(receipt, "pk", None))
        return None
