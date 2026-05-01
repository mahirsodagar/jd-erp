"""Submit / decide / finalize / withdraw flows for relieving."""

import re
from datetime import datetime

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.employees.models import Employee

from .models import RelievingApplication, RelievingApproval


# --- Helpers --------------------------------------------------------

def _approval_chain_for(employee: Employee) -> list[Employee | None]:
    """Snapshot of reporting_manager_1..4 at submission time."""
    return [
        employee.reporting_manager_1,
        employee.reporting_manager_2,
        employee.reporting_manager_3,
        employee.reporting_manager_4,
    ]


def _generate_letter_no(*, kind: str, institute_code: str,
                       year: int | None = None) -> str:
    """`kind` ∈ {'REL', 'EXP'}."""
    year = year or datetime.now().year
    prefix = f"{kind}-{institute_code.upper()}-{year}-"
    last = (RelievingApplication.objects
            .filter(**{
                "relieving_letter_no__startswith" if kind == "REL"
                else "experience_letter_no__startswith": prefix,
            })
            .aggregate(m=Max("relieving_letter_no" if kind == "REL"
                              else "experience_letter_no"))["m"])
    if last and (m := re.match(r".+-(\d+)$", last)):
        seq = int(m.group(1)) + 1
    else:
        seq = 1
    return f"{prefix}{seq:05d}"


# --- Submit ---------------------------------------------------------

@transaction.atomic
def submit(*, employee: Employee, reason: str,
           last_working_date_requested, submitted_by) -> RelievingApplication:
    """Create the application + 4 approval rows (some SKIPPED if RM
    not configured at that level)."""
    chain = _approval_chain_for(employee)
    if chain[0] is None:
        raise ValueError(
            "Employee has no reporting_manager_1; relieving cannot be routed."
        )

    app = RelievingApplication.objects.create(
        employee=employee, reason=reason,
        last_working_date_requested=last_working_date_requested,
        submitted_by=submitted_by,
        status=RelievingApplication.Status.SUBMITTED,
    )
    for i, mgr in enumerate(chain, start=1):
        RelievingApproval.objects.create(
            application=app, level=i, approver=mgr,
            status=(
                RelievingApproval.Status.SKIPPED if mgr is None
                else RelievingApproval.Status.PENDING
            ),
        )
    return app


# --- Decide (approve / reject) -------------------------------------

@transaction.atomic
def decide(*, approval: RelievingApproval, decision: str,
           remarks: str, decided_by) -> RelievingApproval:
    """`decision` ∈ {'APPROVED', 'REJECTED'}. Sequence is enforced
    here — earlier non-skipped levels must be APPROVED first."""
    if approval.status != RelievingApproval.Status.PENDING:
        raise ValueError(f"Approval is already {approval.status}.")
    if decision not in (
        RelievingApproval.Status.APPROVED,
        RelievingApproval.Status.REJECTED,
    ):
        raise ValueError("decision must be APPROVED or REJECTED.")

    app = approval.application
    if app.status not in (
        RelievingApplication.Status.SUBMITTED,
        RelievingApplication.Status.IN_REVIEW,
    ):
        raise ValueError(f"Application is {app.status}; cannot decide.")

    # Sequence: every prior non-SKIPPED level must be APPROVED.
    earlier = app.approvals.filter(level__lt=approval.level).order_by("level")
    for prior in earlier:
        if prior.status == RelievingApproval.Status.SKIPPED:
            continue
        if prior.status != RelievingApproval.Status.APPROVED:
            raise ValueError(
                f"L{prior.level} is {prior.status}; cannot decide L{approval.level} yet."
            )

    approval.status = decision
    approval.remarks = remarks or ""
    approval.decided_at = timezone.now()
    approval.decided_by = decided_by
    approval.save(update_fields=["status", "remarks", "decided_at", "decided_by"])

    if decision == RelievingApproval.Status.REJECTED:
        app.status = RelievingApplication.Status.REJECTED
        app.rejected_at_level = approval.level
        app.rejection_reason = remarks or ""
        app.save(update_fields=[
            "status", "rejected_at_level", "rejection_reason", "updated_at",
        ])
        return approval

    # Was this the last actionable level?
    pending = app.approvals.filter(
        status=RelievingApproval.Status.PENDING,
    ).count()
    if pending == 0:
        app.status = RelievingApplication.Status.APPROVED
    else:
        app.status = RelievingApplication.Status.IN_REVIEW
    app.save(update_fields=["status", "updated_at"])
    return approval


# --- Finalize (HR generates letters) -------------------------------

@transaction.atomic
def finalize(*, application: RelievingApplication,
             last_working_date_approved, finalized_by,
             set_inactive: bool = True) -> RelievingApplication:
    if application.status != RelievingApplication.Status.APPROVED:
        raise ValueError(
            f"Application status is {application.status}; "
            "must be APPROVED before finalize."
        )

    inst_code = application.employee.institute.code
    application.last_working_date_approved = last_working_date_approved
    application.relieving_letter_no = _generate_letter_no(
        kind="REL", institute_code=inst_code,
    )
    application.experience_letter_no = _generate_letter_no(
        kind="EXP", institute_code=inst_code,
    )
    application.status = RelievingApplication.Status.COMPLETED
    application.finalized_at = timezone.now()
    application.finalized_by = finalized_by
    application.save(update_fields=[
        "last_working_date_approved",
        "relieving_letter_no", "experience_letter_no",
        "status", "finalized_at", "finalized_by", "updated_at",
    ])

    if set_inactive:
        emp = application.employee
        emp.status = Employee.Status.INACTIVE
        emp.save(update_fields=["status", "updated_on"])

    return application


# --- Withdraw -------------------------------------------------------

@transaction.atomic
def withdraw(*, application: RelievingApplication,
             remarks: str = "") -> RelievingApplication:
    if application.status not in (
        RelievingApplication.Status.SUBMITTED,
        RelievingApplication.Status.IN_REVIEW,
        RelievingApplication.Status.APPROVED,
    ):
        raise ValueError(
            f"Cannot withdraw from status {application.status}."
        )
    application.status = RelievingApplication.Status.WITHDRAWN
    application.rejection_reason = (
        f"Withdrawn by employee.{(' ' + remarks) if remarks else ''}"
    )
    application.save(update_fields=["status", "rejection_reason", "updated_at"])
    return application
