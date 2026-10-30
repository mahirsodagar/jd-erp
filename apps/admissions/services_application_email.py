"""Acknowledge a submitted application form by email.

Fires once, on the student's first submit of the public self-fill form
(`PublicApplicationView.post`). The message carries the application
form PDF (`services_application_pdf.render_application_pdf`) and goes
to the student with the campus acknowledgement inbox in CC, so both
hold the same copy. The campus inbox comes from
`APPLICATION_ACK_CAMPUS_INBOXES` (keyed on `Campus.code`); a campus
with no inbox configured still gets the student copy.

Best-effort: a mail problem is logged in `NotificationDispatchLog` and
never fails the submission itself.
"""

import logging

from django.conf import settings

from apps.notifications.models import NotificationDispatchLog, NotificationTemplate

from .services_application_pdf import render_application_pdf

logger = logging.getLogger(__name__)

TEMPLATE_KEY = "admissions.form_submitted.email"


def campus_inbox_for(campus) -> str:
    """The acknowledgement mailbox for this campus, or "" when none is set."""
    inboxes = getattr(settings, "APPLICATION_ACK_CAMPUS_INBOXES", {}) or {}
    code = (getattr(campus, "code", "") or "").strip().upper()
    return (inboxes.get(code) or "").strip()


def _transport(degree_type: str):
    """(smtp_config, from_email) for the trigger. Course-aware policy;
    MSG91 cannot carry a PDF, so a MSG91 verdict falls back to SMTP."""
    from apps.notifications.sender import resolve_sender, transport_for

    sender = resolve_sender(TEMPLATE_KEY, degree_type=degree_type)
    if sender is None:
        return None, ""
    kind, smtp_cfg = transport_for(sender.domain)
    if kind != "smtp":
        smtp_cfg = None
    return smtp_cfg, (sender.from_email if sender.is_live else "")


def _compose(student) -> tuple[str, str]:
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
        f"Our admissions team will review it and contact you about the "
        f"next steps.\n\n"
        f"Regards,\nAdmissions Office\n{inst_name}"
    )
    return subject, body


def send_application_acknowledgement(student) -> NotificationDispatchLog | None:
    """Email the application form PDF to the student and the campus
    inbox. Returns the dispatch log row, or None when there was nobody
    to send to. Never raises."""
    try:
        student_email = (student.student_email or "").strip()
        campus_email = campus_inbox_for(student.campus)
        operations = (getattr(settings, "OPERATIONS_INBOX", "") or "").strip()

        to = student_email or campus_email
        cc = [e for e in (campus_email, operations)
              if e and e.lower() != to.lower()]
        if not to:
            logger.info("Application %s: no recipient (student has no email, "
                        "campus %s has no inbox).", student.application_form_id,
                        getattr(student.campus, "code", ""))
            return None

        subject, body = _compose(student)
        log = NotificationDispatchLog.objects.create(
            channel=NotificationTemplate.Channel.EMAIL,
            template_key=TEMPLATE_KEY, recipient=to, cc=", ".join(cc),
            subject=subject, body=body, related_object=student,
        )

        if not getattr(settings, "EMAIL_SMTP_OUTBOUND_ENABLED", True):
            log.error = "SMTP outbound disabled on this host."
            log.save(update_fields=["error"])
            return log

        from django.utils import timezone

        from apps.notifications.email import send_email

        pdf = render_application_pdf(student)
        smtp_cfg, from_email = _transport(
            getattr(student.program, "degree_type", "") or "",
        )
        ok, detail = send_email(
            recipient=to, cc=", ".join(cc), subject=subject, body=body,
            attachments=[(f"Application-{student.application_form_id}.pdf",
                          pdf, "application/pdf")],
            smtp=smtp_cfg, from_email=from_email,
        )
        log.status = (NotificationDispatchLog.Status.SENT if ok
                      else NotificationDispatchLog.Status.FAILED)
        log.sent_at = timezone.now() if ok else None
        log.error = "" if ok else detail
        log.save(update_fields=["status", "sent_at", "error"])
        if not ok:
            logger.warning("Application %s acknowledgement to %s failed: %s",
                           student.application_form_id, to, detail)
        return log
    except Exception:  # noqa: BLE001 — never break the submission
        logger.exception("Application acknowledgement failed for student id=%s",
                         getattr(student, "pk", None))
        return None
