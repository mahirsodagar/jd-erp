"""In-app bell notifications for the student-appointment flow.

Request   → the staff who can see it on the staff Appointments page:
            every active user holding `appointments.view_all`, plus the
            named faculty member's login when the request is addressed
            to one. Same scope rule as `views._in_scope`.
Decision  → the student's portal login (confirmed / declined).
Cancelled → the same staff as the request, so a pending row vanishing
            from their list is explained.

In-app only, on purpose — same as the certificate flow.
"""

from apps.accounts.models import User
from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification

VIEW_ALL_KEY = "appointments.view_all"
STAFF_LINK = "/appointments"
PORTAL_LINK = "/portal/appointments"


def _staff_for(appt):
    users = list(
        User.objects
        .filter(is_active=True, roles__permissions__key=VIEW_ALL_KEY)
        .distinct()
    )
    if appt.faculty_id and appt.faculty.user_account_id:
        users.append(appt.faculty.user_account)
    return users


def _target(appt) -> str:
    if appt.faculty_id:
        return appt.faculty.full_name
    return appt.get_team_display()


def _slot(d, t) -> str:
    if not d:
        return ""
    s = d.strftime("%d-%m-%Y")
    if t:
        s += f" {t.strftime('%H:%M')}"
    return s


def notify_appointment_requested(appt) -> int:
    student = appt.student
    return notify(
        _staff_for(appt),
        kind=InAppNotification.Kind.OTHER,
        title="Appointment requested",
        body=(f"{student.student_name} ({student.application_form_id}) "
              f"has requested an appointment with {_target(appt)} on "
              f"{_slot(appt.preferred_date, appt.preferred_time)}. "
              f"Reason: {appt.reason}"),
        link=STAFF_LINK,  # staff page opens on Requested by default
    )


def notify_appointment_decided(appt) -> int:
    if appt.status == appt.Status.CONFIRMED:
        title = "Appointment confirmed"
        body = (f"Your appointment with {_target(appt)} is confirmed for "
                f"{_slot(appt.scheduled_date, appt.scheduled_time)}"
                + (f" at {appt.venue}" if appt.venue else "") + ".")
    else:
        title = "Appointment declined"
        body = (f"Your appointment request with {_target(appt)} was "
                "declined.")
    if appt.staff_remarks:
        body += f" Remarks: {appt.staff_remarks}"
    return notify(
        [appt.student.user_account],
        kind=InAppNotification.Kind.OTHER,
        title=title, body=body, link=PORTAL_LINK,
    )


def notify_appointment_cancelled(appt) -> int:
    student = appt.student
    return notify(
        _staff_for(appt),
        kind=InAppNotification.Kind.OTHER,
        title="Appointment cancelled",
        body=(f"{student.student_name} ({student.application_form_id}) "
              f"cancelled their appointment with {_target(appt)} "
              f"({_slot(appt.preferred_date, appt.preferred_time)})."),
        link=STAFF_LINK,
    )
