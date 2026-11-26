from datetime import date

from django.db import transaction
from django.utils import timezone

from .models import StudentLeaveApplication


@transaction.atomic
def apply_leave(*, student, leave_date: date, leave_edate: date,
                student_remarks: str, batch_mentor_email: str,
                module_mentor_email: str = "",
                cc_emails: list[str] | None = None) -> StudentLeaveApplication:
    if leave_edate < leave_date:
        raise ValueError("leave_edate must be on or after leave_date.")
    # No overlap with a pending or approved leave: the same day can't be
    # applied for twice (and the report would otherwise count it twice).
    clash = (
        StudentLeaveApplication.objects
        .filter(
            student=student,
            status__in=(StudentLeaveApplication.Status.SUBMITTED,
                        StudentLeaveApplication.Status.APPROVED),
            leave_date__lte=leave_edate, leave_edate__gte=leave_date,
        )
        .order_by("leave_date")
        .first()
    )
    if clash is not None:
        span = (
            f"{clash.leave_date:%d %b %Y}" if clash.leave_date == clash.leave_edate
            else f"{clash.leave_date:%d %b %Y} – {clash.leave_edate:%d %b %Y}"
        )
        raise ValueError(
            f"Overlaps your {clash.get_status_display().lower()} leave ({span})."
        )
    app = StudentLeaveApplication.objects.create(
        student=student,
        leave_date=leave_date, leave_edate=leave_edate,
        student_remarks=student_remarks,
        batch_mentor_email=batch_mentor_email,
        module_mentor_email=module_mentor_email or "",
        cc_emails=cc_emails or [],
    )
    from .notifications import send_leave_applied
    # After commit, so a rolled-back create never mails the mentor.
    transaction.on_commit(lambda: send_leave_applied(app))
    return app


@transaction.atomic
def decide_leave(*, application: StudentLeaveApplication,
                 decision: str, remarks: str = "",
                 decided_by) -> StudentLeaveApplication:
    if application.status != StudentLeaveApplication.Status.SUBMITTED:
        raise ValueError(f"Application is already {application.status}.")
    if decision not in (StudentLeaveApplication.Status.APPROVED,
                        StudentLeaveApplication.Status.REJECTED):
        raise ValueError("decision must be APPROVED or REJECTED.")
    application.status = decision
    application.approver_remarks = remarks or ""
    application.decided_by = decided_by
    application.decided_at = timezone.now()
    application.save(update_fields=[
        "status", "approver_remarks", "decided_by", "decided_at", "updated_at",
    ])
    if decision == StudentLeaveApplication.Status.APPROVED:
        from .notifications import send_leave_accepted
        # After commit, so a rolled-back decision never mails the student.
        transaction.on_commit(lambda: send_leave_accepted(application))
    return application
