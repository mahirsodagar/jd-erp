"""Email dispatch for leave / comp-off workflows.

Every send is recorded in `EmailDispatchLog` *and* handed to the real
transport: `apps.notifications.email.send_email` (ZeptoMail, From
no-reply@dkul.in). Replies go to the leave department
(`LEAVES_HR_INBOX`, policy token HR_LEAVE) — the address is used only
as Reply-To, never as the sender.

A row therefore reflects what actually happened:
  sent   — the transport accepted the message,
  failed — it was rejected (reason in `error`); replay the failed rows
           with `manage.py send_leave_emails --failed`.

Delivery never raises into the request: a mail problem must not fail the
leave application itself.
"""

from django.conf import settings
from django.utils import timezone

from apps.leaves.models import EmailDispatchLog
from apps.notifications.inapp import notify, user_by_email
from apps.notifications.models import InAppNotification


HR_INBOX = getattr(settings, "LEAVES_HR_INBOX", "leave@jdinstitute.edu.in")

# Trigger keys registered in settings.EMAIL_REPLY_TO_POLICY (HR_LEAVE).
TPL_LEAVE_APPLIED = "leaves.application_employee.email"
TPL_LEAVE_DECISION = "leaves.application_status_employee.email"
TPL_COMPOFF_APPLIED = "leaves.compoff_application_employee.email"
TPL_COMPOFF_DECISION = "leaves.compoff_status_employee.email"


def _split_emails(s: str | None) -> list[str]:
    if not s:
        return []
    return [e.strip() for e in s.split(",") if e.strip()]


def reply_to_for(template: str, context: dict | None = None) -> str:
    """Reply-To for a leave trigger: the leave department inbox."""
    from apps.notifications.reply_to import resolve_reply_to

    return resolve_reply_to(template, context)


def deliver(log: EmailDispatchLog) -> EmailDispatchLog:
    """Attempt delivery of one logged email and record the outcome."""
    from apps.notifications.email import send_email

    try:
        ok, detail = send_email(
            recipient=log.to, cc=log.cc,
            subject=log.subject, body=log.body,
            reply_to=reply_to_for(log.template, log.context),
        )
    except Exception as e:  # defensive — send_email already traps SMTP errors
        ok, detail = False, f"{type(e).__name__}: {e}"

    log.status = (EmailDispatchLog.Status.SENT if ok
                  else EmailDispatchLog.Status.FAILED)
    log.sent_at = timezone.now() if ok else None
    log.error = "" if ok else detail
    log.save(update_fields=["status", "sent_at", "error"])
    return log


def send_email_now(*, template: str, to: str, subject: str, body: str,
                   cc: str = "", context: dict | None = None,
                   application=None, compoff=None) -> EmailDispatchLog:
    """Log an outbound email and send it."""
    log = EmailDispatchLog.objects.create(
        template=template, to=to, cc=cc, subject=subject, body=body,
        context=context or {},
        related_application=application, related_compoff=compoff,
    )
    return deliver(log)


# Historical name — kept so existing callers/tests keep working.
queue_email = send_email_now


# --- Specific events ---------------------------------------------------

def notify_leave_applied(application) -> None:
    emp = application.employee
    notify(
        [user_by_email(application.manager_email)],
        kind=InAppNotification.Kind.LEAVE,
        title=f"Leave request from {emp.full_name}",
        body=(f"{application.leave_type.name}, {application.from_date} to "
              f"{application.to_date} ({application.count} day(s))."),
        link="/leaves/team", exclude_user=emp.user_account,
    )
    cc_list = _split_emails(application.cc_emails) + [HR_INBOX]
    body = (
        f"{emp.full_name} ({emp.emp_code}) has applied for "
        f"{application.leave_type.name}.\n"
        f"Dates: {application.from_date} → {application.to_date}\n"
        f"Days: {application.count} "
        f"({application.SESSION_LABELS.get(application.from_session, application.from_session)})\n"
        f"Reason: {application.reason}\n"
    )
    send_email_now(
        template=TPL_LEAVE_APPLIED,
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
    notify(
        [emp.user_account], kind=InAppNotification.Kind.LEAVE,
        title=f"Leave {decision}",
        body=(f"{application.leave_type.name}, {application.from_date} to "
              f"{application.to_date}. "
              f"{application.approver_remarks or ''}").strip(),
        link="/leaves/my",
    )
    send_email_now(
        template=TPL_LEAVE_DECISION,
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


def notify_compoff_applied(compoff) -> None:
    emp = compoff.employee
    notify(
        [user_by_email(compoff.manager_email)],
        kind=InAppNotification.Kind.LEAVE,
        title=f"Comp-off request from {emp.full_name}",
        body=f"Worked on {compoff.worked_date}, earning {compoff.count} day(s).",
        link="/leaves/comp-off", exclude_user=emp.user_account,
    )
    cc_list = _split_emails(compoff.cc_emails) + [HR_INBOX]
    send_email_now(
        template=TPL_COMPOFF_APPLIED,
        to=compoff.manager_email or HR_INBOX,
        cc=", ".join(cc_list),
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
    notify(
        [emp.user_account], kind=InAppNotification.Kind.LEAVE,
        title=f"Comp-off {decision}",
        body=(f"Worked date {compoff.worked_date}. "
              f"{compoff.approver_remarks or ''}").strip(),
        link="/leaves/comp-off",
    )
    send_email_now(
        template=TPL_COMPOFF_DECISION,
        to=emp.email_primary,
        cc=compoff.manager_email,
        subject=f"Comp-off {decision} — {compoff.worked_date}",
        body=(
            f"Your comp-off for {compoff.worked_date} has been {decision}.\n"
            f"Remarks: {compoff.approver_remarks or '(none)'}"
        ),
        compoff=compoff,
    )
