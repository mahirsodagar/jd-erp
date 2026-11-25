"""Dispatcher for "Send Handbook".

The handbook is institute-specific (JDIFT diploma rules differ from the
JDSD degree rules on fees, attendance relaxations, late-fee interest,
ID-card replacement cost...), so the PDF lives on the Institute master
(`Institute.handbook_pdf`). `seed_institutes` bundles the 2026 editions;
finance/academics can replace them from Master -> Institutes without a
deploy.

With no PDF on file the send is refused rather than mailing a body that
promises an attachment it doesn't carry. The wording is the system
e-mail `admissions.handbook.email` (Communication → System Emails).
"""

from __future__ import annotations

import re

from apps.notifications.context import student_vars
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import send_system_email

from .models import Student

TEMPLATE_KEY = "admissions.handbook.email"


def _attachment_name(institute) -> str:
    code = re.sub(r"[^A-Za-z0-9]+", "", getattr(institute, "code", "") or "")
    return f"{code or 'JD'}_Student_Handbook.pdf"


def send_handbook_email(*, student: Student) -> tuple[bool, str]:
    recipient = (student.student_email or "").strip()
    if not recipient:
        return False, "Student has no personal email on file."

    institute = student.institute
    pdf = getattr(institute, "handbook_pdf", None)
    if not pdf:
        return False, (
            f"No student handbook uploaded for "
            f"{getattr(institute, 'name', 'this institute')}. Upload the "
            "PDF under Master -> Institutes first."
        )
    try:
        with pdf.open("rb") as fh:
            content = fh.read()
    except (OSError, ValueError) as e:
        return False, f"Could not read the handbook PDF: {e}"

    log = send_system_email(
        TEMPLATE_KEY, recipient=recipient, context=student_vars(student),
        attachments=[(_attachment_name(institute), content, "application/pdf")],
        related=student, institute=institute,
    )
    ok = getattr(log, "status", "") == NotificationDispatchLog.Status.SENT
    return ok, "" if ok else (getattr(log, "error", "") or "Email delivery failed.")
