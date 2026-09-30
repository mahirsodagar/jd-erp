"""Submit / decide / accept / finalize / withdraw flows for relieving."""

import re
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.employees.models import Employee

from .models import RelievingApplication, RelievingApproval


# --- Helpers --------------------------------------------------------

def _fixed_approver(email: str, *, applicant: Employee) -> Employee | None:
    """Active employee whose primary email is `email`. Never the
    applicant themselves — nobody approves their own exit."""
    if not email:
        return None
    return (Employee.objects
            .filter(email_primary__iexact=email.strip(),
                    status=Employee.Status.ACTIVE)
            .exclude(pk=applicant.pk)
            .first())


def _approval_chain_for(employee: Employee) -> list[Employee | None]:
    """Snapshot at submission time: reporting_manager_1 and _2, then the
    institute-wide L3 (Principal) and L4 (HR) from settings. L3/L4 fall
    back to reporting_manager_3/_4 when the setting is blank or matches
    no active employee."""
    l3 = _fixed_approver(settings.RELIEVING_L3_APPROVER_EMAIL, applicant=employee)
    l4 = _fixed_approver(settings.RELIEVING_L4_APPROVER_EMAIL, applicant=employee)
    return [
        employee.reporting_manager_1,
        employee.reporting_manager_2,
        l3 or employee.reporting_manager_3,
        l4 or employee.reporting_manager_4,
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

    # Final approval issues the letters straight away (legacy parity:
    # the L4 approval in hrsave.php generated the relieving letter).
    if pending == 0:
        finalize(
            application=app,
            last_working_date_approved=app.last_working_date_requested,
            finalized_by=decided_by,
        )
    return approval


# --- Accept directly (HR) -------------------------------------------

@transaction.atomic
def accept(*, application: RelievingApplication, last_working_date_approved,
           accepted_by, remarks: str = "",
           set_inactive: bool = True) -> RelievingApplication:
    """HR accepts the resignation in one step: every still-pending level
    is approved on HR's behalf (recorded as such in the chain), then the
    application is finalized."""
    if application.status not in (
        RelievingApplication.Status.SUBMITTED,
        RelievingApplication.Status.IN_REVIEW,
    ):
        raise ValueError(f"Application is {application.status}; cannot accept.")

    note = "Accepted directly by HR." + (f" {remarks}" if remarks else "")
    application.approvals.filter(
        status=RelievingApproval.Status.PENDING,
    ).update(
        status=RelievingApproval.Status.APPROVED,
        remarks=note, decided_at=timezone.now(), decided_by=accepted_by,
    )
    application.status = RelievingApplication.Status.APPROVED
    application.save(update_fields=["status", "updated_at"])

    return finalize(
        application=application,
        last_working_date_approved=last_working_date_approved,
        finalized_by=accepted_by, set_inactive=set_inactive,
    )


# --- Finalize (letters issued) --------------------------------------
# Called by `decide` on the final approval. The HR finalize endpoint
# remains only for applications approved before that was automatic.

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
        application.employee.set_status(
            Employee.Status.INACTIVE,
            reason=(f"Relieved — relieving letter {application.relieving_letter_no}, "
                    f"last working day {last_working_date_approved:%d/%m/%Y}"),
            user=finalized_by,
        )

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
