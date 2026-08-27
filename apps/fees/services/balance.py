"""Fee balance computations. Returned as plain dicts for serializers
and reports."""

from decimal import Decimal

from django.db.models import Sum

from apps.fees.models import Concession, FeeReceipt, Installment


def _zero() -> Decimal:
    return Decimal("0.00")


def _decimal(v) -> Decimal:
    return Decimal(v) if v is not None else _zero()


def active_fee_template(enrollment):
    """The active FeeTemplate for (academic_year, campus, program), or
    None. Resolved at read time — see docs/technical/06-fees.md §6.3 for
    why editing a live template shifts history."""
    from apps.master.models import FeeTemplate

    return FeeTemplate.objects.filter(
        academic_year=enrollment.academic_year,
        campus=enrollment.campus,
        program=enrollment.program,
        is_active=True,
    ).first()


def concession_ceiling(total_fee: Decimal, registration_fee: Decimal) -> Decimal:
    """The most a concession may reduce. The registration fee is
    mandatory and payable in full, so it is fenced off from discounts."""
    return max(_zero(), total_fee - registration_fee)


def enrollment_balance(enrollment) -> dict:
    """Headline numbers for an enrollment:

      total_fee            — from the active FeeTemplate matching
                              (academic_year, campus, program).
      registration_fee     — the template's mandatory yearly charge. It is
                              carved OUT of total_fee, never added to it.
      concession_total     — sum of approved concessions (raw).
      concession_applied   — concession_total capped so it can never eat
                              into the registration fee. `payable` uses
                              this one; approval-time validation should
                              normally keep the two equal.
      paid_total           — sum of active receipts.
      payable              — total_fee − concession_applied.
      balance              — payable − paid_total.
      registration_due/paid/balance — the REGISTRATION installment rows
                              actually laid down on this enrollment and
                              what has been received against them. A
                              non-zero registration_fee with a zero
                              registration_due means the schedule has not
                              been built yet.
    """
    tmpl = active_fee_template(enrollment)
    total_fee = _decimal(getattr(tmpl, "total_fee", None))
    registration_fee = _decimal(getattr(tmpl, "registration_fee", None))

    concession_total = _decimal(
        Concession.objects.filter(
            enrollment=enrollment, status=Concession.Status.APPROVED,
        ).aggregate(s=Sum("amount"))["s"]
    )
    concession_applied = min(
        concession_total, concession_ceiling(total_fee, registration_fee),
    )
    paid_total = _decimal(
        FeeReceipt.objects.filter(
            enrollment=enrollment, status=FeeReceipt.Status.ACTIVE,
            other_fee__isnull=True,   # Other-fee payments are tracked separately.
        ).aggregate(s=Sum("amount"))["s"]
    )
    payable = total_fee - concession_applied

    reg_rows = Installment.objects.filter(
        enrollment=enrollment, kind=Installment.Kind.REGISTRATION,
    )
    registration_due = _decimal(reg_rows.aggregate(s=Sum("amount"))["s"])
    registration_paid = _decimal(
        FeeReceipt.objects.filter(
            installment__in=reg_rows, status=FeeReceipt.Status.ACTIVE,
        ).aggregate(s=Sum("amount"))["s"]
    )

    return {
        "fee_template_id": getattr(tmpl, "id", None),
        "fee_template_name": getattr(tmpl, "name", None),
        "total_fee": str(total_fee),
        "registration_fee": str(registration_fee),
        "concession_total": str(concession_total),
        "concession_applied": str(concession_applied),
        "concession_capped": concession_applied < concession_total,
        "paid_total": str(paid_total),
        "payable": str(payable),
        "balance": str(payable - paid_total),
        "registration_due": str(registration_due),
        "registration_paid": str(registration_paid),
        "registration_balance": str(registration_due - registration_paid),
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
