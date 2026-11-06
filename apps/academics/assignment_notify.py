"""'New assignment' e-mail to students — MSG91 template `assignmentassigned`
via the notifications layer (key `academics.assignment_assigned.email`).

Fires when an assignment becomes visible to students: on create when
published, or when an unpublished one is flipped to published. One mail
per student (each gets their own name), to every student with an ACTIVE
enrollment the assignment reaches — the exact batch, or every batch of
the program when no batch is set (narrowed to the assignment's semester
when one is set). Same reach as the portal's `_assignments_for_batch`.

The fan-out runs in a background thread after commit: MSG91 is one HTTP
call per student, and a batch of 60 must not hold the faculty's request.

MSG91 variables (positional, as the template defines them):
    VAR1 student name   VAR2 subject   VAR3 assignment title
    VAR4 deadline       VAR5 submission mode
"""

from __future__ import annotations

import logging
import threading
from zoneinfo import ZoneInfo

from django.db import close_old_connections, transaction

log = logging.getLogger(__name__)

TEMPLATE_KEY = "academics.assignment_assigned.email"
SUBMISSION_MODE = "Online (Student Portal)"
_IST = ZoneInfo("Asia/Kolkata")


def recipients_for(assignment):
    """Students (with an email) the assignment reaches, de-duplicated."""
    from apps.admissions.models import Enrollment

    qs = Enrollment.objects.filter(status=Enrollment.Status.ACTIVE)
    if assignment.batch_id:
        qs = qs.filter(batch_id=assignment.batch_id)
    elif assignment.program_id:
        qs = qs.filter(program_id=assignment.program_id)
        if assignment.semester_id:
            qs = qs.filter(semester_id=assignment.semester_id)
    else:
        return []
    seen, out = set(), []
    for e in qs.select_related("student"):
        s = e.student
        email = (s.student_email or "").strip()
        if s.pk in seen or not email:
            continue
        seen.add(s.pk)
        out.append(s)
    return out


def context_for(assignment, student) -> dict:
    due = assignment.due_date.astimezone(_IST)
    return {
        "VAR1": student.student_name,
        "VAR2": assignment.subject.name,
        "VAR3": assignment.title,
        "VAR4": due.strftime("%d-%m-%Y %I:%M %p"),
        "VAR5": SUBMISSION_MODE,
    }


def send_assignment_assigned(assignment) -> int:
    """Mail every reached student now. Returns how many were queued.
    Never raises — one bad row must not stop the rest."""
    from apps.notifications.services import queue_notification

    sent = 0
    for student in recipients_for(assignment):
        try:
            queue_notification(
                template_key=TEMPLATE_KEY,
                recipient=student.student_email.strip(),
                context=context_for(assignment, student),
                related=assignment,
            )
            sent += 1
        except Exception:  # noqa: BLE001
            log.exception("assignment %s: mail to student %s failed",
                          assignment.pk, student.pk)
    return sent


def _run(assignment_id: int) -> None:
    from .models import Assignment

    close_old_connections()
    try:
        a = (Assignment.objects.select_related("subject")
             .filter(pk=assignment_id, is_published=True).first())
        if a is not None:
            n = send_assignment_assigned(a)
            log.info("assignment %s: queued %s student mail(s)", a.pk, n)
    except Exception:  # noqa: BLE001
        log.exception("assignment %s: fan-out failed", assignment_id)
    finally:
        close_old_connections()


def schedule_assignment_assigned(assignment) -> None:
    """Fan out after the current transaction commits, off-request."""
    aid = assignment.pk
    transaction.on_commit(
        lambda: threading.Thread(
            target=_run, args=(aid,), daemon=True,
            name=f"assignment-mail-{aid}",
        ).start(),
    )


# ---------------------------------------------------------------------
# Student submitted → faculty (MSG91 `assignment_submitted`)
# ---------------------------------------------------------------------

SUBMITTED_KEY = "academics.assignment_submitted.email"


def faculty_for(assignment) -> tuple[str, str]:
    """(email, name) of the faculty who set the assignment — the
    `created_by` user's employee record, else the user account itself."""
    u = assignment.created_by
    if u is None:
        return "", ""
    emp = getattr(u, "employee", None)
    email = (getattr(emp, "email_primary", "") or u.email or "").strip()
    name = (getattr(emp, "full_name", "") or getattr(u, "full_name", "")
            or u.get_username())
    return email, name


def send_assignment_submitted(submission):
    """Mail the faculty that a student submitted. Fires on every submit
    (resubmits included). Never raises."""
    from apps.notifications.services import queue_notification

    a = submission.assignment
    to, faculty_name = faculty_for(a)
    if not to:
        log.info("assignment %s: no faculty email, submission mail skipped",
                 a.pk)
        return None
    try:
        return queue_notification(
            template_key=SUBMITTED_KEY,
            recipient=to,
            context={
                "Faculty_Name": faculty_name,
                "Student_Name": submission.student.student_name,
                "Subject_Name": a.subject.name,
                "Assignment_Title": a.title,
            },
            related=submission,
        )
    except Exception:  # noqa: BLE001
        log.exception("submission %s: faculty mail failed", submission.pk)
        return None


def schedule_assignment_submitted(submission) -> None:
    transaction.on_commit(lambda: send_assignment_submitted(submission))
