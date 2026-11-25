"""Email dispatch for leave / comp-off workflows.

Every send is recorded in `EmailDispatchLog` *and* handed to the real
transport: `apps.notifications.email.send_email` (ZeptoMail, From
no-reply@dkul.in). Every leave / comp-off mail CCs the leave inbox of
the employee's campus (`LEAVE_CAMPUS_INBOXES`, client list 2026-11-20,
`LEAVES_HR_INBOX` as fallback) and replies go there too (policy token
HR_LEAVE) — the address is used only as CC / Reply-To, never as the
sender.

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


def leave_inbox_for(employee) -> str:
    """The leave inbox CC'd on this employee's leave / comp-off mail: the
    campus leave inbox (settings LEAVE_CAMPUS_INBOXES, keyed on
    `Campus.code` — client list 2026-11-20), else LEAVES_HR_INBOX."""
    from apps.notifications.reply_to import campus_code_of, leave_inbox_for_code

    return leave_inbox_for_code(campus_code_of(employee)) or HR_INBOX


def _campus_context(employee, **extra) -> dict:
    """Template context: the shared employee variables (which carry the
    campus code, so the Reply-To policy token HR_LEAVE lands on the same
    campus inbox as the CC) plus the trigger's own."""
    from apps.notifications.context import employee_vars
    from apps.notifications.reply_to import campus_code_of

    return {**employee_vars(employee), "campus_code": campus_code_of(employee), **extra}


def _d(value) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _leave_vars(application) -> dict:
    session = application.SESSION_LABELS.get(
        application.from_session, application.from_session,
    )
    return {
        "Leave_Type": application.leave_type.name,
        "From_Date": _d(application.from_date),
        "To_Date": _d(application.to_date),
        "Days": str(application.count),
        "Session": str(session),
        "Reason": application.reason or "",
    }


def _compoff_vars(compoff) -> dict:
    return {
        "Worked_Date": _d(compoff.worked_date),
        "Sessions_Worked": f"{compoff.worked_session_1}+{compoff.worked_session_2}",
        "Earned_Days": str(compoff.count),
        "Reason": compoff.reason or "",
    }


def _cc(*parts: str) -> str:
    """Comma-joined CC list, blanks dropped, duplicates (case-insensitive)
    collapsed, order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for addr in _split_emails(part):
            if addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
    return ", ".join(out)

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
    """Re-deliver one logged email (replay of a failed row by
    `manage.py send_leave_emails --failed`) and record the outcome. The
    stored body is the rendered HTML, so it goes out as HTML."""
    from apps.notifications.email import send_email

    try:
        ok, detail = send_email(
            recipient=log.to, cc=log.cc,
            subject=log.subject, body=log.body,
            is_html=(log.body or "").lstrip()[:1] == "<",
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


def send_email_now(*, template: str, to: str, cc: str = "",
                   context: dict | None = None,
                   application=None, compoff=None) -> EmailDispatchLog:
    """Send one leave / comp-off mail from its system e-mail template
    (Communication → System Emails) and mirror the outcome into the
    leave module's own `EmailDispatchLog` for audit and replay."""
    from apps.notifications.services import send_system_email

    related = application if application is not None else compoff
    dispatch = send_system_email(
        template, recipient=to, cc=cc, context=context or {}, related=related,
    )
    sent = getattr(dispatch, "status", "") == "SENT"
    return EmailDispatchLog.objects.create(
        template=template, to=to, cc=getattr(dispatch, "cc", cc) or cc,
        subject=getattr(dispatch, "subject", ""), body=getattr(dispatch, "body", ""),
        context=context or {},
        status=(EmailDispatchLog.Status.SENT if sent else EmailDispatchLog.Status.FAILED),
        sent_at=timezone.now() if sent else None,
        error="" if sent else (getattr(dispatch, "error", "") or ""),
        related_application=application, related_compoff=compoff,
    )


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
    send_email_now(
        template=TPL_LEAVE_APPLIED,
        to=application.manager_email,
        cc=_cc(application.cc_emails, leave_inbox_for(emp)),
        application=application,
        context=_campus_context(emp, **_leave_vars(application)),
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
        cc=_cc(application.manager_email, leave_inbox_for(emp)),
        application=application,
        context=_campus_context(
            emp, **_leave_vars(application),
            Decision=decision, Remarks=application.approver_remarks or "(none)",
        ),
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
    inbox = leave_inbox_for(emp)
    to = compoff.manager_email or inbox
    send_email_now(
        template=TPL_COMPOFF_APPLIED,
        to=to,
        # No manager on file → the inbox is already the To; don't CC it too.
        cc=_cc(compoff.cc_emails, inbox if to != inbox else ""),
        compoff=compoff,
        context=_campus_context(emp, **_compoff_vars(compoff)),
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
        cc=_cc(compoff.manager_email, leave_inbox_for(emp)),
        compoff=compoff,
        context=_campus_context(
            emp, **_compoff_vars(compoff),
            Decision=decision, Remarks=compoff.approver_remarks or "(none)",
        ),
    )
