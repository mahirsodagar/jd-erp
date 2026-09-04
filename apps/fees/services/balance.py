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


def resolve_fee_figures(enrollment) -> dict:
    """The headline fee for an enrollment, with a fallback.

    Preferred source is the active FeeTemplate for (academic_year,
    campus, program). That lookup can legitimately come up empty — the
    template was deactivated, the fee was revised into a new row, or the
    enrollment was moved to a campus/program the template doesn't cover.

    When it does, a zero total made `payable` zero too, so `balance`
    (payable − paid) went NEGATIVE the moment any money was received, and
    the fee report showed a 0 total against a minus due. So fall back to
    the schedule the enrollment actually carries: Σ installments +
    Σ approved concessions, which is the same identity the fee
    undertaking PDF prints (installments + concession = total fee), with
    the REGISTRATION row standing in for the template's registration_fee.

    Returns total_fee, registration_fee, the concession total that went
    into the fallback, and `source` — "template" or "schedule" — so
    callers can tell a real zero from an unresolved one.
    """
    tmpl = active_fee_template(enrollment)
    total_fee = _decimal(getattr(tmpl, "total_fee", None))
    registration_fee = _decimal(getattr(tmpl, "registration_fee", None))

    concession_total = _decimal(
        Concession.objects.filter(
            enrollment=enrollment, status=Concession.Status.APPROVED,
        ).aggregate(s=Sum("amount"))["s"]
    )
    reg_rows = Installment.objects.filter(
        enrollment=enrollment, kind=Installment.Kind.REGISTRATION,
    )
    registration_due = _decimal(reg_rows.aggregate(s=Sum("amount"))["s"])

    source = "template"
    if total_fee <= _zero():
        scheduled = _decimal(
            Installment.objects.filter(enrollment=enrollment)
            .aggregate(s=Sum("amount"))["s"]
        )
        if scheduled > _zero():
            source = "schedule"
            total_fee = scheduled + concession_total
            # The template is what normally carries registration_fee; with
            # no template, the row on the schedule is the only record of it.
            if registration_fee <= _zero():
                registration_fee = registration_due

    return {
        "template": tmpl,
        "total_fee": total_fee,
        "registration_fee": registration_fee,
        "concession_total": concession_total,
        "registration_due": registration_due,
        "reg_rows": reg_rows,
        "source": source,
    }


def enrollment_balance(enrollment) -> dict:
    """Headline numbers for an enrollment:

      total_fee            — from the active FeeTemplate matching
                              (academic_year, campus, program), falling
                              back to the enrollment's own schedule when
                              no template resolves. See
                              resolve_fee_figures().
      total_fee_source     — "template" or "schedule": which of the two
                              the total came from.
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
    figures = resolve_fee_figures(enrollment)
    tmpl = figures["template"]
    total_fee = figures["total_fee"]
    registration_fee = figures["registration_fee"]
    concession_total = figures["concession_total"]

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

    reg_rows = figures["reg_rows"]
    registration_due = figures["registration_due"]
    registration_paid = _decimal(
        FeeReceipt.objects.filter(
            installment__in=reg_rows, status=FeeReceipt.Status.ACTIVE,
        ).aggregate(s=Sum("amount"))["s"]
    )

    return {
        "fee_template_id": getattr(tmpl, "id", None),
        "fee_template_name": getattr(tmpl, "name", None),
        "total_fee": str(total_fee),
        "total_fee_source": figures["source"],
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
