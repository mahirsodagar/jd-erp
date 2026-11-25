"""Acknowledge a submitted application form by email.

Fires once, on the student's first submit of the public self-fill form
(`PublicApplicationView.post`), as two mails — both system e-mails whose
wording is editable under Communication → System Emails:

* Student copy — `admissions.application_submitted.email` (no PDF, no
  pay links; the student sees the "Pay fees" page right after
  submitting anyway). Replies go to the campus admissions inbox.
* Office copy — `admissions.form_submitted.email` with the application
  form PDF (`services_application_pdf.render_application_pdf`) and fee
  lines, To the campus acknowledgement inbox
  (`APPLICATION_ACK_CAMPUS_INBOXES`, keyed on `Campus.code`), else
  `OPERATIONS_INBOX`, else the academic counsellor assigned to the
  originating lead. CC `OPERATIONS_INBOX` and that counsellor (client
  decision 2026-11-20). Skipped only when none of the three exists.

Best-effort: a mail problem is logged in `NotificationDispatchLog` and
never fails the submission itself.
"""

import logging
from html import escape

from django.conf import settings

from apps.notifications.context import student_vars
from apps.notifications.services import send_system_email

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
    (see `payments.applicant_fees.fee_page_for`), as HTML for the
    `{{Fee_Lines}}` variable. Paid rows and rows collected at the
    college say nothing."""
    from apps.payments.applicant_fees import due_rows

    out = []
    for row in due_rows(fee_page):
        amount = row.get("amount") or ""
        try:
            amount = f"{float(amount):,.2f}"
        except (TypeError, ValueError):
            pass
        url = escape(str(row.get("pay_url", "") or ""))
        out.append(
            f"<p>{escape(str(row.get('label', 'Fee')))}: Rs. {escape(str(amount))}<br>"
            f"You can pay it online whenever convenient using this link:<br>"
            f"<a href=\"{url}\">{url}</a></p>"
        )
    return "".join(out)


def _send_student_copy(student):
    """Student copy of the acknowledgement. Never raises."""
    to = (student.student_email or "").strip()
    if not to:
        return None
    try:
        from django.utils import timezone

        return send_system_email(
            STUDENT_TEMPLATE_KEY, recipient=to, related=student,
            context={
                **student_vars(student),
                "Submission_Date": timezone.localdate().strftime("%d-%m-%Y"),
            },
        )
    except Exception:  # noqa: BLE001 — never break the submission
        logger.exception("Application %s: student ack failed",
                         getattr(student, "application_form_id", ""))
        return None


def counsellor_email_for(student) -> str:
    """Address of the academic counsellor assigned to the lead this
    student was promoted from (`Lead.assign_to` is a User), or ""."""
    lead = getattr(student, "lead_origin", None)
    counsellor = getattr(lead, "assign_to", None) if lead else None
    return (getattr(counsellor, "email", "") or "").strip()


def _send_office_copy(student, fee_page):
    """Mail with the form PDF to the campus inbox, CC operations and the
    lead's academic counsellor. With no campus inbox the mail goes To
    operations, and failing that To the counsellor."""
    campus_email = campus_inbox_for(student.campus)
    operations = (getattr(settings, "OPERATIONS_INBOX", "") or "").strip()
    counsellor = counsellor_email_for(student)
    to = campus_email or operations or counsellor
    cc = []
    for addr in (operations, counsellor):
        if addr and addr.lower() != to.lower() and addr.lower() not in (
            c.lower() for c in cc
        ):
            cc.append(addr)
    if not to:
        logger.info("Application %s: no office copy (campus %s has no inbox, "
                    "no OPERATIONS_INBOX, no counsellor on the lead).",
                    student.application_form_id,
                    getattr(student.campus, "code", ""))
        return None

    pdf = render_application_pdf(student)
    log = send_system_email(
        TEMPLATE_KEY, recipient=to, cc=", ".join(cc), related=student,
        context={**student_vars(student), "Fee_Lines": _fee_lines(fee_page)},
        attachments=[(f"Application-{student.application_form_id}.pdf",
                      pdf, "application/pdf")],
    )
    if getattr(log, "status", "") != "SENT":
        logger.warning("Application %s office copy to %s failed: %s",
                       student.application_form_id, to,
                       getattr(log, "error", ""))
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
