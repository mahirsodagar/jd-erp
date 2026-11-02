"""Registration fee paid straight after the application form.

Client rule (2026-11-02): a JD Institute (JDIFT) applicant who has just
submitted the self-fill application form is offered a "pay registration
fee" step on the spot. JD School of Design applicants are not — their
registration fee is collected with the installment plan after enrolment,
as before. Which institutes get the step is
`settings.REGISTRATION_FEE_AT_APPLICATION_INSTITUTES`.

The student has no Enrollment at that point (staff enrol them later,
choosing batch and semester), so the request hangs off the Student
(`PaymentRequest.student`, purpose REGISTRATION_FEE). The amount is the
fee template's `registration_fee` for the campus/program the student
applied to; the route is the usual one for a JDIFT registration fee
(Razorpay, Royalty account — `apps.payments.routing`).

When the gateway confirms the charge:

1. a receipt number is reserved from the campus series and the receipt
   PDF is mailed to the student (`fees.services.registration_receipt`);
2. if the student already has an enrollment, the FeeReceipt is written
   against that year's registration installment right away; otherwise
   `settle_registration_payment_on_enrollment` does it when staff
   create the enrollment, under the same receipt number — so the student
   is never asked for this year's registration fee again in the portal.

Optional by design: the step is shown when it can be paid online, and
hidden entirely (no manual fallback) when the fee is zero, has no route,
or the gateway is switched off for this environment.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import routing
from .errors import PaymentGatewayError
from .models import PaymentOrder, PaymentRequest
from .services import (
    NoOnlineRoute, _gateway_label, _payment_mode, gateway_usable,
    pay_url_for, payable_route,
)

logger = logging.getLogger("apps.payments")

DEFAULT_INSTITUTES = ("JDIFT",)
ZERO = Decimal("0.00")


# ---------------------------------------------------------------------
# Eligibility and amount
# ---------------------------------------------------------------------

def offered_to(student) -> bool:
    """Whether this student's institute collects the registration fee at
    application time. Read off the program, which is where the ERP
    records the institute."""
    program = getattr(student, "program", None)
    code = (getattr(getattr(program, "institute", None), "code", "") or "").upper()
    allowed = getattr(
        settings, "REGISTRATION_FEE_AT_APPLICATION_INSTITUTES", DEFAULT_INSTITUTES,
    )
    return bool(code) and code in {str(c).upper() for c in allowed}


def registration_fee_amount_for(student) -> Decimal:
    """The fee template's registration fee for the student's campus and
    program — the student's academic year when a template exists for it,
    else the newest active program-wide template, matching what the
    public form shows in its fee panel. Zero when nothing matches."""
    from apps.master.models import FeeTemplate

    base = FeeTemplate.objects.filter(
        campus=student.campus, program=student.program,
        course__isnull=True, is_active=True,
    )
    tmpl = (
        base.filter(academic_year=student.academic_year).first()
        or base.order_by("-academic_year__id", "-id").first()
    )
    return Decimal(getattr(tmpl, "registration_fee", None) or 0)


# ---------------------------------------------------------------------
# Raising the request
# ---------------------------------------------------------------------

def _requests_for(student):
    return PaymentRequest.objects.filter(
        student=student, purpose=PaymentRequest.Purpose.REGISTRATION_FEE,
    )


def paid_registration_fee_request(student) -> PaymentRequest | None:
    return (
        _requests_for(student)
        .filter(status=PaymentRequest.Status.PAID)
        .select_related("paid_order")
        .order_by("-paid_at")
        .first()
    )


def open_registration_fee_request(student) -> PaymentRequest | None:
    return (
        _requests_for(student)
        .filter(status=PaymentRequest.Status.PENDING)
        .order_by("-created_on")
        .first()
    )


def registration_fee_request_for(student, *, actor=None) -> PaymentRequest | None:
    """The payable (or already paid) request for this student's
    registration fee, raising one when none exists.

    Returns None — quietly — whenever the step should not be offered:
    wrong institute, zero fee, no online route, gateway off or broken.
    A broken gateway is logged, since someone should fix it; the student
    simply doesn't see the button.

    A pending request whose amount or route no longer matches is
    cancelled, not reused: its token would still open a live payment
    page for the stale figure. Makes no network call.
    """
    if not offered_to(student):
        return None

    paid = paid_registration_fee_request(student)
    if paid is not None:
        return paid

    amount = registration_fee_amount_for(student)
    if amount <= ZERO:
        return None

    try:
        route = payable_route(
            routing.route_for_student_registration(student),
            f"the registration fee of student {student.pk}",
        )
    except NoOnlineRoute as e:
        logger.info("payments: %s Registration-fee step hidden.", e)
        return None
    except PaymentGatewayError as e:
        logger.error("payments: %s Registration-fee step hidden.", e)
        return None

    existing = open_registration_fee_request(student)
    if existing is not None:
        if (
            existing.amount == amount
            and existing.gateway == route.gateway
            and existing.account == route.account
        ):
            return existing
        existing.status = PaymentRequest.Status.CANCELLED
        existing.save(update_fields=["status", "updated_on"])

    return PaymentRequest.objects.create(
        purpose=PaymentRequest.Purpose.REGISTRATION_FEE,
        student=student,
        gateway=route.gateway,
        account=route.account,
        amount=amount,
        description=f"Registration fee — {student.student_name}",
        created_by=actor,
    )


def registration_payment_summary(student, *, create: bool = False) -> dict | None:
    """What the public form (and staff screens) show about this step.

    `None` means "show nothing". Otherwise::

        {"status": "DUE" | "PAID", "amount": "10000.00",
         "pay_url": "...", "gateway": "razorpay",
         "paid_at": iso | None, "receipt_no": "", "reference": ""}

    With `create=False` an existing request is reported but none is
    raised — the GET prefill must not write.
    """
    if create:
        pr = registration_fee_request_for(student)
    else:
        pr = (
            paid_registration_fee_request(student)
            or open_registration_fee_request(student)
        )
    if pr is None:
        return None

    if pr.status == PaymentRequest.Status.PAID:
        order = pr.paid_order
        return {
            "status": "PAID",
            "request_id": pr.id,
            "amount": str(pr.amount),
            "pay_url": "",
            "gateway": pr.gateway,
            "paid_at": pr.paid_at.isoformat() if pr.paid_at else None,
            "receipt_no": pr.receipt_no,
            "reference": (order.txn_id or order.order_id) if order else "",
        }

    # Still due. Hidden if the gateway can't take the payment right now
    # (switched off since the request was raised) — the client asked for
    # no half-working "pay" button.
    if not gateway_usable(pr.gateway, pr.account):
        return None
    try:
        url = pay_url_for(pr)
    except PaymentGatewayError as e:
        logger.error("payments: cannot build registration pay link: %s", e)
        return None
    return {
        "status": "DUE",
        "request_id": pr.id,
        "amount": str(pr.amount),
        "pay_url": url,
        "gateway": pr.gateway,
        "paid_at": None,
        "receipt_no": "",
        "reference": "",
    }


# ---------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------

def _receipted(order: PaymentOrder) -> bool:
    from apps.fees.models import FeeReceipt
    return FeeReceipt.objects.filter(instrument_ref=order.order_id).exists()


def _current_enrollment(student):
    from apps.admissions.services import current_enrollment
    return current_enrollment(student)


def _write_fee_receipt(payment_request: PaymentRequest, order: PaymentOrder,
                       enrollment, *, actor=None):
    """The accounts row for a settled registration payment, against this
    year's registration installment. Same shape as a counter receipt so
    balances, reports and the portal all see it as paid. Idempotent on
    `instrument_ref == order_id`."""
    from apps.fees.models import FeeReceipt
    from apps.fees.services.receipt_no import generate_receipt_no
    from apps.fees.services.registration import ensure_registration_installment

    if _receipted(order):
        return None

    installment = ensure_registration_installment(enrollment, actor=actor)
    if installment is not None and installment.enrollment_id != enrollment.id:
        # Already charged under an earlier enrollment this year (mid-year
        # promotion). Receipt against that row — it is the one the money
        # pays for.
        enrollment = installment.enrollment

    if not payment_request.receipt_no:
        payment_request.receipt_no = generate_receipt_no(
            campus_code=enrollment.campus.code,
        )
        payment_request.save(update_fields=["receipt_no", "updated_on"])

    charged_at = order.charged_at or timezone.now()
    label = _gateway_label(payment_request)
    return FeeReceipt.objects.create(
        receipt_no=payment_request.receipt_no,
        enrollment=enrollment,
        installment=installment,
        basic_fee=order.amount,
        amount=order.amount,
        payment_mode=_payment_mode(order),
        instrument_ref=order.order_id,
        bank=label[:120],
        received_date=timezone.localtime(charged_at).date(),
        notes=(
            f"Registration fee paid online at application via {label} "
            f"(order {order.order_id}"
            + (f", txn {order.txn_id}" if order.txn_id else "")
            + (f", {order.payment_method}" if order.payment_method else "")
            + ")."
        ),
        received_by=None,
    )


def settle_paid_registration_fee(payment_request: PaymentRequest, order: PaymentOrder) -> None:
    """Called from `apply_order_body` once the gateway says CHARGED.

    Reserves the receipt number, mails the receipt, and — when the
    student already has an enrollment — writes the FeeReceipt now.
    Mail goes after commit so a rollback can't leave the student holding
    a receipt for a payment the ERP never recorded.
    """
    from apps.fees.services.receipt_no import generate_receipt_no

    student = payment_request.student
    if student is None:
        return

    if not payment_request.receipt_no:
        payment_request.receipt_no = generate_receipt_no(
            campus_code=student.campus.code,
        )
        payment_request.save(update_fields=["receipt_no", "updated_on"])

    enrollment = _current_enrollment(student)
    if enrollment is not None:
        _write_fee_receipt(payment_request, order, enrollment)

    def _mail():
        from apps.fees.services.registration_receipt import (
            send_registration_payment_receipt,
        )
        send_registration_payment_receipt(payment_request, order)

    transaction.on_commit(_mail)


def settle_registration_payment_on_enrollment(enrollment, *, actor=None):
    """Hook for enrolment: a registration fee the student paid at
    application time becomes this year's registration receipt.

    Returns the FeeReceipt written, or None when there was nothing to
    settle (no paid request, or already receipted). Never raises — a
    settlement problem must not block the enrolment itself.
    """
    try:
        pr = paid_registration_fee_request(enrollment.student)
        if pr is None or pr.paid_order is None:
            return None
        return _write_fee_receipt(pr, pr.paid_order, enrollment, actor=actor)
    except Exception:  # noqa: BLE001 — enrolment must still go through
        logger.exception(
            "payments: could not settle the registration fee paid at "
            "application against enrollment %s.", enrollment.pk,
        )
        return None
