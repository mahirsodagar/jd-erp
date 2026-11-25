"""Receipt for a fee paid at application time — registration, course or
other fee (`payments.applicant_fees`).

The student pays before any enrollment exists, so there is no FeeReceipt
row to print yet — that is written when staff enrol them
(`payments.applicant_fees.settle_applicant_payments_on_enrollment`).
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

from django.utils import timezone

from apps.fees.models import FeeReceipt
from apps.notifications.context import receipt_vars, student_vars
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import send_system_email

from .pdf import render_receipt_pdf
from .receipt_email import receipt_recipients
from .registration import REGISTRATION_DESCRIPTION

logger = logging.getLogger(__name__)

# Its own system e-mail (Communication → System Emails): the wording
# differs from the counter receipt ("our admissions team will contact
# you about enrolment").
TEMPLATE_KEY = "fees.applicant_receipt.email"


class _Placement:
    """Stands in for the Enrollment the PDF reads its course/year off."""

    def __init__(self, student):
        self.student = student
        self.academic_year = student.academic_year
        self.course = student.course
        self.course_id = student.course_id
        self.program = student.program
        self.campus = student.campus


def particular_for(purpose: str) -> str:
    """What the receipt says the money was towards."""
    from apps.payments.applicant_fees import BY_PURPOSE, REGISTRATION

    kind = BY_PURPOSE.get(purpose)
    if kind is None or kind is REGISTRATION:
        return REGISTRATION_DESCRIPTION
    return kind.label


class RegistrationReceipt:
    """Duck-typed FeeReceipt for a settled applicant-fee request
    (REGISTRATION_FEE, COURSE_FEE or OTHER_FEE_APPLICANT)."""

    Status = FeeReceipt.Status
    installment_id = None
    other_fee_id = None
    received_by_id = None
    sgst = cgst = igst = Decimal("0.00")
    status = FeeReceipt.Status.ACTIVE
    particular = REGISTRATION_DESCRIPTION

    def __init__(self, payment_request, order):
        from apps.payments.services import _gateway_label, _payment_mode

        self.particular = particular_for(payment_request.purpose)
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


def send_registration_payment_receipt(payment_request, order) -> NotificationDispatchLog | None:
    """Mail the receipt PDF to the student with the campus receipts
    inbox in CC. Returns the dispatch log, or None when there was nobody
    to send to. Never raises."""
    try:
        receipt = RegistrationReceipt(payment_request, order)
        student = payment_request.student
        to, cc = receipt_recipients(student.student_email, student.campus)
        if not to:
            logger.info("Registration receipt %s: no recipient.", receipt.receipt_no)
            return None

        pdf = render_receipt_pdf(receipt)
        log = send_system_email(
            TEMPLATE_KEY, recipient=to, cc=cc, related=payment_request,
            context={
                **student_vars(student),
                **receipt_vars(receipt, particular=receipt.particular),
            },
            attachments=[(f"{receipt.receipt_no}.pdf", pdf, "application/pdf")],
        )
        if log.status != NotificationDispatchLog.Status.SENT:
            logger.warning("Registration receipt %s email to %s failed: %s",
                           receipt.receipt_no, to, log.error)
        return log
    except Exception:  # noqa: BLE001 — never break the settlement
        logger.exception("Registration receipt email failed for request id=%s",
                         getattr(payment_request, "pk", None))
        return None
