"""Submit / decide / finalize / withdraw flows for relieving, plus the
Relieving Managers master helpers."""

import re
from datetime import datetime

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.employees.models import Employee
from apps.master.models import Institute

from .models import RelievingApplication, RelievingApproval, RelievingManager


# --- Relieving Managers master --------------------------------------

def managers_for(institute: Institute) -> list[RelievingManager]:
    """The institute's four master rows, in level order. Missing levels
    are created on the fly (approver unset) so the master page and the
    router always see exactly four rows."""
    existing = {
        m.level: m
        for m in RelievingManager.objects
        .filter(institute=institute)
        .select_related("approver")
    }
    out = []
    for level in RelievingManager.LEVELS:
        row = existing.get(level)
        if row is None:
            row = RelievingManager.objects.create(
                institute=institute, level=level,
                label=RelievingManager.DEFAULT_LABELS[level],
            )
        out.append(row)
    return out


@transaction.atomic
def save_managers(*, institute: Institute, levels: list[dict],
                  updated_by) -> list[RelievingManager]:
    """`levels` = [{level, approver (Employee|None), label}]. Levels not
    mentioned are left untouched. Each approver must be an ACTIVE
    employee; the same person may hold more than one level (legacy let
    the Principal double up), but that is HR's call, not enforced."""
    by_level = {m.level: m for m in managers_for(institute)}
    for item in levels:
        row = by_level[item["level"]]
        approver = item.get("approver")
        if approver is not None and approver.status != Employee.Status.ACTIVE:
            raise ValueError(
                f"L{row.level}: {approver.full_name} is not an active employee."
            )
        row.approver = approver
        if (label := (item.get("label") or "").strip()):
            row.label = label
        row.updated_by = updated_by
        row.save(update_fields=["approver", "label", "updated_by", "updated_at"])
    return [by_level[level] for level in RelievingManager.LEVELS]


class ChainNotConfigured(ValueError):
    """Raised by `submit` when the institute's master is incomplete."""


def _approval_chain_for(employee: Employee) -> list[tuple[str, Employee | None]]:
    """Snapshot at submission time: the applicant's institute's L1–L4
    from the master. Every level must have an active approver — an
    unset or inactive level blocks submission (user rule 2026-11-06:
    every application truly gets four approvals; HR fixes the master
    first). The one exception is the applicant themselves holding a
    level (the Principal resigning): that level is returned as None
    and recorded SKIPPED, since nobody approves their own exit."""
    rows = managers_for(employee.institute)
    missing: list[str] = []
    chain: list[tuple[str, Employee | None]] = []
    for row in rows:
        approver = row.approver
        if approver is None:
            missing.append(f"L{row.level} ({row.label}) is not set")
        elif approver.status != Employee.Status.ACTIVE:
            missing.append(
                f"L{row.level} ({row.label}) {approver.full_name} is inactive"
            )
        elif approver.pk == employee.pk:
            approver = None  # self — skipped
        chain.append((row.label, approver))
    if missing:
        raise ChainNotConfigured(
            f"Relieving managers are not fully configured for "
            f"{employee.institute.name}: {'; '.join(missing)}. "
            "Ask HR to complete the Relieving Managers master."
        )
    return chain


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
           last_working_date_requested, submitted_by,
           application_type: str = RelievingApplication.Type.RELIEVING,
           ) -> RelievingApplication:
    """Create the application + 4 approval rows snapshotted from the
    institute's Relieving Managers master. Raises `ChainNotConfigured`
    when any level is unset or inactive."""
    chain = _approval_chain_for(employee)

    app = RelievingApplication.objects.create(
        employee=employee, reason=reason,
        application_type=application_type,
        last_working_date_requested=last_working_date_requested,
        submitted_by=submitted_by,
        status=RelievingApplication.Status.SUBMITTED,
    )
    for i, (label, mgr) in enumerate(chain, start=1):
        RelievingApproval.objects.create(
            application=app, level=i, label=label, approver=mgr,
            status=(
                RelievingApproval.Status.SKIPPED if mgr is None
                else RelievingApproval.Status.PENDING
            ),
            remarks="" if mgr else "Skipped — approver is the applicant.",
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

    # Final approval completes straight away (legacy parity: the L4
    # approval in hrsave.php generated the relieving letter).
    if pending == 0:
        finalize(
            application=app,
            last_working_date_approved=app.last_working_date_requested,
            finalized_by=decided_by,
        )
    return approval


# --- Finalize --------------------------------------------------------
# Called by `decide` on the final approval. The HR finalize endpoint
# remains only for applications approved before that was automatic.

@transaction.atomic
def finalize(*, application: RelievingApplication,
             last_working_date_approved, finalized_by,
             set_inactive: bool = True) -> RelievingApplication:
    """RELIEVING: stamp both letter numbers, COMPLETE, deactivate the
    employee. PART_TIME: COMPLETE only — the employee record is updated
    by HR by hand (legacy parity), no letters."""
    if application.status != RelievingApplication.Status.APPROVED:
        raise ValueError(
            f"Application status is {application.status}; "
            "must be APPROVED before finalize."
        )

    application.last_working_date_approved = last_working_date_approved
    application.status = RelievingApplication.Status.COMPLETED
    application.finalized_at = timezone.now()
    application.finalized_by = finalized_by
    fields = [
        "last_working_date_approved", "status",
        "finalized_at", "finalized_by", "updated_at",
    ]

    if application.is_relieving:
        inst_code = application.employee.institute.code
        application.relieving_letter_no = _generate_letter_no(
            kind="REL", institute_code=inst_code,
        )
        application.experience_letter_no = _generate_letter_no(
            kind="EXP", institute_code=inst_code,
        )
        fields += ["relieving_letter_no", "experience_letter_no"]
    application.save(update_fields=fields)

    if application.is_relieving and set_inactive:
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
