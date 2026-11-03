"""Registration fee paid straight after the application form.

Kept as the registration-only face of `apps.payments.applicant_fees`,
which (since 2026-11-03) handles the whole "Pay fees" page — registration
for every institute, course and other fee for JDSD. The names below are
what the admissions views, the student serializer and the tests call;
each is a thin wrapper over the generic machinery so the registration
behaviour stays exactly as it was:

- the request hangs off the Student (`PaymentRequest.student`, purpose
  REGISTRATION_FEE) and routes through Razorpay (Royalty account);
- the amount is the fee template's `registration_fee` for the campus and
  program applied to, picked the way the enrolment screen picks it;
- the step is shown when it can be paid online and hidden otherwise;
- paying reserves a receipt number, mails the receipt, and settles
  against this year's REGISTRATION installment at enrolment under the
  same number.
"""

from __future__ import annotations

from decimal import Decimal

from . import applicant_fees as _af
from .applicant_fees import (  # noqa: F401 — re-exported
    REGISTRATION, ZERO, fee_amounts, fee_template_for, offered_to,
    write_registration_receipt as _write_fee_receipt,
)
from .models import PaymentOrder, PaymentRequest

DEFAULT_INSTITUTES = ()


def registration_fee_amount_for(student) -> Decimal:
    """The fee template's registration fee for the student's campus and
    program — see `applicant_fees.fee_template_for`. Zero when nothing
    matches."""
    return fee_amounts(fee_template_for(student))[REGISTRATION]


def paid_registration_fee_request(student) -> PaymentRequest | None:
    return _af.paid_request(student, REGISTRATION)


def open_registration_fee_request(student) -> PaymentRequest | None:
    return _af.open_request(student, REGISTRATION)


def registration_fee_request_for(student, *, actor=None) -> PaymentRequest | None:
    return _af.request_for(student, REGISTRATION, actor=actor)


def registration_payment_summary(student, *, create: bool = False) -> dict | None:
    """What the staff screens show about this step.

    `None` means "show nothing". Otherwise::

        {"status": "DUE" | "PAID", "amount": "10000.00",
         "pay_url": "...", "gateway": "razorpay",
         "paid_at": iso | None, "receipt_no": "", "reference": ""}

    With `create=False` an existing request is reported but none is
    raised — the GET prefill must not write.
    """
    amount = registration_fee_amount_for(student)
    row = _af.row_for(student, REGISTRATION, amount, create=create)
    if row is None or row["status"] == _af.STATUS_OFFLINE:
        return None
    return {k: v for k, v in row.items() if k not in ("kind", "label")}


def settle_paid_registration_fee(payment_request: PaymentRequest, order: PaymentOrder) -> None:
    _af.settle_paid_applicant_fee(payment_request, order)


def settle_registration_payment_on_enrollment(enrollment, *, actor=None):
    """Hook for enrolment: a registration fee the student paid at
    application time becomes this year's registration receipt.

    Returns the FeeReceipt written, or None when there was nothing to
    settle (no paid request, or already receipted). Never raises.
    """
    try:
        pr = paid_registration_fee_request(enrollment.student)
        if pr is None or pr.paid_order is None:
            return None
        return _write_fee_receipt(pr, pr.paid_order, enrollment, actor=actor)
    except Exception:  # noqa: BLE001 — enrolment must still go through
        _af.logger.exception(
            "payments: could not settle the registration fee paid at "
            "application against enrollment %s.", enrollment.pk,
        )
        return None
