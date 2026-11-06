"""Relieving workflow emails — ported from legacy `hr/hrsave.php`.

Legacy sent four mails:

  apply      → approver 1, cc approvers 2–4        (employee_relieving_application)
  reject     → approver 1, cc approvers 2–4        (employee_relieving_application_rejected)
  completion → employee's PERSONAL mail, cc approvers + institutional
               mail, relieving letter PDF attached  (relieving_letter_employee)
  experience → HR button, sent separately: employee's personal mail,
               cc final approver, experience letter PDF attached
                                                    (experience_letter_employee)

Legacy hard-coded the four approver addresses; here the chain is the
per-application snapshot in `RelievingApproval`, taken from the
institute's Relieving Managers master (L1–L4). A PART_TIME application
("Full time to Part time") uses the same apply / reject mails and, on
completion, a plain approval mail instead of the letter.
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
TPL_APPROVED = "hr.relieving.application_approved.email"  # PART_TIME completion
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

def _kind(application) -> tuple[str, str]:
    """(subject noun, last-day caption) per application type."""
    if application.is_relieving:
        return "Relieving", "Last Working Date"
    return "Full-time to Part-time", "Last Working Date as Full-time"


def notify_submitted(application) -> None:
    emp = application.employee
    approvers = _approver_emails(application)
    if not approvers:
        return
    doj = emp.date_of_joining
    noun, caption = _kind(application)
    _safe_send(
        template=TPL_APPLICATION, application=application,
        to=approvers[0], cc=_join(approvers[1:]),
        subject=f"Employee {noun} Application — {emp.full_name} ({emp.emp_code})",
        body=(
            f"Employee submitted a {noun.lower()} application.\n\n"
            f"Employee Name: {emp.full_name} [{emp.emp_code}]\n"
            f"Date of Join: {f'{doj:%d %b %Y}' if doj else '—'}\n"
            f"{caption}: {application.last_working_date_requested:%d %b %Y}\n"
            f"Reason: {application.reason}"
            + _FOOTER
        ),
    )


def notify_rejected(application) -> None:
    emp = application.employee
    approvers = _approver_emails(application)
    if not approvers:
        return
    noun, _ = _kind(application)
    _safe_send(
        template=TPL_REJECTED, application=application,
        to=approvers[0], cc=_join(approvers[1:]),
        subject=f"Employee {noun} Application Rejected — {emp.full_name}",
        body=(
            f"Employee {noun.lower()} application has been rejected.\n\n"
            f"Employee Name: {emp.full_name} [{emp.emp_code}]\n"
            f"Rejected at level: {application.rejected_at_level}\n"
            f"Reason for Rejection: {application.rejection_reason or '(none)'}"
            + _FOOTER
        ),
    )


def notify_completed(application) -> None:
    """RELIEVING: email the relieving letter to the employee. The
    experience letter is not sent here — HR sends it from its own button
    (legacy parity), see `send_experience_letter`. PART_TIME: a plain
    approval mail to the employee, cc the four approvers, so HR knows to
    update the employee record."""
    emp = application.employee
    approvers = _approver_emails(application)
    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)
    inst_name = emp.institute.name

    if not application.is_relieving:
        to = emp.email_primary or emp.email_alternate
        if not to:
            return
        _safe_send(
            template=TPL_APPROVED, application=application,
            to=to, cc=_join(approvers),
            subject=f"Full-time to Part-time Approved — {emp.full_name} ({emp.emp_code})",
            body=(
                f"Dear {emp.full_name},\n\n"
                "Your application to move from full-time to part-time has "
                "been approved by all four levels. Your last working date "
                f"as a full-time employee is {last_day:%d %b %Y}.\n\n"
                "HR will update your employment record.\n\n"
                "Regards,\nHR" + _FOOTER
            ),
        )
        return

    personal = emp.email_alternate or emp.email_primary
    if not personal:
        return

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


def send_experience_letter(application) -> NotificationDispatchLog | None:
    """Email the experience letter to the employee's personal mail, cc the
    final approver. Returns the dispatch log (None when the employee has
    no address or the send blew up) so the caller can report the outcome."""
    emp = application.employee
    personal = emp.email_alternate or emp.email_primary
    if not personal:
        return None
    approvers = _approver_emails(application)
    inst_name = emp.institute.name

    return _safe_send(
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
