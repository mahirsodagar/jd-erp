"""Fee balance computations. Returned as plain dicts for serializers
and reports."""

from decimal import Decimal

from django.db.models import Sum

from apps.fees.models import Concession, FeeReceipt, Installment


def _zero() -> Decimal:
    return Decimal("0.00")


def _decimal(v) -> Decimal:
    return Decimal(v) if v is not None else _zero()


def enrollment_balance(enrollment) -> dict:
    """Headline numbers for an enrollment:

      total_fee        — from the linked FeeTemplate (current rule:
                          look up the active template by
                          (academic_year, campus, program, course)).
      concession_total — sum of approved concessions.
      paid_total       — sum of active receipts.
      payable          — total_fee − concession_total.
      balance          — payable − paid_total.
    """
    from apps.master.models import FeeTemplate

    tmpl = FeeTemplate.objects.filter(
        academic_year=enrollment.academic_year,
        campus=enrollment.campus,
        program=enrollment.program,
        course=enrollment.course,
        is_active=True,
    ).first()
    if tmpl is None:
        # Fall back: same context but course=None.
        tmpl = FeeTemplate.objects.filter(
            academic_year=enrollment.academic_year,
            campus=enrollment.campus,
            program=enrollment.program,
            course__isnull=True,
            is_active=True,
        ).first()
    total_fee = _decimal(getattr(tmpl, "total_fee", None))

    concession_total = _decimal(
        Concession.objects.filter(
            enrollment=enrollment, status=Concession.Status.APPROVED,
        ).aggregate(s=Sum("amount"))["s"]
    )
    paid_total = _decimal(
        FeeReceipt.objects.filter(
            enrollment=enrollment, status=FeeReceipt.Status.ACTIVE,
        ).aggregate(s=Sum("amount"))["s"]
    )
    payable = total_fee - concession_total

    return {
        "fee_template_id": getattr(tmpl, "id", None),
        "fee_template_name": getattr(tmpl, "name", None),
        "total_fee": str(total_fee),
        "concession_total": str(concession_total),
        "paid_total": str(paid_total),
        "payable": str(payable),
        "balance": str(payable - paid_total),
    }


def installment_balance(installment: Installment) -> dict:
    paid = _decimal(
        FeeReceipt.objects.filter(
            installment=installment, status=FeeReceipt.Status.ACTIVE,
        ).aggregate(s=Sum("amount"))["s"]
    )
    return {
        "installment_id": installment.id,
        "amount_due": str(installment.amount),
        "paid": str(paid),
        "balance": str(_decimal(installment.amount) - paid),
    }
