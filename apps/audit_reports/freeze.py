"""Month-wise freeze of the faculty and admin daily reports.

A calendar month's daily reports lock once the month is over (plus an
optional grace of `DAILY_REPORT_FREEZE_GRACE_DAYS` days into the next
month, default 0). A frozen month can only be edited through a
`DailyReportAccess` request:

    employee requests  →  reporting manager approves  →  admin grants
    (PENDING)             (MANAGER_APPROVED)              (GRANTED, until a date)

Nobody edits a frozen month without a GRANTED, unexpired access row —
except holders of the audit `*_any` keys, who are correcting someone
else's report as auditors and are not the ones being frozen.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from .models import DailyReportAccess
from .permissions import has_perm

REPORT_FACULTY = DailyReportAccess.ReportType.FACULTY
REPORT_ADMIN = DailyReportAccess.ReportType.ADMIN

# Keys that bypass the freeze entirely (auditors correcting others).
_BYPASS_KEYS = {
    REPORT_FACULTY: ("audit.faculty_daily.edit_any",
                     "audit.faculty_daily.delete_any"),
    REPORT_ADMIN: ("audit.admin_daily.edit_any",
                   "audit.admin_daily.delete_any"),
}


def today() -> date:
    return timezone.localdate()


def grace_days() -> int:
    return int(getattr(settings, "DAILY_REPORT_FREEZE_GRACE_DAYS", 0) or 0)


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def next_month_start(year: int, month: int) -> date:
    return date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)


def freeze_date(year: int, month: int) -> date:
    """The first day on which (year, month) counts as frozen."""
    return next_month_start(year, month) + timedelta(days=grace_days())


def month_is_frozen(year: int, month: int, *, on: date | None = None) -> bool:
    return (on or today()) >= freeze_date(year, month)


def date_is_frozen(d: date, *, on: date | None = None) -> bool:
    return month_is_frozen(d.year, d.month, on=on)


def open_access(user, report_type: str, year: int, month: int,
                *, on: date | None = None):
    """The GRANTED, unexpired access row for this user/month, or None."""
    on = on or today()
    return (DailyReportAccess.objects
            .filter(user=user, report_type=report_type, year=year,
                    month=month, status=DailyReportAccess.Status.GRANTED,
                    access_until__gte=on)
            .order_by("-access_until").first())


def bypasses_freeze(user, report_type: str) -> bool:
    return user.is_superuser or any(
        has_perm(user, k) for k in _BYPASS_KEYS[report_type])


def write_blocked_reason(user, report_type: str, d: date) -> str | None:
    """None when `user` may write their own report for `d`; otherwise the
    message to show. Auditors with `*_any` keys are never blocked."""
    if not date_is_frozen(d):
        return None
    if bypasses_freeze(user, report_type):
        return None
    if open_access(user, report_type, d.year, d.month) is not None:
        return None
    return (f"{d.strftime('%B %Y')} is frozen. Request access for that "
            f"month; your reporting manager must approve it and an admin "
            f"must then grant it before you can edit.")


def status_for(user, report_type: str, year: int, month: int) -> dict:
    """What the My Daily Report page needs to decide editable vs locked."""
    frozen = month_is_frozen(year, month)
    access = open_access(user, report_type, year, month) if frozen else None
    latest = (DailyReportAccess.objects
              .filter(user=user, report_type=report_type, year=year, month=month)
              .order_by("-created_at").first())
    return {
        "report_type": report_type,
        "year": year, "month": month,
        "frozen": frozen,
        "freezes_on": freeze_date(year, month).isoformat(),
        "grace_days": grace_days(),
        "can_edit": (not frozen) or access is not None
                    or bypasses_freeze(user, report_type),
        "access": access,     # serialised by the view
        "latest_request": latest,
    }
