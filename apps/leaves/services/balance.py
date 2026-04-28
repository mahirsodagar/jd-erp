"""Per-employee leave balance computation. Returns plain dicts so the
caller (serializers, reports) can shape them as needed."""

from decimal import Decimal

from django.db.models import Sum

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType, Session,
)


COMP_OFF_CODE = "COMP_OFF"


def _zero() -> Decimal:
    return Decimal("0.0")


def compute_balance(employee, leave_type: LeaveType, session: Session | None) -> dict:
    """Return {granted, pending, availed, balance} for a regular LEAVE type,
    or {earned, used, balance} for COMP_OFF. The session is required for
    standard types; ignored for COMP_OFF."""

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

    granted = _zero()
    pending = _zero()
    availed = _zero()

    if session:
        granted = (
            LeaveAllocation.objects
            .filter(employee=employee, session=session, leave_type=leave_type)
            .aggregate(s=Sum("count"))["s"] or _zero()
        )

    apps_qs = LeaveApplication.objects.filter(
        employee=employee, leave_type=leave_type,
    )
    if session:
        apps_qs = apps_qs.filter(
            from_date__gte=session.start_date,
            from_date__lte=session.end_date,
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


def all_balances(employee, session: Session | None) -> list[dict]:
    return [
        compute_balance(employee, lt, session)
        for lt in LeaveType.objects.filter(is_active=True).order_by("name")
    ]
