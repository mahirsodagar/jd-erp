"""Email dispatcher — wraps Django's built-in `django.core.mail`.

Email backend selection lives in settings (`EMAIL_BACKEND` etc.). On
PythonAnywhere free we recommend `django.core.mail.backends.console`
for dev and a real SMTP backend in prod.
"""

from __future__ import annotations

from email.utils import formataddr, parseaddr
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMessage, get_connection


# Attachments arrive as (filename, bytes, content_type) tuples — same
# shape EmailMessage.attach() expects natively.
Attachment = tuple[str, bytes, str]


def _resolve_from_email(override: str = "") -> str:
    """Build the canonical From header so recipients always see a
    friendly display name, not the bare local-part of the address.

    Priority:
      0. `override` — a per-trigger From-address chosen by the sender
         router (apps.notifications.sender). If it already carries a
         display name it's used verbatim; a bare address is wrapped with
         DEFAULT_FROM_NAME. Blank `override` falls through to the
         settings-based default below.
      1. DEFAULT_FROM_EMAIL — if it already includes a display name
         (e.g. `"JD Communications <admin.a@jdinstitute.edu.in>"`),
         use it verbatim.
      2. DEFAULT_FROM_EMAIL is just a bare address → wrap it with
         DEFAULT_FROM_NAME (defaults to "JD Communications").
      3. Otherwise fall back to EMAIL_HOST_USER (Workspace mailbox we
         authenticate with) wrapped with DEFAULT_FROM_NAME.
      4. If both are empty, return "" — the caller surfaces a clean
         error rather than letting Django raise `ValueError("Invalid
         address \"\"")` deep inside the SMTP code path.
    """
    display_name = (
        getattr(settings, "DEFAULT_FROM_NAME", "") or "JD Communications"
    ).strip()

    override = (override or "").strip()
    if override:
        name, addr = parseaddr(override)
        if name:
            return override
        if addr:
            return formataddr((display_name, addr))

    candidate = (getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip()
    if candidate:
        name, addr = parseaddr(candidate)
        if name:
            # Already has a display name — keep it intact.
            return candidate
        if addr:
            # Bare address → wrap with our default display name.
            return formataddr((display_name, addr))

    fallback = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    if fallback:
        return formataddr((display_name, fallback))

    return ""


def send_email(
    *,
    recipient: str,
    cc: str = "",
    subject: str,
    body: str,
    is_html: bool = False,
    attachments: Iterable[Attachment] | None = None,
    from_email: str = "",
    smtp: dict | None = None,
) -> tuple[bool, str]:
    if not recipient:
        return False, "No recipient address."

    # A dedicated per-domain SMTP server (e.g. jdindia.com) supplies its
    # own connection + From-address; otherwise we use the project's
    # default backend and the settings-derived From.
    connection = None
    if smtp:
        from_email = _resolve_from_email(from_email or smtp.get("from_email", ""))
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=smtp.get("host"),
            port=smtp.get("port"),
            username=smtp.get("username"),
            password=smtp.get("password"),
            use_tls=smtp.get("use_tls", True),
            use_ssl=smtp.get("use_ssl", False),
        )
    else:
        from_email = _resolve_from_email(from_email)
    if not from_email:
        return False, (
            "No sender address — set DEFAULT_FROM_EMAIL or EMAIL_HOST_USER "
            "in your environment."
        )

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email,
        to=[recipient],
        cc=[c.strip() for c in cc.split(",") if c.strip()],
        connection=connection,
    )
    if is_html:
        msg.content_subtype = "html"

    for att in attachments or ():
        filename, content, content_type = att
        msg.attach(filename, content, content_type or "application/octet-stream")

    try:
        sent = msg.send(fail_silently=False)
        return bool(sent), f"sent={sent}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
