"""Fees-related SMS dispatch (payment confirmation + installment-due reminders).

All sends go through `apps.notifications.services.queue_notification` so
they get a dispatch log row + provider routing via MSG91. Best-effort by
design — a failed SMS never blocks the receipt/installment operation.
"""

from __future__ import annotations

import logging
from datetime import date as _Date
from decimal import Decimal
from typing import Iterable

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.notifications.services import queue_notification

from .models import FeeReceipt, Installment

logger = logging.getLogger(__name__)


_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 11 → '11th', 12 → '12th', ..."""
    if 10 <= (n % 100) <= 20:
        return f"{n}th"
    return f"{n}{_ORDINAL_SUFFIX.get(n % 10, 'th')}"


def _money(amount: Decimal | float | int) -> str:
    """Render an amount without trailing zeros — '5000' not '5000.00'."""
    if amount is None:
        return ""
    d = Decimal(amount).quantize(Decimal("1.00"))
    return f"{d:.0f}" if d == d.to_integral_value() else f"{d:.2f}"


def _parent_phone(student) -> str:
    return (
        (getattr(student, "father_mobile", "") or "").strip()
        or (getattr(student, "mother_mobile", "") or "").strip()
    )


def _fire_sms(
    *, template_key: str, recipient: str, context: dict, related,
) -> None:
    """Tiny wrapper — logs failures, never raises."""
    if not recipient:
        return
    try:
        queue_notification(
            template_key=template_key,
            recipient=recipient,
            context=context,
            related=related,
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception("Fees SMS dispatch failed: %s → %s", template_key, recipient)


# ---------------------------------------------------------------------
# Payment confirmation — on receipt create
# ---------------------------------------------------------------------

def _fire_payment_confirmation(receipt: FeeReceipt) -> None:
    """Fire 2 SMS (student + parent) confirming a fresh receipt."""
    if receipt.status != FeeReceipt.Status.ACTIVE:
        return  # Cancelled receipts don't notify.

    enrollment = receipt.enrollment
    student = getattr(enrollment, "student", None)
    if student is None:
        return

    installment_ord = (
        _ordinal(receipt.installment.sequence)
        if receipt.installment_id else ""
    )
    course_name = getattr(getattr(enrollment, "program", None), "name", "") or ""
    registration_no = getattr(student, "registration_number", "") or ""
    amount = _money(receipt.amount)

    # Student leg
    _fire_sms(
        template_key="fees.installment_paid_student.sms",
        recipient=(student.student_mobile or "").strip(),
        context={
            "name": student.student_name,
            "registration_no": registration_no,
            "amount": amount,
            "installment": installment_ord,
        },
        related=receipt,
    )

    # Parent leg
    _fire_sms(
        template_key="fees.installment_paid_parent.sms",
        recipient=_parent_phone(student),
        context={
            "amount": amount,
            "installment": installment_ord,
            "ward_name": student.student_name,
            "registration_no": registration_no,
            "course": course_name,
        },
        related=receipt,
    )


@receiver(post_save, sender=FeeReceipt)
def _on_fee_receipt_saved(sender, instance: FeeReceipt, created, **kwargs):
    """Only fire on fresh ACTIVE receipts. Cancellation flips status
    in-place (status=CANCELLED) without triggering a "created" save, so
    the guard above + the created-check together cover both cases."""
    if not created:
        return
    _fire_payment_confirmation(instance)


# ---------------------------------------------------------------------
# Installment due reminders — fired by management command
# ---------------------------------------------------------------------

def fire_installment_due_reminder(installment: Installment) -> None:
    """Send "fees due" SMS to student + parent for one installment.

    Called by the `notify_installments_due` management command, which
    selects installments whose `due_date` falls inside a configurable
    window (e.g. 7 days, 3 days, 1 day ahead).
    """
    enrollment = installment.enrollment
    student = getattr(enrollment, "student", None)
    if student is None:
        return

    installment_ord = _ordinal(installment.sequence)
    course_name = getattr(getattr(enrollment, "program", None), "name", "") or ""
    registration_no = getattr(student, "registration_number", "") or ""
    amount = _money(installment.amount)
    due = installment.due_date.strftime("%d-%m-%Y") if installment.due_date else ""

    # Student leg
    _fire_sms(
        template_key="fees.installment_due_student.sms",
        recipient=(student.student_mobile or "").strip(),
        context={
            "name": student.student_name,
            "registration_no": registration_no,
            "installment": installment_ord,
            "amount": amount,
            "course": course_name,
            "due_date": due,
        },
        related=installment,
    )

    # Parent leg
    _fire_sms(
        template_key="fees.installment_due_parent.sms",
        recipient=_parent_phone(student),
        context={
            "installment": installment_ord,
            "amount": amount,
            "ward_name": student.student_name,
            "registration_no": registration_no,
            "course": course_name,
            "due_date": due,
        },
        related=installment,
    )


# ---------------------------------------------------------------------
# Bulk reminder — fired by management command
# ---------------------------------------------------------------------

def fire_bulk_fee_reminder(students: Iterable) -> dict:
    """Fire the static bulk-reminder SMS to every passed student +
    their parent. Returns counts of attempts.

    The DLT body has zero variables, so no context required — we just
    use student.student_mobile and parent's mobile as recipients."""
    fired = parents = skipped = 0
    for student in students:
        s_mobile = (getattr(student, "student_mobile", "") or "").strip()
        p_mobile = _parent_phone(student)
        if s_mobile:
            _fire_sms(
                template_key="fees.bulk_reminder.sms",
                recipient=s_mobile,
                context={},
                related=student,
            )
            fired += 1
        else:
            skipped += 1
        if p_mobile:
            _fire_sms(
                template_key="fees.bulk_reminder.sms",
                recipient=p_mobile,
                context={},
                related=student,
            )
            parents += 1
    return {"students_fired": fired, "parents_fired": parents, "skipped": skipped}
