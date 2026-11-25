"""Student leave e-mails via the notifications layer (ZeptoMail, From
no-reply@dkul.in). Every send writes a NotificationDispatchLog row
(GFK → the application) for audit.

    submitted → `student_leaves.applied.email`
                To batch mentor; CC module mentor + student's CCs + student
                + campus leave inbox; Reply-To the student
    approved  → `student_leaves.accepted.email`
                To student; CC campus leave inbox; Reply-To the batch mentor

The campus leave inbox (settings LEAVE_CAMPUS_INBOXES, keyed on the
student's `Campus.code` — client list 2026-11-20) is CC'd on both so
the campus desk holds a copy.

Both templates use the same variables (names must match exactly):
    Student_Name, Leave_Start_Date, Leave_End_Date, Leave_Count, Reason
"""

from __future__ import annotations

import logging

from apps.notifications.services import queue_notification

from .models import StudentLeaveApplication

log = logging.getLogger(__name__)

APPLIED_KEY = "student_leaves.applied.email"
ACCEPTED_KEY = "student_leaves.accepted.email"

_DATE_FMT = "%d-%m-%Y"


def leave_context(app: StudentLeaveApplication) -> dict:
    from apps.notifications.context import student_vars

    return {
        **student_vars(app.student),
        "Leave_Start_Date": app.leave_date.strftime(_DATE_FMT),
        "Leave_End_Date": app.leave_edate.strftime(_DATE_FMT),
        "Leave_Count": str(app.days),
        "Reason": app.student_remarks or "-",
    }


def campus_leave_inbox(app: StudentLeaveApplication) -> str:
    """The leave inbox of the student's campus, "" when none is set."""
    from apps.notifications.reply_to import campus_code_of, leave_inbox_for_code

    return leave_inbox_for_code(campus_code_of(getattr(app, "student", None)))


def _with_campus_inbox(app, to: str, cc: list[str]) -> list[str]:
    """`cc` plus the campus leave inbox, unless it is already To or CC."""
    inbox = campus_leave_inbox(app)
    seen = {to.lower(), *(e.lower() for e in cc)}
    if inbox and inbox.lower() not in seen:
        cc = [*cc, inbox]
    return cc


def _queue(app, key, recipient, cc="", reply_to=""):
    """Never raises — a mail failure must not undo the leave action."""
    try:
        return queue_notification(
            template_key=key, recipient=recipient,
            context={**leave_context(app), "reply_to": reply_to},
            cc=cc, related=app,
        )
    except Exception:  # noqa: BLE001 — log and move on
        log.exception("student leave %s: %s mail failed", app.pk, key)
        return None


def send_leave_applied(app: StudentLeaveApplication):
    """Mail the batch mentor that a student applied for leave."""
    to = (app.batch_mentor_email or "").strip()
    if not to:
        log.warning("student leave %s has no batch mentor email", app.pk)
        return None
    cc, seen = [], {to.lower()}
    for e in [app.module_mentor_email, *(app.cc_emails or []),
              app.student.student_email]:
        e = (e or "").strip()
        if e and e.lower() not in seen:
            seen.add(e.lower())
            cc.append(e)
    cc = _with_campus_inbox(app, to, cc)
    return _queue(app, APPLIED_KEY, to, ",".join(cc),
                  reply_to=(app.student.student_email or "").strip())


def send_leave_accepted(app: StudentLeaveApplication):
    """Mail the student that their leave was approved."""
    recipient = (app.student.student_email or "").strip()
    if not recipient:
        log.warning("student leave %s approved but student has no email", app.pk)
        return None
    cc = _with_campus_inbox(app, recipient, [])
    return _queue(app, ACCEPTED_KEY, recipient, ",".join(cc),
                  reply_to=(app.batch_mentor_email or "").strip())
