"""Bell notifications for timetable changes.

Recipients are the slot's instructor (via Employee.user_account) and
the students enrolled in the batch (via Student.user_account). The
person making the change is never notified about it.
"""

from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification

from .attendance_service import roster_for_batch


def _recipients(batch, instructor):
    users = [getattr(instructor, "user_account", None)]
    for enr in roster_for_batch(batch).select_related("student__user_account"):
        users.append(enr.student.user_account)
    return users


def _fmt_time(t):
    return t.strftime("%I:%M %p").lstrip("0") if t else ""


def notify_slot(slot, *, verb: str, actor) -> None:
    """`verb` is 'scheduled', 'updated' or 'cancelled'."""
    when = f"{slot.date.strftime('%d-%m-%Y')}"
    ts = slot.time_slot
    if ts is not None:
        when += f", {_fmt_time(ts.start_time)}–{_fmt_time(ts.end_time)}"
    users = _recipients(slot.batch, slot.instructor)
    # Students and faculty land on their own "my timetable" views.
    staff = users[0]
    students = users[1:]
    body = f"{slot.subject.name} for {slot.batch.name} on {when}."
    notify(
        [staff], kind=InAppNotification.Kind.TIMETABLE,
        title=f"Class {verb}", body=body, link="/schedule/me",
        exclude_user=actor,
    )
    notify(
        students, kind=InAppNotification.Kind.TIMETABLE,
        title=f"Class {verb}", body=body, link="/portal/timetable",
        exclude_user=actor,
    )


def notify_batch_published(batch, *, instructors, start_date, end_date,
                           created: int, actor) -> None:
    """One summary line per person after a bulk publish, instead of a
    line per generated slot."""
    if not created:
        return
    span = f"{start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}"
    body = f"{created} class(es) for {batch.name}, {span}."
    notify(
        [getattr(i, "user_account", None) for i in instructors],
        kind=InAppNotification.Kind.TIMETABLE,
        title="Timetable published", body=body, link="/schedule/me",
        exclude_user=actor,
    )
    notify(
        [enr.student.user_account
         for enr in roster_for_batch(batch).select_related("student__user_account")],
        kind=InAppNotification.Kind.TIMETABLE,
        title="Timetable published", body=body, link="/portal/timetable",
        exclude_user=actor,
    )
