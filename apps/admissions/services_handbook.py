"""Email body + dispatcher for "Send Handbook".

The handbook is institute-specific (JDIFT diploma rules differ from the
JDSD degree rules on fees, attendance relaxations, late-fee interest,
ID-card replacement cost...), so the PDF lives on the Institute master
(`Institute.handbook_pdf`). `seed_institutes` bundles the 2026 editions;
finance/academics can replace them from Master -> Institutes without a
deploy.

With no PDF on file the send is refused rather than mailing a body that
promises an attachment it doesn't carry.
"""

from __future__ import annotations

import re

from apps.notifications.email import send_email

from .models import Student


def _attachment_name(institute) -> str:
    code = re.sub(r"[^A-Za-z0-9]+", "", getattr(institute, "code", "") or "")
    return f"{code or 'JD'}_Student_Handbook.pdf"


def _build_body(*, student: Student) -> str:
    institute = getattr(student.institute, "name", "the institute")
    program = getattr(student.program, "name", "your program")
    return (
        f"Dear {student.student_name},\n\n"
        f"Welcome to {program} at {institute}!\n\n"
        "Please find the Student Handbook attached. It is the official "
        "manual for your time with us and covers, among other things:\n"
        "  - the attendance policy (85% minimum per module) and leave rules\n"
        "  - assessment, submission deadlines and progression\n"
        "  - fee payment modes and deadlines\n"
        "  - the code of conduct, anti-ragging and anti-harassment "
        "policies\n"
        "  - support services: counselling, library, Wi-Fi, medical help\n"
        "  - the appeals and complaints process\n\n"
        "Read it carefully before orientation, and share it with your "
        "parents/guardians - the closing pages include the undertakings "
        "both of you are required to sign and submit.\n\n"
        "If you have any questions, reach out to your Class Mentor or the "
        "admissions office - we're happy to help.\n\n"
        f"- {institute}"
    )


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

    institute_name = getattr(institute, "name", "JD")
    return send_email(
        recipient=recipient,
        subject=f"Your Student Handbook - {institute_name}",
        body=_build_body(student=student),
        attachments=[(_attachment_name(institute), content, "application/pdf")],
    )
