"""Leave day count — legacy JD_ERP model (``gettotalleave()``).

Legacy counts plain **calendar days**, inclusive of both endpoints, with no
weekend or holiday netting. A single-day request is a half day (0.5) for the
half / permission sessions and a full day (1.0) otherwise.
"""

from datetime import date
from decimal import Decimal

from apps.leaves.models import LeaveType


def count_days(*, employee, leave_type: LeaveType, from_date: date,
               to_date: date, from_session: int) -> Decimal:
    if from_date == to_date:
        # 1 = half (AM), 3/4 = permission slots → half day; 2 = full day.
        if from_session in (1, 3, 4):
            return Decimal("0.5")
        return Decimal("1.0")

    # Multi-day: inclusive calendar-day span.
    return Decimal((to_date - from_date).days + 1)
