"""Email the receipt PDF when a fee payment is recorded.

Fires for both ways a receipt comes into being — keyed at the counter
(`FeeReceiptListCreateView`) and settled online through the portal
(`payments.services._record_installment_receipt`). One message goes to
the student with the campus receipts inbox in CC, so both parties hold
the same copy. The campus inbox comes from `FEE_RECEIPT_CAMPUS_INBOXES`
(keyed on `Campus.code`); a campus with no inbox configured still gets
the student copy.

Wording = system e-mail `fees.receipt.email` (Communication → System
Emails). Best-effort: a mail problem is logged in
`NotificationDispatchLog` and never fails the receipt itself.
"""

import logging

from django.conf import settings

from apps.notifications.context import enrollment_vars, receipt_vars
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import send_system_email

from .pdf import render_receipt_pdf

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "fees.receipt.email"


def campus_inbox_for(campus) -> str:
    """The receipts mailbox for this campus, or "" when none is set."""
    inboxes = getattr(settings, "FEE_RECEIPT_CAMPUS_INBOXES", {}) or {}
    code = (getattr(campus, "code", "") or "").strip().upper()
    return (inboxes.get(code) or "").strip()


def receipt_recipients(primary_email: str, campus) -> tuple[str, list[str]]:
    """`(to, cc)` for any receipt mail: the person in To (else the campus
    receipts inbox), campus inbox + Accounts in CC, no duplicates."""
    campus_email = campus_inbox_for(campus)
    accounts = (getattr(settings, "ACCOUNTS_INBOX", "") or "").strip()
    to = (primary_email or "").strip() or campus_email
    cc = [e for e in (campus_email, accounts) if e and e.lower() != to.lower()]
    return to, cc


def send_receipt_email(receipt) -> NotificationDispatchLog | None:
    """Send the receipt PDF to the student and the campus inbox.

    Returns the dispatch log row, or None when there was nobody to send
    to. Never raises.
    """
    try:
        enrollment = receipt.enrollment
        student = enrollment.student
        to, cc = receipt_recipients(student.student_email, enrollment.campus)
        if not to:
            logger.info("Receipt %s: no recipient (student has no email, "
                        "campus %s has no inbox).", receipt.receipt_no,
                        enrollment.campus.code)
            return None

        pdf = render_receipt_pdf(receipt)
        # Replies go to the campus receipts inbox (policy CAMPUS_RECEIPTS).
        log = send_system_email(
            TEMPLATE_KEY, recipient=to, cc=cc, related=receipt,
            context={**enrollment_vars(enrollment), **receipt_vars(receipt)},
            attachments=[(f"{receipt.receipt_no}.pdf", pdf, "application/pdf")],
        )
        if log.status != NotificationDispatchLog.Status.SENT:
            logger.warning("Receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, log.error)
        return log
    except Exception:  # noqa: BLE001 — never break receipt creation
        logger.exception("Receipt email failed for receipt id=%s",
                         getattr(receipt, "pk", None))
        return None
