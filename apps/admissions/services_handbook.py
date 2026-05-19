"""Email body + dispatcher for "Send Handbook".

Plain-text for now. When you want to attach the actual handbook PDF,
upload it on the Institute master (a future `handbook_pdf` FileField)
and read it here via `attachments=[(name, content, "application/pdf")]`.
"""

from __future__ import annotations

from apps.notifications.email import send_email

from .models import Student


def _build_body(*, student: Student) -> str:
    institute = getattr(student.institute, "name", "the institute")
    program = getattr(student.program, "name", "your program")
    return (
        f"Hi {student.student_name},\n\n"
        f"Congratulations on joining {program} at {institute}!\n\n"
        "Please find your student handbook attached / linked below. "
        "It covers attendance norms, the assessment scheme, the dress "
        "code, library timings, and the grievance-redressal process. "
        "Read it carefully before the orientation.\n\n"
        "If you have any questions, drop a note to the admissions "
        "office — we're happy to help.\n\n"
        "— JD Admissions"
    )


def send_handbook_email(*, student: Student) -> tuple[bool, str]:
    recipient = (student.student_email or "").strip()
    if not recipient:
        return False, "Student has no personal email on file."
    subject = "Your student handbook"
    return send_email(
        recipient=recipient,
        subject=subject,
        body=_build_body(student=student),
    )
