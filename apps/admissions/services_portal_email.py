"""Dispatcher for "Send portal credentials".

Routes through the notifications layer (`queue_notification`): system
e-mail `student.portal_credentials.email` (editable under Communication
→ System Emails), ZeptoMail From no-reply@dkul.in, default Reply-To. A
NotificationDispatchLog row is written for audit.
"""

from __future__ import annotations

from django.conf import settings

from apps.notifications.context import student_vars
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.services import queue_notification

from .models import Student


def send_portal_credentials_email(
    *, student: Student, creds: dict,
) -> tuple[bool, str]:
    recipient = (student.student_email or "").strip()
    if not recipient:
        return False, "Student has no personal email on file."

    login_url = getattr(
        settings, "STUDENT_PORTAL_LOGIN_URL",
        "https://jdsd.netlify.app/#/portal/login/",
    )

    log = queue_notification(
        template_key="student.portal_credentials.email",
        recipient=recipient,
        context={
            **student_vars(student),
            "Portal_Email": creds["email"],
            "Username": creds["username"],
            "Password": creds["temporary_password"],
            "Login_Url": login_url,
        },
        related=student,
    )
    sent = NotificationDispatchLog.Status.SENT
    ok = getattr(log, "status", "") == sent
    return ok, "" if ok else (getattr(log, "error", "") or "")
