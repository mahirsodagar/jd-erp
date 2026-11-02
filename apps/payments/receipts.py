"""The receipt PDF behind a paid PaymentRequest, whatever it was for.

One resolver for the staff download (`PaymentRequestReceiptPdfView`) and
the payer's own download on the public result page
(`PublicPaymentReceiptView`), so both hand out the same document:

- FEE_INSTALLMENT  → the FeeReceipt written at settlement
- REGISTRATION_FEE → the FeeReceipt once the student is enrolled, else
                     the pre-enrolment stand-in under the reserved number
- OTHER_FEE        → the FeeReceipt written at settlement
- APPLICATION_FEE  → the lead's application fee receipt
"""

from __future__ import annotations

from django.http import HttpResponse

from .models import PaymentRequest


def receipt_pdf_for_request(pr: PaymentRequest) -> tuple[bytes, str] | None:
    """(pdf_bytes, receipt_no) for a PAID request, or None when there is
    nothing to print yet."""
    if pr.status != PaymentRequest.Status.PAID or pr.paid_order_id is None:
        return None
    order = pr.paid_order

    from apps.fees.models import FeeReceipt
    from apps.fees.services.pdf import render_receipt_pdf

    receipt = (
        FeeReceipt.objects
        .select_related(
            "enrollment", "enrollment__student", "enrollment__campus",
            "enrollment__batch", "enrollment__program",
            "enrollment__student__institute", "installment", "other_fee",
            "received_by",
        )
        .filter(instrument_ref=order.order_id)
        .first()
    )
    if receipt is not None:
        return render_receipt_pdf(receipt), receipt.receipt_no

    if pr.purpose == PaymentRequest.Purpose.REGISTRATION_FEE and pr.student_id:
        from apps.fees.services.registration_receipt import RegistrationReceipt

        if not pr.receipt_no:
            return None
        stand_in = RegistrationReceipt(pr, order)
        return render_receipt_pdf(stand_in), pr.receipt_no

    if pr.purpose == PaymentRequest.Purpose.APPLICATION_FEE and pr.lead_id:
        from apps.fees.services.application_receipt import (
            render_application_fee_receipt,
        )

        lead = pr.lead
        if lead.application_fee_paid_at is None:
            return None
        pdf = render_application_fee_receipt(lead)
        return pdf, lead.application_fee_receipt_no

    return None


def pdf_response(pdf: bytes, receipt_no: str) -> HttpResponse:
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{receipt_no}.pdf"'
    return resp
