"""Receipt for a lead's application fee.

The application fee is paid before the person is a Student, so there is
no FeeReceipt row and no Enrollment for `fees.services.pdf` to read. This
renders the ordinary receipt PDF from stand-ins built off the Lead, the
same trick `registration_receipt` uses for the pre-enrolment
registration fee, under a number reserved from the campus receipt series
(`Lead.application_fee_receipt_no`).
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.fees.models import FeeReceipt
from apps.master.models import AcademicYear, Institute

from .pdf import render_receipt_pdf
from .receipt_no import generate_receipt_no

APPLICATION_DESCRIPTION = "Application fee"


def ensure_application_fee_receipt_no(lead) -> str:
    """Reserve a receipt number for a paid application fee, once.

    Called when the fee is marked paid (by hand or by the gateway) and
    again, defensively, when the PDF is requested — leads marked paid
    before the number existed get one on first download.
    """
    if lead.application_fee_receipt_no:
        return lead.application_fee_receipt_no
    if lead.application_fee_paid_at is None:
        raise ValueError("Application fee is not marked paid.")
    year = timezone.localtime(lead.application_fee_paid_at).year
    lead.application_fee_receipt_no = generate_receipt_no(
        campus_code=lead.campus.code, year=year,
    )
    lead.save(update_fields=["application_fee_receipt_no"])
    return lead.application_fee_receipt_no


def _institute_for(lead):
    program = lead.program
    if program is not None and program.institute_id:
        return program.institute
    inst = lead.campus.institutes.first()
    return inst or Institute.objects.order_by("id").first()


class _Applicant:
    """Stands in for the Student the PDF prints the name block from."""

    registration_number = ""
    father_name = ""
    current_address = ""
    current_city_id = None
    current_city = None
    current_state_id = None
    current_state = None
    current_pincode = ""

    def __init__(self, lead):
        self.student_name = lead.name
        self.application_form_id = f"LEAD-{lead.id}"
        self.student_mobile = lead.phone
        self.student_email = lead.email
        self.institute = _institute_for(lead)
        parts = [p for p in (lead.city, lead.state) if p]
        self.current_address = ", ".join(parts)


class _Placement:
    """Stands in for the Enrollment the PDF reads its course/year off."""

    course = None
    course_id = None

    def __init__(self, lead, student):
        self.student = student
        self.program = lead.program
        self.campus = lead.campus
        self.academic_year = (
            AcademicYear.objects.filter(is_current=True).first()
            or AcademicYear.objects.order_by("-start_date").first()
        )


class ApplicationFeeReceipt:
    """Duck-typed FeeReceipt for a paid application fee."""

    Status = FeeReceipt.Status
    installment_id = None
    other_fee_id = None
    sgst = cgst = igst = Decimal("0.00")
    status = FeeReceipt.Status.ACTIVE
    particular = APPLICATION_DESCRIPTION

    def __init__(self, lead):
        self.receipt_no = lead.application_fee_receipt_no
        student = _Applicant(lead)
        self.enrollment = _Placement(lead, student)
        amount = Decimal(lead.application_fee_amount or 0)
        self.basic_fee = amount
        self.amount = amount
        self._mode = (lead.application_fee_mode or "ONLINE").upper()
        self.instrument_ref = lead.application_fee_ref
        self.bank = _bank_label(lead)
        paid_at = lead.application_fee_paid_at or timezone.now()
        self.received_date = timezone.localtime(paid_at).date()
        self.created_on = paid_at
        self.received_by_id = lead.application_fee_recorded_by_id
        self.received_by = lead.application_fee_recorded_by

    def get_payment_mode_display(self) -> str:
        return str(dict(FeeReceipt.PaymentMode.choices).get(self._mode, self._mode.title()))


def _bank_label(lead) -> str:
    """"HDFC SmartGateway — JD Educational Trust" for an online payment,
    read back off the paid request; blank for a counter entry."""
    from apps.payments.models import PaymentRequest
    from apps.payments.services import _gateway_label

    pr = (
        PaymentRequest.objects
        .filter(lead=lead, purpose=PaymentRequest.Purpose.APPLICATION_FEE,
                status=PaymentRequest.Status.PAID)
        .order_by("-paid_at")
        .first()
    )
    return _gateway_label(pr)[:120] if pr else ""


def render_application_fee_receipt(lead) -> bytes:
    ensure_application_fee_receipt_no(lead)
    return render_receipt_pdf(ApplicationFeeReceipt(lead))
