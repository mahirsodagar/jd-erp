"""Per-employee leave balance computation. Returns plain dicts so the
caller (serializers, reports) can shape them as needed."""

from datetime import date as _date
from decimal import Decimal

from django.db.models import Max, Min, Sum
from django.utils import timezone

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)


COMP_OFF_CODE = "COMP_OFF"


def _zero() -> Decimal:
    return Decimal("0.0")


def compute_balance(
    employee, leave_type: LeaveType, on_date: _date | None = None,
) -> dict:
    """Return {granted, pending, availed, balance} for a regular LEAVE type,
    or {earned, used, balance} for COMP_OFF.

    A LEAVE balance is scoped to the allocation window(s) open on `on_date`
    (defaults to today): granted comes from the open allocation(s), and
    used/pending count only the applications whose from_date falls inside
    that window. COMP_OFF is lifetime; ON_DUTY is unlimited."""

    if on_date is None:
        on_date = timezone.localdate()

    if leave_type.code == COMP_OFF_CODE:
        earned = (
            CompOffApplication.objects
            .filter(employee=employee, status=CompOffApplication.Status.APPROVED)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        used = (
            LeaveApplication.objects
            .filter(
                employee=employee,
                leave_type__code=COMP_OFF_CODE,
                status__in=[
                    LeaveApplication.Status.PENDING,
                    LeaveApplication.Status.APPROVED,
                ],
            )
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        return {
            "leave_type_id": leave_type.id,
            "leave_type_code": leave_type.code,
            "leave_type_name": leave_type.name,
            "earned": earned,
            "used": used,
            "balance": earned - used,
        }

    if leave_type.category != LeaveType.Category.LEAVE:
        # ON_DUTY types are unlimited; we still return a row for parity.
        return {
            "leave_type_id": leave_type.id,
            "leave_type_code": leave_type.code,
            "leave_type_name": leave_type.name,
            "category": leave_type.category,
            "granted": None,
            "pending": None,
            "availed": None,
            "balance": None,
        }

    pending = _zero()
    availed = _zero()

    # Allocation windows open on the reference date.
    active = LeaveAllocation.objects.filter(
        employee=employee, leave_type=leave_type,
        start_date__lte=on_date, end_date__gte=on_date,
    )
    granted = active.aggregate(s=Sum("count"))["s"] or _zero()

    # Scope applications to the bounding window of the open allocation(s).
    bounds = active.aggregate(lo=Min("start_date"), hi=Max("end_date"))
    win_start, win_end = bounds["lo"], bounds["hi"]
    if win_start and win_end:
        apps_qs = LeaveApplication.objects.filter(
            employee=employee, leave_type=leave_type,
            from_date__gte=win_start, from_date__lte=win_end,
        )
        pending = (
            apps_qs.filter(status=LeaveApplication.Status.PENDING)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        availed = (
            apps_qs.filter(status=LeaveApplication.Status.APPROVED)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )

    return {
        "leave_type_id": leave_type.id,
        "leave_type_code": leave_type.code,
        "leave_type_name": leave_type.name,
        "granted": granted,
        "pending": pending,
        "availed": availed,
        "balance": granted - pending - availed,
    }


def all_balances(employee, on_date: _date | None = None) -> list[dict]:
    return [
        compute_balance(employee, lt, on_date)
        for lt in LeaveType.objects.filter(is_active=True).order_by("name")
    ]
