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
    # Block duplicate active application for the same start date
    if StudentLeaveApplication.objects.filter(
        student=student, leave_date=leave_date,
        status=StudentLeaveApplication.Status.SUBMITTED,
    ).exists():
        raise ValueError(
            "You already have a pending leave for this start date."
        )
    return StudentLeaveApplication.objects.create(
        student=student,
        leave_date=leave_date, leave_edate=leave_edate,
        student_remarks=student_remarks,
        batch_mentor_email=batch_mentor_email,
        module_mentor_email=module_mentor_email or "",
        cc_emails=cc_emails or [],
    )


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
    return application
