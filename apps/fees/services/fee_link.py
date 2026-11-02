"""Staff-triggered "Send fee link" for an enrolled student.

The student is emailed a link for the *next payable installment* — the
same earliest-row-with-a-balance the portal lets them pay, so the link
and the portal can never disagree about what is due.

The link is a tokenised pay URL (`PaymentRequest`) whenever the fee has
an online route, which makes the payment self-reconciling: the gateway
confirms the charge and the receipt is written automatically. When it
has none (e.g. JDIFT course installments — see `apps.payments.routing`)
our manual-payment page (UPI QR + bank details, `apps.payments.manual`)
goes out instead, and accounts records the receipt by hand as before.

Email only for now: there is no DLT-approved SMS template for this yet.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.conf import settings

from apps.notifications.services import queue_notification

logger = logging.getLogger(__name__)


class FeeLinkError(ValueError):
    """Nothing can be sent — the message is shown to staff as-is."""


def _money(amount: Decimal) -> str:
    d = Decimal(amount).quantize(Decimal("1.00"))
    return f"{d:.0f}" if d == d.to_integral_value() else f"{d:.2f}"


def _manual_url(institute_key: str, *, amount: Decimal, label: str) -> str:
    from apps.payments.manual import manual_pay_url

    try:
        return manual_pay_url(institute_key, amount=amount, purpose=label)
    except ValueError as e:
        raise FeeLinkError(
            f"Online payment is not available for this fee and the manual "
            f"fee link can't be built for institute "
            f"'{institute_key or '—'}': {e}",
        ) from e


def _pay_url(installment, *, amount: Decimal, institute_key: str, label: str, actor):
    """`(url, payment_request_or_None)` — gateway link, else manual page."""
    from apps.payments import routing
    from apps.payments.errors import PaymentGatewayError
    from apps.payments.services import (
        NoOnlineRoute, installment_request_for, pay_url_for, payable_route,
    )

    try:
        payable_route(
            routing.route_for_installment(installment),
            f"installment {installment.pk}",
        )
    except NoOnlineRoute as e:
        logger.info("fees: %s Sending the manual fee link.", e)
        return _manual_url(institute_key, amount=amount, label=label), None
    except PaymentGatewayError as e:
        logger.error("fees: %s Sending the manual fee link instead.", e)
        return _manual_url(institute_key, amount=amount, label=label), None

    try:
        payment_request = installment_request_for(
            installment, amount=amount, actor=actor,
        )
    except PaymentGatewayError as e:
        logger.warning(
            "fees: pay request failed for installment %s (%s) — "
            "falling back to the manual fee link.", installment.pk, e,
        )
        return _manual_url(institute_key, amount=amount, label=label), None

    return pay_url_for(payment_request), payment_request


def send_fee_link(*, enrollment, actor=None) -> dict:
    """Email the student a pay link for their next payable installment.

    Raises `FeeLinkError` when there is nothing to send (no email, no
    schedule, everything paid, no link configured).
    """
    # Lazy: portal imports fees, so a module-level import would be circular.
    from apps.portal.fee_views import _pay_state

    student = enrollment.student
    email = (student.student_email or "").strip()
    if not email:
        raise FeeLinkError("This student has no email address on file.")

    installments, paid_map, target = _pay_state(enrollment)
    if not installments:
        raise FeeLinkError(
            "No installments are scheduled for this enrollment yet. Set up "
            "the fee plan first.",
        )
    if target is None:
        raise FeeLinkError("Every scheduled installment is already paid.")

    balance = Decimal(target.amount) - paid_map.get(target.id, Decimal("0"))
    program = enrollment.program
    institute = getattr(program, "institute", None)
    institute_key = (getattr(institute, "code", "") or "").upper()
    institute_label = getattr(institute, "name", "") or "JD"

    installment_label = (
        "Registration fee"
        if target.kind == target.Kind.REGISTRATION
        else f"Installment #{target.sequence}"
    )
    url, payment_request = _pay_url(
        target, amount=balance, institute_key=institute_key,
        label=installment_label, actor=actor,
    )

    email_log = queue_notification(
        template_key="fees.fee_link.email",
        recipient=email,
        context={
            "name": student.student_name,
            "institute": institute_label,
            "course": program.name,
            "installment": installment_label,
            "amount": _money(balance),
            "due_date": target.due_date.strftime("%d %b %Y") if target.due_date else "—",
            "url": url,
            # Drives the From domain (Diploma → jdinstitute.edu.in,
            # Degree/Bachelors → jdindia.com). See notifications.sender.
            "degree_type": program.degree_type,
        },
        related=enrollment,
    )

    sent = getattr(email_log, "status", "") == "SENT"
    return {
        "email": email,
        "email_sent": sent,
        "email_error": "" if sent else (getattr(email_log, "error", "") or ""),
        "url": url,
        "installment_id": target.id,
        "installment": installment_label,
        "amount": str(balance),
        # "manual" = our UPI/bank page; the receipt still has to be recorded.
        "gateway": payment_request.gateway if payment_request else "manual",
        "payment_request_id": getattr(payment_request, "id", None),
    }


# ---------------------------------------------------------------------
# Per-row links (student details → Fees → "Send link" on each row)
# ---------------------------------------------------------------------
#
# Unlike `send_fee_link` these are online-only: a row with no gateway
# route (JDIFT course installments and other fees — paid at the college,
# user rule 2026-11-02) is refused rather than sent as a manual page, and
# the UI hides the button for such rows (`online_payable`).

def is_online_payable(route) -> bool:
    """Whether a resolved route can take money right now."""
    from apps.payments.errors import PaymentGatewayError
    from apps.payments.services import payable_route

    try:
        payable_route(route, "")
    except PaymentGatewayError:
        return False
    return True


def _student_email(enrollment) -> str:
    email = (enrollment.student.student_email or "").strip()
    if not email:
        raise FeeLinkError("This student has no email address on file.")
    return email


def _institute_bits(enrollment) -> tuple[str, str]:
    program = enrollment.program
    institute = getattr(program, "institute", None)
    return (
        (getattr(institute, "code", "") or "").upper(),
        getattr(institute, "name", "") or "JD",
    )


def _online_request(make_request, *, what: str):
    from apps.payments.errors import PaymentGatewayError
    from apps.payments.services import NoOnlineRoute

    try:
        return make_request()
    except NoOnlineRoute as e:
        logger.info("fees: %s", e)
        raise FeeLinkError(
            f"Online payment is not available for this {what}; it is paid "
            f"at the college.",
        ) from e
    except PaymentGatewayError as e:
        logger.error("fees: %s", e)
        raise FeeLinkError(
            f"The payment gateway could not raise a link for this {what}: {e}",
        ) from e


def _email_link(*, enrollment, email, label, amount, due_date, url) -> dict:
    program = enrollment.program
    _key, institute_label = _institute_bits(enrollment)
    email_log = queue_notification(
        template_key="fees.fee_link.email",
        recipient=email,
        context={
            "name": enrollment.student.student_name,
            "institute": institute_label,
            "course": program.name,
            "installment": label,
            "amount": _money(amount),
            "due_date": due_date.strftime("%d %b %Y") if due_date else "—",
            "url": url,
            "degree_type": program.degree_type,
        },
        related=enrollment,
    )
    sent = getattr(email_log, "status", "") == "SENT"
    return {
        "email": email,
        "email_sent": sent,
        "email_error": "" if sent else (getattr(email_log, "error", "") or ""),
        "url": url,
        "installment": label,
        "amount": str(amount),
    }


def send_installment_link(*, installment, actor=None) -> dict:
    """Email the student a gateway link for ONE scheduled installment —
    any row with a balance, not only the next payable one (staff's
    call, user 2026-11-02). Raises `FeeLinkError` when nothing can go."""
    from apps.fees.services.balance import installment_balance
    from apps.payments.services import installment_request_for, pay_url_for

    enrollment = installment.enrollment
    email = _student_email(enrollment)
    balance = Decimal(installment_balance(installment)["balance"])
    if balance <= Decimal("0"):
        raise FeeLinkError("This installment is already paid.")

    label = (
        "Registration fee"
        if installment.kind == installment.Kind.REGISTRATION
        else f"Installment #{installment.sequence}"
    )
    payment_request = _online_request(
        lambda: installment_request_for(installment, amount=balance, actor=actor),
        what="installment",
    )
    out = _email_link(
        enrollment=enrollment, email=email, label=label, amount=balance,
        due_date=installment.due_date, url=pay_url_for(payment_request),
    )
    out.update({
        "installment_id": installment.id,
        "gateway": payment_request.gateway,
        "payment_request_id": payment_request.id,
    })
    return out


def send_other_fee_link(*, other_fee, actor=None) -> dict:
    """Email the student a gateway link for ONE ad-hoc "other" fee."""
    from apps.fees.models import FeeReceipt
    from apps.payments.services import other_fee_request_for, pay_url_for
    from django.db.models import Sum

    enrollment = other_fee.enrollment
    email = _student_email(enrollment)
    paid = Decimal(
        other_fee.receipts.filter(status=FeeReceipt.Status.ACTIVE)
        .aggregate(s=Sum("amount"))["s"] or 0
    )
    balance = Decimal(other_fee.amount) - paid
    if balance <= Decimal("0"):
        raise FeeLinkError("This fee is already paid.")

    payment_request = _online_request(
        lambda: other_fee_request_for(other_fee, amount=balance, actor=actor),
        what="fee",
    )
    out = _email_link(
        enrollment=enrollment, email=email, label=other_fee.name,
        amount=balance, due_date=None, url=pay_url_for(payment_request),
    )
    out.update({
        "other_fee_id": other_fee.id,
        "gateway": payment_request.gateway,
        "payment_request_id": payment_request.id,
    })
    return out
