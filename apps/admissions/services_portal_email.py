"""Email body + dispatcher for "Send portal credentials".

Splits the templating off the view so the wording lives in one place
and the view stays focused on auth + the side-effect chain.
"""

from __future__ import annotations

from apps.notifications.email import send_email

from .models import Student


def _build_body(*, student: Student, creds: dict) -> str:
    institute = getattr(student.institute, "name", "the institute")
    return (
        f"Hi {student.student_name},\n\n"
        f"Welcome to {institute}. Your student portal account is ready.\n\n"
        "You can log in using the credentials below:\n\n"
        f"  Login email : {creds['email']}\n"
        f"  Username    : {creds['username']}\n"
        f"  Password    : {creds['temporary_password']}\n\n"
        "Please change your password after the first login.\n\n"
        "If you didn't request this, contact your admissions office.\n\n"
        "— JD Admissions"
    )


def send_portal_credentials_email(
    *, student: Student, creds: dict,
) -> tuple[bool, str]:
    recipient = (student.student_email or "").strip()
    if not recipient:
        return False, "Student has no personal email on file."
    subject = "Your student portal login"
    return send_email(
        recipient=recipient,
        subject=subject,
        body=_build_body(student=student, creds=creds),
    )
