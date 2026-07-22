"""Per-employee leave balance computation — legacy JD_ERP model.

Balances are a straight lifetime ``granted − availed`` per leave type
(mirroring ``leave_balances.php``): granted comes from every allocation in
``emp_leave_master``, availed from approved applications. Comp-off is a
derived pool (earned via comp-off requests, spent via COMP_OFF leaves).

The Apply dashboard uses a different, legacy-specific model for Casual
Leave: a fixed 12-per-year monthly accrual (``cl_dashboard``).
"""

from datetime import date as _date
from decimal import Decimal

from django.db.models import Sum

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)


COMP_OFF_CODE = "COMP_OFF"
CASUAL_CODE = "CASUAL"

# Fixed leave-year window (legacy leave_apply.php dashboard).
LEAVE_YEAR_START = _date(2025, 6, 1)
LEAVE_YEAR_END = _date(2026, 5, 31)
CL_PER_YEAR = Decimal("12")


def _zero() -> Decimal:
    return Decimal("0.0")


def compute_balance(employee, leave_type: LeaveType, on_date=None) -> dict:
    """Return a balance row for one leave type.

    - COMP_OFF: ``{earned, used, balance}`` — lifetime derived pool.
    - other LEAVE types: ``{granted, pending, availed, balance}`` where
      ``granted`` is the sum of all allocations and ``availed`` the sum of
      approved applications (legacy ``leave_balances.php``).
    - ON_DUTY types: unlimited — nulls, returned only for parity.

    ``on_date`` is accepted for signature compatibility but ignored: legacy
    balances are lifetime, not window-scoped.
    """

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
                status=LeaveApplication.Status.APPROVED,
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

    granted = (
        LeaveAllocation.objects
        .filter(employee=employee, leave_type=leave_type)
        .aggregate(s=Sum("count"))["s"] or _zero()
    )
    apps_qs = LeaveApplication.objects.filter(employee=employee, leave_type=leave_type)
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
        "balance": granted - availed,
    }


def all_balances(employee, on_date=None) -> list[dict]:
    return [
        compute_balance(employee, lt, on_date)
        for lt in LeaveType.objects.filter(is_active=True).order_by("name")
    ]


def cl_dashboard(employee) -> dict:
    """Legacy leave_apply.php dashboard counters over the fixed leave-year.

    CL Balance follows the 1-CL-per-month accrual: ``12 − (# distinct
    months in which a Casual Leave was approved)``.
    """
    approved = LeaveApplication.objects.filter(
        employee=employee,
        status=LeaveApplication.Status.APPROVED,
        from_date__gte=LEAVE_YEAR_START,
        from_date__lte=LEAVE_YEAR_END,
    )

    total_leaves = (
        approved.filter(leave_type__category=LeaveType.Category.LEAVE)
        .aggregate(s=Sum("count"))["s"] or _zero()
    )
    total_cl = (
        approved.filter(leave_type__code=CASUAL_CODE)
        .aggregate(s=Sum("count"))["s"] or _zero()
    )
    total_compoff = (
        approved.filter(leave_type__code=COMP_OFF_CODE)
        .aggregate(s=Sum("count"))["s"] or _zero()
    )

    cl_months = {
        d.month
        for d in approved.filter(leave_type__code=CASUAL_CODE)
        .values_list("from_date", flat=True)
    }
    cl_balance = CL_PER_YEAR - Decimal(len(cl_months))

    return {
        "leave_year_start": str(LEAVE_YEAR_START),
        "leave_year_end": str(LEAVE_YEAR_END),
        "total_leaves_taken": total_leaves,
        "total_cl_taken": total_cl,
        "total_compoff_taken": total_compoff,
        "cl_balance": cl_balance,
    }
