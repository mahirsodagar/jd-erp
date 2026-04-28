"""Working-day count for a leave application.

Default behaviour skips Sundays + holidays (per scope §5.2). Set
LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS=False in settings/env to fall back
to PHP-style "calendar days" counting.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings

from apps.leaves.models import Holiday, LeaveType


def _holiday_dates(employee, start: date, end: date) -> set[date]:
    qs = Holiday.objects.filter(
        date__range=(start, end),
        is_optional=False,
    ).filter(
        # Holidays are either institute-wide (campus null) or campus-scoped.
        # Use Q for the OR.
    )
    from django.db.models import Q
    qs = qs.filter(Q(campus__isnull=True) | Q(campus_id=employee.campus_id))
    return set(qs.values_list("date", flat=True))


def count_days(*, employee, leave_type: LeaveType, from_date: date,
               to_date: date, from_session: int) -> Decimal:
    if from_date == to_date:
        if from_session in (1, 3, 4):
            return Decimal("0.5")
        if from_session == 2:
            return Decimal("1.0")
        # Defensive: unexpected session for a single-day request.
        return Decimal("1.0")

    exclude = getattr(settings, "LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS", True)
    holidays = _holiday_dates(employee, from_date, to_date) if exclude else set()

    n = 0
    cur = from_date
    while cur <= to_date:
        skip = False
        if exclude:
            # Sunday only — Saturday is a normal working day for many JD campuses.
            if cur.weekday() == 6:
                skip = True
            elif cur in holidays:
                skip = True
        if not skip:
            n += 1
        cur += timedelta(days=1)
    return Decimal(n)
