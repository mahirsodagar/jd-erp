"""Apply-time guards: no overlapping leaves, no overdrawn balances.

Legacy JD_ERP enforced neither (doc issue #6 — the "insufficient balance"
check was commented out), so employees could stack leaves on the same day
and drive balances negative. Both checks run on apply and again on approve.
"""

from decimal import Decimal

from apps.leaves.models import LeaveApplication, LeaveType
from apps.leaves.services.balance import compute_balance


FULL_DAY = 2
_LIVE = (LeaveApplication.Status.PENDING, LeaveApplication.Status.APPROVED)


def find_overlap(*, employee, from_date, to_date, from_session,
                 exclude_id=None, statuses=_LIVE):
    """First application of ``employee`` in ``statuses`` (default:
    pending/approved) that clashes with the requested range, or None.

    Two single-day, part-day requests on the same date only clash when they
    use the same session (e.g. permission slot 1 + slot 2 can coexist).
    Anything involving a full day or a multi-day span clashes on any shared
    date.
    """
    qs = LeaveApplication.objects.filter(
        employee=employee, status__in=statuses,
        from_date__lte=to_date, to_date__gte=from_date,
    ).select_related("leave_type")
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)

    new_is_part_day = from_date == to_date and from_session != FULL_DAY
    for other in qs:
        other_is_part_day = (
            other.from_date == other.to_date and other.from_session != FULL_DAY
        )
        if new_is_part_day and other_is_part_day and other.from_session != from_session:
            continue
        return other
    return None


def overlap_message(other: LeaveApplication) -> str:
    span = (
        f"{other.from_date:%d %b %Y}" if other.from_date == other.to_date
        else f"{other.from_date:%d %b %Y} – {other.to_date:%d %b %Y}"
    )
    return (
        f"Overlaps your {other.get_status_display().lower()} "
        f"{other.leave_type.name} ({span})."
    )


def available_balance(employee, leave_type: LeaveType, *, include_pending=True,
                      exclude_id=None) -> Decimal | None:
    """Days still spendable on ``leave_type``, or None if it isn't
    balance-enforced.

    ``include_pending`` reserves days already requested but undecided so
    that several pending applies can't jointly overdraw the balance.
    ``exclude_id`` drops one pending application from that reservation
    (the one being approved).
    """
    if not leave_type.enforce_balance:
        return None
    row = compute_balance(employee, leave_type)
    available = row["balance"]
    if include_pending:
        pending = LeaveApplication.objects.filter(
            employee=employee, leave_type=leave_type,
            status=LeaveApplication.Status.PENDING,
        )
        if exclude_id is not None:
            pending = pending.exclude(pk=exclude_id)
        available -= sum((a.count for a in pending), Decimal("0"))
    return available


def balance_message(leave_type: LeaveType, requested: Decimal,
                    available: Decimal) -> str:
    return (
        f"Insufficient {leave_type.name} balance: requested {requested}, "
        f"available {max(available, Decimal('0'))}."
    )
