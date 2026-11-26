"""Apply-time guards: no overlapping leaves, no overdrawn balances, no
self-approval, no double-earned comp-off.

Legacy JD_ERP enforced none of these (doc issue #6 — the "insufficient
balance" check was commented out), so employees could stack leaves on the
same day and drive balances negative. The overlap and balance checks run on
apply and again on approve.
"""

from decimal import Decimal

from django.utils import timezone

from apps.leaves.models import CompOffApplication, LeaveApplication, LeaveType
from apps.leaves.services.balance import COMP_OFF_CODE, compute_balance


FULL_DAY = 2
_LIVE = (LeaveApplication.Status.PENDING, LeaveApplication.Status.APPROVED)
# Part-day sessions that fall inside one another: permission slot 1
# (9:30–11) is in the first half, slot 2 (4:00–5:30) in the second.
_NESTED = {frozenset({1, 3}), frozenset({5, 4})}


def _sessions_clash(a: int, b: int) -> bool:
    return a == b or frozenset({a, b}) in _NESTED


def find_overlap(*, employee, from_date, to_date, from_session,
                 exclude_id=None, statuses=_LIVE):
    """First application of ``employee`` in ``statuses`` (default:
    pending/approved) that clashes with the requested range, or None.

    Two single-day, part-day requests on the same date only clash when they
    use the same session or one sits inside the other (first half +
    second half can coexist; first half + permission slot 1 cannot).
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
        if (new_is_part_day and other_is_part_day
                and not _sessions_clash(other.from_session, from_session)):
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


def available_balance(employee, leave_type: LeaveType, *, on_date=None,
                      include_pending=True, exclude_id=None) -> Decimal | None:
    """Days still spendable on ``leave_type`` in the allocation window
    covering ``on_date`` (the leave's from_date), or None if the type
    isn't balance-enforced or has no balance (ON_DUTY).

    ``include_pending`` reserves days already requested but undecided so
    that several pending applies can't jointly overdraw the balance.
    ``exclude_id`` drops one pending application from that reservation
    (the one being approved).
    """
    if not leave_type.enforce_balance:
        return None
    row = compute_balance(employee, leave_type, on_date)
    if row["balance"] is None:
        return None
    # row["balance"] already nets out every pending application.
    available = row["balance"]
    if not include_pending:
        available += row.get("pending") or Decimal("0")
    elif exclude_id is not None:
        excluded = LeaveApplication.objects.filter(
            pk=exclude_id, status=LeaveApplication.Status.PENDING,
        ).first()
        if excluded is not None:
            available += excluded.count
    return available


def has_allocation_for(employee, leave_type: LeaveType, on_date) -> bool:
    """False when a balance-enforced, allocation-based type has no
    allocation window covering ``on_date``. Comp-off and unenforced
    types always pass."""
    if not leave_type.enforce_balance or leave_type.code == COMP_OFF_CODE:
        return True
    if leave_type.category != LeaveType.Category.LEAVE:
        return True
    return compute_balance(employee, leave_type, on_date)["window_start"] is not None


def no_allocation_message(leave_type: LeaveType, on_date) -> str:
    return (
        f"No {leave_type.name} allocation covers {on_date:%d %b %Y}. "
        "Ask HR to allocate leave for that period."
    )


def balance_message(leave_type: LeaveType, requested: Decimal,
                    available: Decimal) -> str:
    return (
        f"Insufficient {leave_type.name} balance: requested {requested}, "
        f"available {max(available, Decimal('0'))}."
    )


# --- routing -------------------------------------------------------------

def own_emails(employee) -> set[str]:
    """Lower-cased emails that identify ``employee`` (login + both
    employee emails), for the self-routing check."""
    emails = {
        (getattr(employee, "email_primary", "") or "").strip().lower(),
        (getattr(employee, "email_alternate", "") or "").strip().lower(),
    }
    user = getattr(employee, "user_account", None)
    if user is not None:
        emails.add((getattr(user, "email", "") or "").strip().lower())
    emails.discard("")
    return emails


def routes_to_self(employee, manager_email: str) -> bool:
    """True when ``manager_email`` is one of the applicant's own
    addresses — a request routed to oneself could be self-approved."""
    return (manager_email or "").strip().lower() in own_emails(employee)


SELF_ROUTE_MESSAGE = "You cannot route a request to yourself."


# --- comp-off ------------------------------------------------------------

_COMPOFF_LIVE = (CompOffApplication.Status.PENDING, CompOffApplication.Status.APPROVED)


def find_compoff_clash(*, employee, worked_date, session_1: int, session_2: int,
                       exclude_id=None):
    """A pending/approved comp-off by ``employee`` for ``worked_date``
    that already claims one of the requested sessions, or None. The two
    half-day sessions of one date may be claimed by separate requests."""
    qs = CompOffApplication.objects.filter(
        employee=employee, worked_date=worked_date, status__in=_COMPOFF_LIVE,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    for other in qs:
        if (session_1 and other.worked_session_1) or (session_2 and other.worked_session_2):
            return other
    return None


def compoff_clash_message(other: CompOffApplication) -> str:
    return (
        f"You already have a {other.get_status_display().lower()} comp-off "
        f"for {other.worked_date:%d %b %Y} covering that session."
    )


def compoff_in_future(worked_date) -> bool:
    return worked_date > timezone.localdate()


COMPOFF_FUTURE_MESSAGE = "Comp-off can only be claimed for a day already worked."
