"""Dispatcher for "Send portal credentials".

Routes through the notifications layer (`queue_notification`) so the
email goes via MSG91 when `MSG91_EMAIL_TEMPLATES["student.portal_credentials.email"]`
is registered, and falls back to plain SMTP otherwise. Either way a
NotificationDispatchLog row is written for audit.
"""

from __future__ import annotations

from django.conf import settings

from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import queue_notification

from .models import Student


def send_portal_credentials_email(
    *, student: Student, creds: dict,
) -> tuple[bool, str]:
    recipient = (student.student_email or "").strip()
    if not recipient:
        return False, "Student has no personal email on file."

    institute = getattr(student.institute, "name", "the institute")
    login_url = getattr(
        settings, "STUDENT_PORTAL_LOGIN_URL",
        "https://jdsd.netlify.app/#/portal/login/",
    )

    log = queue_notification(
        template_key="student.portal_credentials.email",
        recipient=recipient,
        context={
            "name": student.student_name,
            "email": creds["email"],
            "username": creds["username"],
            "password": creds["temporary_password"],
            "institute": institute,
            "login_url": login_url,
        },
        related=student,
    )
    sent = NotificationDispatchLog.Status.SENT
    ok = getattr(log, "status", "") == sent
    return ok, "" if ok else (getattr(log, "error", "") or "")
