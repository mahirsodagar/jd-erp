"""Email sender — the one path every outbound mail takes.

Wraps Django's mail API with the institute's rules:

* **Transport**: the project's default backend, which is ZeptoMail SMTP
  (EMAIL_HOST / EMAIL_HOST_PASSWORD = the ZeptoMail send-mail token).
  There is no per-domain or per-trigger SMTP any more.
* **From**: always `DEFAULT_FROM_EMAIL` (`no-reply@dkul.in`) wrapped
  with `DEFAULT_FROM_NAME`. Callers cannot override it — ZeptoMail
  rejects unverified From domains, and the client forbids sending as
  any other mailbox.
* **Reply-To**: `reply_to` if the caller resolved one (see
  `apps.notifications.reply_to`), else `EMAIL_DEFAULT_REPLY_TO`.
* **HTML**: `is_html=True` sends a multipart/alternative message with a
  plain-text rendering of the HTML as the fallback part.

Returns `(ok, detail)`; never raises on transport errors so a mail
problem cannot break the business action that triggered it.
"""

from __future__ import annotations

import html as _html
import re
from email.utils import formataddr, parseaddr
from typing import Iterable

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


# Attachments arrive as (filename, bytes, content_type) tuples — same
# shape EmailMessage.attach() expects natively.
Attachment = tuple[str, bytes, str]


def resolve_from_email() -> str:
    """`DEFAULT_FROM_EMAIL` with a display name, or "" when unset."""
    display_name = (
        getattr(settings, "DEFAULT_FROM_NAME", "") or "JD Institute"
    ).strip()
    candidate = (getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip()
    if not candidate:
        return ""
    name, addr = parseaddr(candidate)
    if name:
        return candidate
    if addr:
        return formataddr((display_name, addr))
    return ""


# Kept for callers/tests that import the old private name.
_resolve_from_email = resolve_from_email


def _split(addresses: str | Iterable[str] | None) -> list[str]:
    if not addresses:
        return []
    if isinstance(addresses, str):
        addresses = addresses.split(",")
    out, seen = [], set()
    for a in addresses:
        a = (a or "").strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|tr|li|h[1-6]|table)[^>]*>", re.I)
_STYLE_RE = re.compile(r"<(style|script|head)[^>]*>.*?</\1>", re.I | re.S)
_ANCHOR_RE = re.compile(
    r"<a\b[^>]*?\bhref\s*=\s*([\"'])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S,
)


def _anchor_to_text(m: re.Match) -> str:
    """`<a href=U>label</a>` → `label (U)` so the URL survives in the
    text part (buttons in the client's HTML carry the only link)."""
    url = _html.unescape(m.group(2).strip())
    label = " ".join(_TAG_RE.sub("", m.group(3)).split())
    if not url or url.startswith("#"):
        return label
    if not label or label == url:
        return url
    return f"{label} ({url})"


def html_to_text(html_body: str) -> str:
    """Rough plain-text rendering of an HTML body for the text part."""
    text = _STYLE_RE.sub("", html_body or "")
    text = _ANCHOR_RE.sub(_anchor_to_text, text)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def send_email(
    *,
    recipient: str | Iterable[str],
    cc: str | Iterable[str] = "",
    subject: str,
    body: str,
    is_html: bool = False,
    attachments: Iterable[Attachment] | None = None,
    reply_to: str | Iterable[str] = "",
    bcc: str | Iterable[str] = "",
    headers: dict | None = None,
) -> tuple[bool, str]:
    to_list = _split(recipient)
    if not to_list:
        return False, "No recipient address."

    from_email = resolve_from_email()
    if not from_email:
        return False, "No sender address — set DEFAULT_FROM_EMAIL in .env."

    reply_list = _split(reply_to)
    if not reply_list:
        from .reply_to import default_reply_to
        reply_list = _split(default_reply_to())

    text_body = html_to_text(body) if is_html else body
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=to_list,
        cc=_split(cc),
        bcc=_split(bcc),
        reply_to=reply_list or None,
        headers=headers or None,
    )
    if is_html:
        msg.attach_alternative(body, "text/html")

    for att in attachments or ():
        filename, content, content_type = att
        msg.attach(filename, content, content_type or "application/octet-stream")

    try:
        sent = msg.send(fail_silently=False)
        return bool(sent), f"sent={sent}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
