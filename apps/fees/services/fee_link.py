"""Staff-triggered "Send fee link" for an enrolled student.

The student is emailed a link for the *next payable installment* — the
same earliest-row-with-a-balance the portal lets them pay, so the link
and the portal can never disagree about what is due.

The link is a tokenised pay URL (`PaymentRequest`) whenever the fee has
an online route, which makes the payment self-reconciling: the gateway
confirms the charge and the receipt is written automatically. When it
has none (e.g. JDIFT course installments — see `apps.payments.routing`)
the static per-institute link from `settings.FEE_LINK_URLS` goes out
instead, and accounts records the receipt by hand as before.

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


def _static_url(institute_key: str) -> str:
    url = (getattr(settings, "FEE_LINK_URLS", {}) or {}).get(institute_key)
    if not url:
        raise FeeLinkError(
            f"Online payment is not available for this fee and no manual "
            f"fee link is configured for institute '{institute_key or '—'}'. "
            f"Set FEE_LINK_URLS[{institute_key!r}].",
        )
    return url


def _pay_url(installment, *, amount: Decimal, institute_key: str, actor):
    """`(url, payment_request_or_None)` — gateway link, else static link."""
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
        return _static_url(institute_key), None
    except PaymentGatewayError as e:
        logger.error("fees: %s Sending the manual fee link instead.", e)
        return _static_url(institute_key), None

    try:
        payment_request = installment_request_for(
            installment, amount=amount, actor=actor,
        )
    except PaymentGatewayError as e:
        logger.warning(
            "fees: pay request failed for installment %s (%s) — "
            "falling back to the static fee link.", installment.pk, e,
        )
        return _static_url(institute_key), None

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

    url, payment_request = _pay_url(
        target, amount=balance, institute_key=institute_key, actor=actor,
    )

    installment_label = (
        "Registration fee"
        if target.kind == target.Kind.REGISTRATION
        else f"Installment #{target.sequence}"
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
        # "manual" = static link; the receipt still has to be recorded.
        "gateway": payment_request.gateway if payment_request else "manual",
        "payment_request_id": getattr(payment_request, "id", None),
    }
