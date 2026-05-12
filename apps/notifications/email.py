"""Email dispatcher — wraps Django's built-in `django.core.mail`.

Email backend selection lives in settings (`EMAIL_BACKEND` etc.). On
PythonAnywhere free we recommend `django.core.mail.backends.console`
for dev and a real SMTP backend in prod.
"""

from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMessage


def send_email(
    *,
    recipient: str,
    cc: str = "",
    subject: str,
    body: str,
    is_html: bool = False,
) -> tuple[bool, str]:
    if not recipient:
        return False, "No recipient address."

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[recipient],
        cc=[c.strip() for c in cc.split(",") if c.strip()],
    )
    if is_html:
        msg.content_subtype = "html"

    try:
        sent = msg.send(fail_silently=False)
        return bool(sent), f"sent={sent}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
