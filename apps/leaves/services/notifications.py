"""Email dispatch wrappers. On PythonAnywhere free we cannot reach SMTP,
so we record intended emails in `EmailDispatchLog` for later replay.

When you upgrade hosting, write a real sender that drains rows where
status='queued' and updates them to 'sent' / 'failed'."""

from django.conf import settings

from apps.leaves.models import EmailDispatchLog


HR_INBOX = getattr(settings, "LEAVES_HR_INBOX", "leave@jdinstitute.edu.in")


def _split_emails(s: str | None) -> list[str]:
    if not s:
        return []
    return [e.strip() for e in s.split(",") if e.strip()]


def queue_email(*, template: str, to: str, subject: str, body: str,
                cc: str = "", context: dict | None = None,
                application=None, compoff=None) -> EmailDispatchLog:
    return EmailDispatchLog.objects.create(
        template=template, to=to, cc=cc, subject=subject, body=body,
        context=context or {},
        related_application=application, related_compoff=compoff,
    )


# --- Specific events ---------------------------------------------------

def notify_leave_applied(application) -> None:
    emp = application.employee
    cc_list = _split_emails(application.cc_emails) + [HR_INBOX]
    body = (
        f"{emp.full_name} ({emp.emp_code}) has applied for "
        f"{application.leave_type.name}.\n"
        f"Dates: {application.from_date} → {application.to_date}\n"
        f"Days: {application.count} (session {application.from_session})\n"
        f"Reason: {application.reason}\n"
    )
    queue_email(
        template="employee_leave_application",
        to=application.manager_email,
        cc=", ".join(cc_list),
        subject=f"Leave application — {emp.full_name} ({application.from_date})",
        body=body,
        application=application,
        context={
            "employee_id": emp.id, "leave_type": application.leave_type.code,
            "from_date": str(application.from_date),
            "to_date": str(application.to_date),
            "count": str(application.count),
        },
    )


def notify_leave_decision(application) -> None:
    emp = application.employee
    decision = "approved" if application.status == 2 else "rejected"
    queue_email(
        template="employee_leave_decision",
        to=emp.email_primary,
        cc=application.manager_email,
        subject=f"Leave {decision} — {application.from_date}",
        body=(
            f"Your leave application ({application.from_date} → "
            f"{application.to_date}) has been {decision}.\n\n"
            f"Remarks: {application.approver_remarks or '(none)'}"
        ),
        application=application,
        context={"decision": decision},
    )


def notify_leave_cancelled(application) -> None:
    queue_email(
        template="employee_leave_cancelled",
        to=application.manager_email,
        subject=f"Leave cancelled — {application.employee.full_name}",
        body=(
            f"{application.employee.full_name} cancelled their approved leave "
            f"({application.from_date} → {application.to_date})."
        ),
        application=application,
    )


def notify_compoff_applied(compoff) -> None:
    emp = compoff.employee
    rm = emp.reporting_manager_1
    to = (rm.email_primary if rm else HR_INBOX)
    queue_email(
        template="employee_compoff_application",
        to=to,
        cc=HR_INBOX,
        subject=f"Comp-off application — {emp.full_name} ({compoff.worked_date})",
        body=(
            f"{emp.full_name} ({emp.emp_code}) has applied for comp-off.\n"
            f"Worked date: {compoff.worked_date}\n"
            f"Sessions worked: {compoff.worked_session_1}+{compoff.worked_session_2}\n"
            f"Earned: {compoff.count}\n"
            f"Reason: {compoff.reason}"
        ),
        compoff=compoff,
    )


def notify_compoff_decision(compoff) -> None:
    emp = compoff.employee
    decision = "approved" if compoff.status == 2 else "rejected"
    queue_email(
        template="employee_compoff_decision",
        to=emp.email_primary,
        subject=f"Comp-off {decision} — {compoff.worked_date}",
        body=(
            f"Your comp-off for {compoff.worked_date} has been {decision}.\n"
            f"Remarks: {compoff.approver_remarks or '(none)'}"
        ),
        compoff=compoff,
    )
