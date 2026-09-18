"""Email dispatch for leave / comp-off workflows.

Every send is recorded in `EmailDispatchLog` *and* handed to the real
transport: `apps.notifications.email.send_email`, with the From-domain
and SMTP connection chosen by `apps.notifications.sender` (leave and
comp-off triggers route to the HR domain — see
`settings.EMAIL_SENDER_DOMAIN_POLICY`).

A row therefore reflects what actually happened:
  sent   — the transport accepted the message,
  failed — it was rejected (reason in `error`),
  queued — this host has SMTP egress disabled
           (`EMAIL_SMTP_OUTBOUND_ENABLED=False`), so the mail is kept
           for replay by `manage.py send_leave_emails`.

Delivery never raises into the request: a mail problem must not fail the
leave application itself.
"""

from django.conf import settings
from django.utils import timezone

from apps.leaves.models import EmailDispatchLog


HR_INBOX = getattr(settings, "LEAVES_HR_INBOX", "leave@jdinstitute.edu.in")

# Trigger keys registered in settings.EMAIL_SENDER_DOMAIN_POLICY. These
# are also listed in SMTP_INTERNAL_TEMPLATE_KEYS — internal HR mail is
# composed here and sent over SMTP, never through the MSG91 registry.
TPL_LEAVE_APPLIED = "leaves.application_employee.email"
TPL_LEAVE_DECISION = "leaves.application_status_employee.email"
TPL_COMPOFF_APPLIED = "leaves.compoff_application_employee.email"
TPL_COMPOFF_DECISION = "leaves.compoff_status_employee.email"


def _split_emails(s: str | None) -> list[str]:
    if not s:
        return []
    return [e.strip() for e in s.split(",") if e.strip()]


def _transport_for(template: str) -> tuple[dict | None, str]:
    """Resolve (smtp_config, from_email) for a leave trigger.

    `smtp_config` is a dedicated per-domain connection dict, or None to
    use the project's default backend. `from_email` is "" when the
    resolved domain isn't a configured live sender, which tells
    `send_email` to keep the settings-derived default From.
    """
    from apps.notifications.sender import resolve_sender, transport_for

    sender = resolve_sender(template)
    if sender is None:
        return None, ""
    kind, smtp_cfg = transport_for(sender.domain)
    # These triggers have no MSG91 template (they're SMTP-internal), so a
    # "msg91" verdict would have nothing to send — use default SMTP.
    if kind != "smtp":
        smtp_cfg = None
    return smtp_cfg, (sender.from_email if sender.is_live else "")


def deliver(log: EmailDispatchLog) -> EmailDispatchLog:
    """Attempt delivery of one logged email and record the outcome."""
    if not getattr(settings, "EMAIL_SMTP_OUTBOUND_ENABLED", True):
        # No SMTP egress on this host — leave the row queued for replay.
        return log

    from apps.notifications.email import send_email

    smtp_cfg, from_email = _transport_for(log.template)
    try:
        ok, detail = send_email(
            recipient=log.to, cc=log.cc,
            subject=log.subject, body=log.body,
            smtp=smtp_cfg, from_email=from_email,
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
    cc_list = _split_emails(application.cc_emails) + [HR_INBOX]
    body = (
        f"{emp.full_name} ({emp.emp_code}) has applied for "
        f"{application.leave_type.name}.\n"
        f"Dates: {application.from_date} → {application.to_date}\n"
        f"Days: {application.count} (session {application.from_session})\n"
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
    rm = emp.reporting_manager_1
    to = (rm.email_primary if rm else HR_INBOX)
    send_email_now(
        template=TPL_COMPOFF_APPLIED,
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
    send_email_now(
        template=TPL_COMPOFF_DECISION,
        to=emp.email_primary,
        subject=f"Comp-off {decision} — {compoff.worked_date}",
        body=(
            f"Your comp-off for {compoff.worked_date} has been {decision}.\n"
            f"Remarks: {compoff.approver_remarks or '(none)'}"
        ),
        compoff=compoff,
    )
