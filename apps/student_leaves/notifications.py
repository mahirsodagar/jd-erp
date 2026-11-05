"""Student leave e-mails, sent through MSG91 templates via the
notifications layer (both keys routed to mail.jdinstitute.com by
EMAIL_SENDER_DOMAIN_POLICY). Every send writes a NotificationDispatchLog
row (GFK → the application) for audit.

    submitted → `student_leaves.applied.email`  → MSG91 `student_leave_application_`
                To batch mentor; CC module mentor + student's CCs + student
    approved  → `student_leaves.accepted.email` → MSG91 `student_leave_accepted`
                To student

Both MSG91 templates use the same variables (names must match exactly):
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
    return {
        "Student_Name": app.student.student_name,
        "Leave_Start_Date": app.leave_date.strftime(_DATE_FMT),
        "Leave_End_Date": app.leave_edate.strftime(_DATE_FMT),
        "Leave_Count": str(app.days),
        "Reason": app.student_remarks or "-",
    }


def _queue(app, key, recipient, cc=""):
    """Never raises — a mail failure must not undo the leave action."""
    try:
        return queue_notification(
            template_key=key, recipient=recipient,
            context=leave_context(app), cc=cc, related=app,
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
    return _queue(app, APPLIED_KEY, to, ",".join(cc))


def send_leave_accepted(app: StudentLeaveApplication):
    """Mail the student that their leave was approved."""
    recipient = (app.student.student_email or "").strip()
    if not recipient:
        log.warning("student leave %s approved but student has no email", app.pk)
        return None
    return _queue(app, ACCEPTED_KEY, recipient)
