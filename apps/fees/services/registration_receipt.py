"""Receipt for a registration fee paid at application time.

The student pays before any enrollment exists, so there is no FeeReceipt
row to print yet — that is written when staff enrol them
(`payments.registration_fee.settle_registration_payment_on_enrollment`).
The client wants the receipt in the student's inbox the moment the
payment lands, so this renders the ordinary receipt PDF from a stand-in
that looks like a FeeReceipt to `fees.services.pdf`, under the receipt
number already reserved on the PaymentRequest. The FeeReceipt written
later carries the same number, so the two are one document.

Best-effort: a mail problem is logged in `NotificationDispatchLog` and
never fails the payment.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.fees.models import FeeReceipt
from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .pdf import render_receipt_pdf
from .receipt_email import _transport, campus_inbox_for
from .registration import REGISTRATION_DESCRIPTION

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "fees.receipt.email"


class _Placement:
    """Stands in for the Enrollment the PDF reads its course/year off."""

    def __init__(self, student):
        self.student = student
        self.academic_year = student.academic_year
        self.course = student.course
        self.course_id = student.course_id
        self.program = student.program
        self.campus = student.campus


class RegistrationReceipt:
    """Duck-typed FeeReceipt for a settled REGISTRATION_FEE request."""

    Status = FeeReceipt.Status
    installment_id = None
    other_fee_id = None
    received_by_id = None
    sgst = cgst = igst = Decimal("0.00")
    status = FeeReceipt.Status.ACTIVE
    particular = REGISTRATION_DESCRIPTION

    def __init__(self, payment_request, order):
        from apps.payments.services import _gateway_label, _payment_mode

        self.receipt_no = payment_request.receipt_no
        self.enrollment = _Placement(payment_request.student)
        self.basic_fee = order.amount
        self.amount = order.amount
        self._mode = _payment_mode(order)
        self.instrument_ref = order.order_id
        self.bank = _gateway_label(payment_request)[:120]
        charged_at = order.charged_at or timezone.now()
        self.received_date = timezone.localtime(charged_at).date()
        self.created_on = charged_at

    def get_payment_mode_display(self) -> str:
        return str(dict(FeeReceipt.PaymentMode.choices).get(self._mode, self._mode))


def _compose(receipt: RegistrationReceipt) -> tuple[str, str]:
    student = receipt.enrollment.student
    institute = getattr(student, "institute", None)
    inst_name = getattr(institute, "name", "") or "JD Institute"
    amount = f"{Decimal(receipt.amount):,.2f}"
    subject = f"Fee receipt {receipt.receipt_no} — {student.student_name}"
    body = (
        f"Dear {student.student_name},\n\n"
        f"We have received your registration fee. The receipt is attached.\n\n"
        f"Receipt no:   {receipt.receipt_no}\n"
        f"Amount:       Rs. {amount}\n"
        f"Towards:      {receipt.particular}\n"
        f"Date:         {receipt.received_date.strftime('%d-%m-%Y')}\n"
        f"Mode:         {receipt.get_payment_mode_display()}\n"
        f"Program:      {student.program.name}\n"
        f"Campus:       {student.campus.name}\n\n"
        f"Please keep this receipt for your records. Our admissions team "
        f"will contact you about enrolment.\n\n"
        f"Regards,\nAccounts Office\n{inst_name}"
    )
    return subject, body


def send_registration_payment_receipt(payment_request, order) -> NotificationDispatchLog | None:
    """Mail the receipt PDF to the student with the campus receipts
    inbox in CC. Returns the dispatch log, or None when there was nobody
    to send to. Never raises."""
    try:
        receipt = RegistrationReceipt(payment_request, order)
        student = payment_request.student
        student_email = (student.student_email or "").strip()
        campus_email = campus_inbox_for(student.campus)
        accounts = (getattr(settings, "ACCOUNTS_INBOX", "") or "").strip()

        to = student_email or campus_email
        cc = [e for e in (campus_email, accounts)
              if e and e.lower() != to.lower()]
        if not to:
            logger.info("Registration receipt %s: no recipient.", receipt.receipt_no)
            return None

        subject, body = _compose(receipt)
        log = NotificationDispatchLog.objects.create(
            channel=NotificationTemplate.Channel.EMAIL,
            template_key=TEMPLATE_KEY, recipient=to, cc=", ".join(cc),
            subject=subject, body=body, related_object=payment_request,
        )

        if not getattr(settings, "EMAIL_SMTP_OUTBOUND_ENABLED", True):
            log.error = "SMTP outbound disabled on this host."
            log.save(update_fields=["error"])
            return log

        from apps.notifications.email import send_email

        pdf = render_receipt_pdf(receipt)
        smtp_cfg, from_email = _transport(
            getattr(student.program, "degree_type", "") or "",
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
            logger.warning("Registration receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, detail)
        return log
    except Exception:  # noqa: BLE001 — never break the settlement
        logger.exception("Registration receipt email failed for request id=%s",
                         getattr(payment_request, "pk", None))
        return None
