"""Per-employee leave balance computation.

Balances are scoped to the allocation window that covers a reference date
(default: today). ``granted`` is the sum of every allocation whose
[start_date, end_date] contains that date; ``availed`` / ``pending`` are
the approved / pending applications whose ``from_date`` falls inside the
union of those windows. Days granted for an earlier window therefore do
not carry forward once HR opens the next one.

``balance`` is what the employee can still spend: granted − availed −
pending. The Apply guards, the Balances page and the Apply dashboard all
read this same number.

Comp-off is a derived lifetime pool (earned via approved comp-off
requests, spent via approved COMP_OFF leaves); it has no allocation and,
since 2026-11-27, is informational only — applying comp-off is unlimited
like ON_DUTY (see ``guards.available_balance``).
"""

from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Min, Sum
from django.utils import timezone

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)


# Canonical codes (what ``seed_leave_types`` creates). Matching is done
# through ``LeaveType.is_casual`` / ``is_comp_off`` which also accept the
# name, because production's HR-created catalogue uses numeric codes.
COMP_OFF_CODE = "COMP_OFF"
CASUAL_CODE = "CASUAL"


def _types_where(pred) -> list[LeaveType]:
    """Leave types satisfying ``pred``, canonical code first, then by id
    so ``[0]`` is a stable "the" type."""
    hits = [lt for lt in LeaveType.objects.order_by("id") if pred(lt)]
    hits.sort(key=lambda lt: (not lt.is_active, lt.code.upper() not in (CASUAL_CODE, COMP_OFF_CODE), lt.id))
    return hits


def casual_types() -> list[LeaveType]:
    return _types_where(lambda lt: lt.is_casual)


def comp_off_types() -> list[LeaveType]:
    return _types_where(lambda lt: lt.is_comp_off)


def casual_type() -> LeaveType | None:
    hits = casual_types()
    return hits[0] if hits else None


def comp_off_type() -> LeaveType | None:
    hits = comp_off_types()
    return hits[0] if hits else None

# The leave year runs 1 June – 31 May. Legacy leave_apply.php hard-coded
# one such window ('2025-06-01'..'2026-05-31') and needed a yearly edit;
# here it is derived from the date so it rolls over on its own.
LEAVE_YEAR_START_MONTH = 6


def leave_year(on_date=None) -> tuple[_date, _date]:
    """The (1 Jun, 31 May) leave-year window containing ``on_date``
    (default: today)."""
    on_date = on_date or timezone.localdate()
    start_year = (
        on_date.year if on_date.month >= LEAVE_YEAR_START_MONTH
        else on_date.year - 1
    )
    start = _date(start_year, LEAVE_YEAR_START_MONTH, 1)
    end = _date(start_year + 1, LEAVE_YEAR_START_MONTH, 1) - timedelta(days=1)
    return start, end


def _zero() -> Decimal:
    return Decimal("0.0")


def allocation_window(employee, leave_type: LeaveType, on_date=None):
    """``(start, end, granted)`` for the allocations of ``leave_type``
    covering ``on_date`` (default today), or ``None`` when no allocation
    covers that date. Overlapping allocations are merged into one window
    spanning the earliest start and latest end."""
    on_date = on_date or timezone.localdate()
    agg = (
        LeaveAllocation.objects
        .filter(employee=employee, leave_type=leave_type,
                start_date__lte=on_date, end_date__gte=on_date)
        .aggregate(start=Min("start_date"), end=Max("end_date"), granted=Sum("count"))
    )
    if agg["start"] is None:
        return None
    return agg["start"], agg["end"], agg["granted"] or _zero()


def compute_balance(employee, leave_type: LeaveType, on_date=None) -> dict:
    """Return a balance row for one leave type.

    - COMP_OFF: ``{earned, used, pending, balance}`` — lifetime derived pool.
    - other LEAVE types: ``{granted, pending, availed, balance,
      window_start, window_end}`` scoped to the allocation window that
      covers ``on_date`` (see ``allocation_window``). With no covering
      allocation every figure is 0 and the window is null.
    - ON_DUTY types: unlimited — nulls, returned only for parity.

    ``balance`` = granted − availed − pending in every case.
    """

    base = {
        "leave_type_id": leave_type.id,
        "leave_type_code": leave_type.code,
        "leave_type_name": leave_type.name,
        # Lets the Balances page pick the comp-off card layout without
        # depending on the literal code.
        "is_comp_off": leave_type.is_comp_off,
    }

    if leave_type.is_comp_off:
        earned = (
            CompOffApplication.objects
            .filter(employee=employee, status=CompOffApplication.Status.APPROVED)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        spend = LeaveApplication.objects.filter(
            employee=employee,
            leave_type_id__in=[lt.id for lt in comp_off_types()],
        )
        used = (
            spend.filter(status=LeaveApplication.Status.APPROVED)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        pending = (
            spend.filter(status=LeaveApplication.Status.PENDING)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )
        return {
            **base,
            "earned": earned,
            "used": used,
            "pending": pending,
            "balance": earned - used - pending,
        }

    if leave_type.category != LeaveType.Category.LEAVE:
        return {
            **base,
            "category": leave_type.category,
            "granted": None,
            "pending": None,
            "availed": None,
            "balance": None,
        }

    window = allocation_window(employee, leave_type, on_date)
    if window is None:
        return {
            **base,
            "granted": _zero(),
            "pending": _zero(),
            "availed": _zero(),
            "balance": _zero(),
            "window_start": None,
            "window_end": None,
        }
    w_start, w_end, granted = window
    apps_qs = LeaveApplication.objects.filter(
        employee=employee, leave_type=leave_type,
        from_date__gte=w_start, from_date__lte=w_end,
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
        **base,
        "granted": granted,
        "pending": pending,
        "availed": availed,
        "balance": granted - availed - pending,
        "window_start": str(w_start),
        "window_end": str(w_end),
    }


def all_balances(employee, on_date=None) -> list[dict]:
    return [
        compute_balance(employee, lt, on_date)
        for lt in LeaveType.objects.filter(is_active=True).order_by("name")
    ]


def cl_dashboard(employee, on_date=None) -> dict:
    """Apply-page counters: totals taken over the current Jun–May leave
    year, plus the Casual Leave balance.

    ``cl_balance`` is the same figure the Balances page and the apply
    guard use (``compute_balance`` for CASUAL as of ``on_date``), so the
    employee never sees two different CL numbers.
    """
    year_start, year_end = leave_year(on_date)
    approved = LeaveApplication.objects.filter(
        employee=employee,
        status=LeaveApplication.Status.APPROVED,
        from_date__gte=year_start,
        from_date__lte=year_end,
    )

    total_leaves = (
        approved.filter(leave_type__category=LeaveType.Category.LEAVE)
        .aggregate(s=Sum("count"))["s"] or _zero()
    )
    total_cl = (
        approved.filter(leave_type_id__in=[lt.id for lt in casual_types()])
        .aggregate(s=Sum("count"))["s"] or _zero()
    )
    total_compoff = (
        approved.filter(leave_type_id__in=[lt.id for lt in comp_off_types()])
        .aggregate(s=Sum("count"))["s"] or _zero()
    )

    cl_type = casual_type()
    cl_balance = (
        compute_balance(employee, cl_type, on_date)["balance"]
        if cl_type is not None else _zero()
    )

    return {
        "leave_year_start": str(year_start),
        "leave_year_end": str(year_end),
        "total_leaves_taken": total_leaves,
        "total_cl_taken": total_cl,
        "total_compoff_taken": total_compoff,
        "cl_balance": cl_balance,
    }
