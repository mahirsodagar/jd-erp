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

from django.contrib.contenttypes.models import ContentType

from apps.notifications.context import lead_vars, receipt_vars
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import send_system_email

from .application_receipt import (
    ApplicationFeeReceipt, ensure_application_fee_receipt_no,
    render_application_fee_receipt,
)
from .receipt_email import receipt_recipients

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "fees.application_fee_receipt.email"


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

        to, cc = receipt_recipients(lead.email, lead.campus)
        if not to:
            logger.info("Application fee receipt %s: no recipient.",
                        receipt.receipt_no)
            return None

        pdf = render_application_fee_receipt(lead)
        # Replies to the campus receipts inbox (policy CAMPUS_RECEIPTS) —
        # the lead builder's counsellor Reply-To is dropped on purpose.
        ctx = {**lead_vars(lead), **receipt_vars(receipt, particular=receipt.particular)}
        ctx.pop("reply_to", None)
        log = send_system_email(
            TEMPLATE_KEY, recipient=to, cc=cc, related=lead, context=ctx,
            attachments=[(f"{receipt.receipt_no}.pdf", pdf, "application/pdf")],
        )
        if log.status != NotificationDispatchLog.Status.SENT:
            logger.warning("Application fee receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, log.error)
        return log
    except Exception:  # noqa: BLE001 — never break the payment
        logger.exception("Application fee receipt email failed for lead id=%s",
                         getattr(lead, "pk", None))
        return None
