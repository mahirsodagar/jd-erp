"""Relieving workflow emails — ported from legacy `hr/hrsave.php`.

Legacy sent four mails:

  apply      → approver 1, cc approvers 2–4        (employee_relieving_application)
  reject     → approver 1, cc approvers 2–4        (employee_relieving_application_rejected)
  completion → employee's PERSONAL mail, cc approvers + institutional
               mail, relieving letter PDF attached  (relieving_letter_employee)
  experience → employee's personal mail, cc final approver,
               experience letter PDF attached       (experience_letter_employee)

Legacy hard-coded the four approver addresses; here the chain is the
per-application snapshot in `RelievingApproval` (reporting managers 1–4).
Legacy's personal / institutional mail (`emp_email2` / `emp_email1`) map
to `Employee.email_alternate` / `email_primary`. The letter goes to the
personal address because the institutional mailbox is typically closed
once the employee is relieved.

Every send is recorded as a `NotificationDispatchLog` row (linked to the
application) with the transport's verdict. Delivery never raises — a mail
failure must not undo an approval or a finalization.
"""

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .letters import render_experience_letter, render_relieving_letter
from .models import RelievingApproval


# Keys registered in settings.EMAIL_SENDER_DOMAIN_POLICY (HR domain) and
# SMTP_INTERNAL_TEMPLATE_KEYS.
TPL_APPLICATION = "hr.relieving.application.email"
TPL_REJECTED = "hr.relieving.application_rejected.email"
TPL_RELIEVING_LETTER = "hr.relieving.letter.email"
TPL_EXPERIENCE_LETTER = "hr.relieving.experience_letter.email"

_FOOTER = "\n\nNote: This is an auto-generated mail. Please do not reply."


# --- Plumbing ------------------------------------------------------

def _approver_emails(application) -> list[str]:
    """Approver addresses in level order, skipped / unset levels dropped."""
    rows = (application.approvals
            .exclude(status=RelievingApproval.Status.SKIPPED)
            .select_related("approver")
            .order_by("level"))
    out: list[str] = []
    for row in rows:
        addr = (row.approver.email_primary if row.approver else "") or ""
        if addr and addr.lower() not in (a.lower() for a in out):
            out.append(addr)
    return out


def _join(*groups) -> str:
    """Comma-joined, de-duplicated (case-insensitive), blanks dropped."""
    seen, out = set(), []
    for group in groups:
        for addr in ([group] if isinstance(group, str) else group):
            addr = (addr or "").strip()
            if addr and addr.lower() not in seen:
                seen.add(addr.lower())
                out.append(addr)
    return ", ".join(out)


def _send(*, template: str, application, to: str, cc: str, subject: str,
          body: str, attachments=()) -> NotificationDispatchLog:
    from apps.notifications.email import send_email
    from apps.notifications.sender import resolve_sender, transport_for

    # Don't CC the primary recipient.
    cc = _join([c for c in cc.split(",") if c.strip().lower() != to.lower()])

    log = NotificationDispatchLog.objects.create(
        channel=NotificationTemplate.Channel.EMAIL,
        template_key=template, recipient=to, cc=cc,
        subject=subject, body=body,
        status=NotificationDispatchLog.Status.QUEUED,
        content_type=ContentType.objects.get_for_model(application),
        object_id=str(application.pk),
    )

    smtp_cfg, from_email = None, ""
    sender = resolve_sender(template)
    if sender is not None:
        kind, cfg = transport_for(sender.domain)
        smtp_cfg = cfg if kind == "smtp" else None
        from_email = sender.from_email if sender.is_live else ""

    try:
        ok, detail = send_email(
            recipient=to, cc=cc, subject=subject, body=body,
            attachments=attachments, smtp=smtp_cfg, from_email=from_email,
        )
    except Exception as e:  # defensive — send_email already traps SMTP errors
        ok, detail = False, f"{type(e).__name__}: {e}"

    log.status = (NotificationDispatchLog.Status.SENT if ok
                  else NotificationDispatchLog.Status.FAILED)
    log.sent_at = timezone.now() if ok else None
    log.error = "" if ok else detail
    log.save(update_fields=["status", "sent_at", "error"])
    return log


def _safe_send(**kw) -> NotificationDispatchLog | None:
    """Letter rendering or logging can fail too — never let that escape."""
    try:
        return _send(**kw)
    except Exception:  # pragma: no cover — defensive
        import logging
        logging.getLogger(__name__).exception(
            "Relieving email %s failed for application %s",
            kw.get("template"), getattr(kw.get("application"), "pk", None),
        )
        return None


# --- Events --------------------------------------------------------

def notify_submitted(application) -> None:
    emp = application.employee
    approvers = _approver_emails(application)
    if not approvers:
        return
    doj = emp.date_of_joining
    _safe_send(
        template=TPL_APPLICATION, application=application,
        to=approvers[0], cc=_join(approvers[1:]),
        subject=f"Employee Relieving Application — {emp.full_name} ({emp.emp_code})",
        body=(
            "Employee submitted a relieving application.\n\n"
            f"Employee Name: {emp.full_name} [{emp.emp_code}]\n"
            f"Date of Join: {f'{doj:%d %b %Y}' if doj else '—'}\n"
            f"Last Working Date: {application.last_working_date_requested:%d %b %Y}\n"
            f"Reason: {application.reason}"
            + _FOOTER
        ),
    )


def notify_rejected(application) -> None:
    emp = application.employee
    approvers = _approver_emails(application)
    if not approvers:
        return
    _safe_send(
        template=TPL_REJECTED, application=application,
        to=approvers[0], cc=_join(approvers[1:]),
        subject=f"Employee Relieving Application Rejected — {emp.full_name}",
        body=(
            "Employee relieving application has been rejected.\n\n"
            f"Employee Name: {emp.full_name} [{emp.emp_code}]\n"
            f"Rejected at level: {application.rejected_at_level}\n"
            f"Reason for Rejection: {application.rejection_reason or '(none)'}"
            + _FOOTER
        ),
    )


def notify_completed(application) -> None:
    """Email the relieving letter, then the experience letter, to the
    employee. Legacy sent the experience letter from a separate HR
    button; here both letters are issued at finalize, so both go out."""
    emp = application.employee
    personal = emp.email_alternate or emp.email_primary
    if not personal:
        return
    approvers = _approver_emails(application)
    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)
    inst_name = emp.institute.name

    _safe_send(
        template=TPL_RELIEVING_LETTER, application=application,
        to=personal, cc=_join(approvers, emp.email_primary),
        subject=f"Relieving Letter — {emp.full_name}",
        body=(
            f"Dear {emp.full_name},\n\n"
            f"Please find attached your relieving letter from {inst_name}. "
            f"Your last working date is {last_day:%d %b %Y}.\n\n"
            "We wish you the very best in your future endeavours.\n\n"
            "Regards,\nHR" + _FOOTER
        ),
        attachments=[(
            f"{application.relieving_letter_no}.pdf",
            render_relieving_letter(application), "application/pdf",
        )],
    )

    _safe_send(
        template=TPL_EXPERIENCE_LETTER, application=application,
        to=personal, cc=_join(approvers[-1:]),
        subject=f"Experience Letter — {emp.full_name}",
        body=(
            f"Dear {emp.full_name},\n\n"
            f"Please find attached your experience letter from {inst_name}.\n\n"
            "Regards,\nHR" + _FOOTER
        ),
        attachments=[(
            f"{application.experience_letter_no}.pdf",
            render_experience_letter(application), "application/pdf",
        )],
    )
