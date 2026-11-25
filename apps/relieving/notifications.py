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

from apps.notifications.models import NotificationDispatchLog

from .letters import render_experience_letter, render_relieving_letter
from .models import RelievingApproval


# System e-mail keys (apps.notifications.registry; wording editable under
# Communication → System Emails) also registered in
# settings.EMAIL_REPLY_TO_POLICY. Mail leaves From no-reply@dkul.in;
# replies go to the first approver in the chain (the manager handling
# the application), else the Principal's inbox.
TPL_APPLICATION = "hr.relieving.application.email"
TPL_REJECTED = "hr.relieving.application_rejected.email"
TPL_APPROVED = "hr.relieving.application_approved.email"  # PART_TIME completion
TPL_RELIEVING_LETTER = "hr.relieving.letter.email"
TPL_EXPERIENCE_LETTER = "hr.relieving.experience_letter.email"


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


def _send(*, template: str, application, to: str, cc: str, context: dict,
          attachments=()) -> NotificationDispatchLog:
    """One relieving mail from its system e-mail template (Communication
    → System Emails), logged in NotificationDispatchLog."""
    from apps.notifications.context import employee_vars
    from apps.notifications.services import send_system_email

    # Don't CC the primary recipient.
    cc = _join([c for c in cc.split(",") if c.strip().lower() != to.lower()])

    # Reply-To = the approver handling this application (L1), unless
    # the mail is addressed to them — then the next in the chain. With
    # no approver left, the policy falls back to the Principal of the
    # employee's campus (token PRINCIPAL reads campus_code).
    approvers = _approver_emails(application)
    handler = next((a for a in approvers if a.lower() != to.lower()), "")

    emp = getattr(application, "employee", None)
    return send_system_email(
        template, recipient=to, cc=cc, related=application,
        context={**employee_vars(emp), **context, "reply_to": handler},
        attachments=attachments,
    )


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
    noun, caption = _kind(application)
    _safe_send(
        template=TPL_APPLICATION, application=application,
        to=approvers[0], cc=_join(approvers[1:]),
        context={
            "Application_Type": noun,
            "Last_Working_Date": f"{application.last_working_date_requested:%d %b %Y}",
            "Last_Working_Date_Caption": caption,
            "Reason": application.reason or "",
        },
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
        context={
            "Application_Type": noun,
            "Rejected_Level": str(application.rejected_at_level or ""),
            "Rejection_Reason": application.rejection_reason or "(none)",
        },
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
            context={"Last_Working_Date": f"{last_day:%d %b %Y}"},
        )
        return

    personal = emp.email_alternate or emp.email_primary
    if not personal:
        return

    _safe_send(
        template=TPL_RELIEVING_LETTER, application=application,
        to=personal, cc=_join(approvers, emp.email_primary),
        context={
            "Institute_Name": inst_name,
            "Last_Working_Date": f"{last_day:%d %b %Y}",
            "Letter_No": str(application.relieving_letter_no or ""),
        },
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
        context={
            "Institute_Name": inst_name,
            "Letter_No": str(application.experience_letter_no or ""),
        },
        attachments=[(
            f"{application.experience_letter_no}.pdf",
            render_experience_letter(application), "application/pdf",
        )],
    )
