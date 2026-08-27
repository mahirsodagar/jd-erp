"""The mandatory yearly registration fee.

The charge lives on `master.FeeTemplate.registration_fee` and is **carved
out of** that template's `total_fee` — it is a labelled, separately
scheduled slice of the course fee, not an extra on top. A student pays it
once per academic year for as long as the course runs, so a three-year
program collects it three times (once against each year's template).

It is modelled as an `Installment` of `kind=REGISTRATION` rather than an
`OtherFee` on purpose: only installments carry a due date, link to
receipts, and feed the due-date reminders and collection reports.

**Keyed on (student, academic year), not on enrollment.** `promote_batch()`
is used both for year-to-year promotion and for sem 1 → sem 2 *within the
same academic year*; keying on the enrollment would charge a mid-year
promotion twice.
"""

from datetime import date
from decimal import Decimal

from django.db.models import Max

from apps.fees.models import Installment
from apps.fees.services.balance import active_fee_template

#: Description written on the auto-created row. The undertaking PDF and
#: the enrolment form both key off `kind`, not this text — it is for
#: humans reading the schedule.
REGISTRATION_DESCRIPTION = "Registration fee"


def _zero() -> Decimal:
    return Decimal("0.00")


def registration_fee_for(enrollment) -> Decimal:
    """The mandatory amount for this enrollment's year/campus/program,
    or 0 when no active template matches or the template opts out."""
    tmpl = active_fee_template(enrollment)
    return Decimal(getattr(tmpl, "registration_fee", None) or 0)


def registration_installment_for_year(student_id, academic_year_id):
    """The existing REGISTRATION row for this student in this academic
    year, across *any* of their enrollments — or None."""
    return (
        Installment.objects
        .filter(
            kind=Installment.Kind.REGISTRATION,
            enrollment__student_id=student_id,
            enrollment__academic_year_id=academic_year_id,
        )
        .select_related("enrollment")
        .first()
    )


def default_due_date(enrollment) -> date:
    """Due at the start of the session it belongs to, falling back to the
    enrolment date and then to today."""
    start = getattr(enrollment.academic_year, "start_date", None)
    return start or enrollment.entry_date or date.today()


def _next_sequence(enrollment) -> int:
    current = (
        Installment.objects
        .filter(enrollment=enrollment)
        .aggregate(m=Max("sequence"))["m"]
    )
    return (current or 0) + 1


def ensure_registration_installment(enrollment, *, due_date=None, actor=None):
    """Lay down this year's registration installment if it is missing.

    Idempotent per (student, academic year) — returns the existing row
    when one is already present, and None when the template charges
    nothing (or no template matches), so callers can treat it as a
    best-effort seed.
    """
    existing = registration_installment_for_year(
        enrollment.student_id, enrollment.academic_year_id,
    )
    if existing is not None:
        return existing

    amount = registration_fee_for(enrollment)
    if amount <= _zero():
        return None

    return Installment.objects.create(
        enrollment=enrollment,
        kind=Installment.Kind.REGISTRATION,
        sequence=_next_sequence(enrollment),
        due_date=due_date or default_due_date(enrollment),
        amount=amount,
        description=REGISTRATION_DESCRIPTION,
        created_by=actor,
    )
