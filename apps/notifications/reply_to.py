"""Per-trigger Reply-To routing.

Every outbound mail leaves From `no-reply@dkul.in` over ZeptoMail (see
the Email block in config/settings.py). Replies must still land with
whoever handles that kind of mail, so the dispatcher sets the Reply-To
header per trigger:

    leave / comp-off          → the leave department inbox
    fee receipts / fee links  → the campus receipts inbox
    application / lead mail   → the assigned counsellor, else the campus
                                admissions inbox
    relieving                 → the approver handling the application,
                                else the Principal's inbox
    student leave / assignments
                              → mentor / faculty / student (from context)
    everything else           → EMAIL_DEFAULT_REPLY_TO

`resolve_reply_to(template_key, context)` is the single entry point.
Resolution order:

  1. ``context["reply_to"]`` — an explicit handler chosen by the caller
     (counsellor, reporting manager, faculty…). Always wins.
  2. ``settings.EMAIL_REPLY_TO_POLICY[template_key]`` — a token
     (HR_LEAVE, CAMPUS_RECEIPTS, CAMPUS_ADMISSIONS, CAMPUS_UNDERTAKING,
     PRINCIPAL, ACCOUNTS, CONTEXT) or a literal address. Campus tokens
     read ``context["campus_code"]``.
  3. ``settings.EMAIL_DEFAULT_REPLY_TO``.

The handler address is used ONLY as Reply-To — never as the From and
never for SMTP authentication (client requirement, 2026-11-18).
"""

from __future__ import annotations

from django.conf import settings


def _campus_inbox(setting_name: str, campus_code: str) -> str:
    inboxes = getattr(settings, setting_name, {}) or {}
    code = (campus_code or "").strip().upper()
    return (inboxes.get(code) or "").strip()


def campus_code_of(obj) -> str:
    """`Campus.code` for anything that is a campus or carries one
    (enrollment, student, lead, application…). "" when unknown."""
    if obj is None:
        return ""
    code = getattr(obj, "code", None)
    if isinstance(code, str) and not hasattr(obj, "campus"):
        return code
    campus = getattr(obj, "campus", None)
    return (getattr(campus, "code", "") or "") if campus is not None else ""


def _from_token(token: str, context: dict) -> str:
    campus_code = (context.get("campus_code") or "")
    if token == "HR_LEAVE":
        return (getattr(settings, "LEAVES_HR_INBOX", "") or "").strip()
    if token == "CAMPUS_RECEIPTS":
        return _campus_inbox("FEE_RECEIPT_CAMPUS_INBOXES", campus_code)
    if token == "CAMPUS_ADMISSIONS":
        return _campus_inbox("APPLICATION_ACK_CAMPUS_INBOXES", campus_code)
    if token == "CAMPUS_UNDERTAKING":
        return _campus_inbox("UNDERTAKING_CAMPUS_INBOXES", campus_code)
    if token == "PRINCIPAL":
        return (getattr(settings, "PRINCIPAL_INBOX", "") or "").strip()
    if token == "ACCOUNTS":
        return (getattr(settings, "ACCOUNTS_INBOX", "") or "").strip()
    if token == "CONTEXT":
        return ""
    # Literal address configured straight in the policy map.
    return token.strip() if "@" in token else ""


def default_reply_to() -> str:
    return (getattr(settings, "EMAIL_DEFAULT_REPLY_TO", "") or "").strip()


def resolve_reply_to(template_key: str, context: dict | None = None) -> str:
    """The Reply-To address for one outbound mail (never blank unless
    EMAIL_DEFAULT_REPLY_TO itself is blank)."""
    context = context or {}
    explicit = (context.get("reply_to") or "").strip()
    if explicit:
        return explicit
    policy = (getattr(settings, "EMAIL_REPLY_TO_POLICY", {}) or {}).get(
        template_key or "", "",
    )
    if policy:
        addr = _from_token(str(policy), context)
        if addr:
            return addr
    return default_reply_to()
