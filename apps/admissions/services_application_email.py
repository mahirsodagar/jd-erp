"""Acknowledge a submitted application form by email.

Fires once, on the student's first submit of the public self-fill form
(`PublicApplicationView.post`), as two mails:

* Student copy — template row `admissions.application_submitted.email`
  via `queue_notification` (no PDF, no pay links; the student sees the
  "Pay fees" page right after submitting anyway). Replies go to the
  campus admissions inbox.
* Office copy — the mail with the application form PDF
  (`services_application_pdf.render_application_pdf`) and fee lines, To
  the campus acknowledgement inbox (`APPLICATION_ACK_CAMPUS_INBOXES`,
  keyed on `Campus.code`), CC `OPERATIONS_INBOX`. Skipped when neither
  inbox is configured.

Best-effort: a mail problem is logged in `NotificationDispatchLog` and
never fails the submission itself.
"""

import logging

from django.conf import settings

from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .services_application_pdf import render_application_pdf

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "admissions.form_submitted.email"  # office copy (+ PDF)
STUDENT_TEMPLATE_KEY = "admissions.application_submitted.email"  # student copy


def campus_inbox_for(campus) -> str:
    """The acknowledgement mailbox for this campus, or "" when none is set."""
    inboxes = getattr(settings, "APPLICATION_ACK_CAMPUS_INBOXES", {}) or {}
    code = (getattr(campus, "code", "") or "").strip().upper()
    return (inboxes.get(code) or "").strip()


def _fee_lines(fee_page: dict | None) -> str:
    """One "pay online" paragraph per fee still due and payable online
    (see `payments.applicant_fees.fee_page_for`). Paid rows and rows
    collected at the college say nothing."""
    from apps.payments.applicant_fees import due_rows

    out = []
    for row in due_rows(fee_page):
        amount = row.get("amount") or ""
        try:
            amount = f"{float(amount):,.2f}"
        except (TypeError, ValueError):
            pass
        out.append(
            f"{row.get('label', 'Fee')}: Rs. {amount}\n"
            f"You can pay it online whenever convenient using this link:\n"
            f"{row.get('pay_url', '')}\n\n"
        )
    return "".join(out)


def _compose(student, fee_page: dict | None = None) -> tuple[str, str]:
    institute = getattr(student, "institute", None)
    inst_name = getattr(institute, "name", "") or "JD Institute"
    program = getattr(student.program, "name", "") or "—"
    campus = getattr(student.campus, "name", "") or "—"
    subject = (f"Application received — {student.application_form_id} "
               f"({student.student_name})")
    body = (
        f"Dear {student.student_name},\n\n"
        f"Thank you for applying to {inst_name}. We have received your "
        f"application form; a copy is attached for your records.\n\n"
        f"Application no: {student.application_form_id}\n"
        f"Program:        {program}\n"
        f"Campus:         {campus}\n\n"
        + _fee_lines(fee_page)
        + f"Our admissions team will review it and contact you about the "
        f"next steps.\n\n"
        f"Regards,\nAdmissions Office\n{inst_name}"
    )
    return subject, body


def _send_student_copy(student):
    """Student copy of the acknowledgement. Never raises."""
    to = (student.student_email or "").strip()
    if not to:
        return None
    try:
        from django.utils import timezone

        from apps.notifications.services import queue_notification

        submitted = timezone.localdate()
        return queue_notification(
            template_key=STUDENT_TEMPLATE_KEY,
            recipient=to,
            context={
                "Student_Name": student.student_name,
                "Course_Name": getattr(student.program, "name", "") or "",
                "Application_ID": student.application_form_id,
                "Submission_Date": submitted.strftime("%d-%m-%Y"),
                "campus_code": getattr(student.campus, "code", "") or "",
            },
            related=student,
        )
    except Exception:  # noqa: BLE001 — never break the submission
        logger.exception("Application %s: student ack failed",
                         getattr(student, "application_form_id", ""))
        return None


def _send_office_copy(student, fee_page):
    """Mail with the form PDF to the campus inbox (CC operations)."""
    campus_email = campus_inbox_for(student.campus)
    operations = (getattr(settings, "OPERATIONS_INBOX", "") or "").strip()
    to = campus_email or operations
    cc = [e for e in (operations,) if e and e.lower() != to.lower()]
    if not to:
        logger.info("Application %s: no office copy (campus %s has no inbox, "
                    "no OPERATIONS_INBOX).", student.application_form_id,
                    getattr(student.campus, "code", ""))
        return None

    subject, body = _compose(student, fee_page)
    log = NotificationDispatchLog.objects.create(
        channel=NotificationTemplate.Channel.EMAIL,
        template_key=TEMPLATE_KEY, recipient=to, cc=", ".join(cc),
        subject=subject, body=body, related_object=student,
    )

    from django.utils import timezone

    from apps.notifications.email import send_email
    from apps.notifications.reply_to import resolve_reply_to

    pdf = render_application_pdf(student)
    ok, detail = send_email(
        recipient=to, cc=", ".join(cc), subject=subject, body=body,
        attachments=[(f"Application-{student.application_form_id}.pdf",
                      pdf, "application/pdf")],
        reply_to=resolve_reply_to(
            TEMPLATE_KEY,
            {"campus_code": getattr(student.campus, "code", "") or ""},
        ),
    )
    log.status = (NotificationDispatchLog.Status.SENT if ok
                  else NotificationDispatchLog.Status.FAILED)
    log.sent_at = timezone.now() if ok else None
    log.error = "" if ok else detail
    log.save(update_fields=["status", "sent_at", "error"])
    if not ok:
        logger.warning("Application %s office copy to %s failed: %s",
                       student.application_form_id, to, detail)
    return log


def send_application_acknowledgement(
    student, fee_page: dict | None = None,
) -> tuple:
    """Student ack + office copy with the PDF. `fee_page` is
    the summary from `payments.applicant_fees.fee_page_for`; fees still
    due online ride along in the office copy. Returns
    (student_log, office_log) — either may be None. Never raises."""
    student_log = _send_student_copy(student)
    try:
        office_log = _send_office_copy(student, fee_page)
    except Exception:  # noqa: BLE001 — never break the submission
        logger.exception("Application office copy failed for student id=%s",
                         getattr(student, "pk", None))
        office_log = None
    return student_log, office_log
