"""Per-trigger sender-domain routing.

The "From" domain on an outbound email is not constant — it depends on
the *trigger* and, for fee / admission mail, on the student's *course
type*. From the institute's spec:

    fee link / fee receipt / admission form link / admission form filled
    / installment undertaking / installment-pending reminder
        → Diploma courses        : jdinstitute.edu.in
        → Degree / Bachelors     : jdindia.com
    reset student password / portal credentials
        → mail.jdinstitute.com
    leave / relieving / experience (HR + staff workflows)
        → jdinstitute.edu.in

`resolve_sender(template_key, degree_type=...)` maps a trigger to the
domain + From-address it should send from. It is provider-agnostic: the
dispatcher passes the result to MSG91 (`from`/`domain`) or to SMTP
(`from_email`) as appropriate.

SAFETY: a domain is only made "live" when it has an entry in
`settings.EMAIL_SENDER_BY_DOMAIN`. Domains absent from that map resolve
to a `None` From-address, and the dispatcher falls back to the provider
default (the current single-domain behaviour). This lets the routing
*policy* land now while the new sender domains (jdinstitute.edu.in,
jdindia.com) are still being verified on MSG91 — flip them on by adding
the verified From-address to that map, no code change.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class SenderInfo:
    """Resolved sender for one outbound email.

    `domain` is the policy-selected sending domain. `from_email` is the
    verified From-address for that domain, or "" when the domain isn't
    configured as a live sender yet — in which case the caller should
    fall back to the provider default.
    """

    domain: str
    from_email: str

    @property
    def is_live(self) -> bool:
        return bool(self.from_email)


# Policy tokens used in settings.EMAIL_SENDER_DOMAIN_POLICY. COURSE is
# resolved per-student (diploma vs degree); the rest map to a fixed
# domain setting. Any other value is treated as a literal domain string.
_COURSE = "COURSE"
_PORTAL = "PORTAL"
_HR = "HR"


def is_diploma(degree_type: str | None) -> bool:
    """True when a program's free-form `degree_type` denotes a diploma.

    `degree_type` is entered by hand (e.g. "B.Des", "M.Des", "Diploma"),
    so we match on substring rather than equality. Anything that isn't a
    diploma is treated as a degree / bachelors course.
    """
    return "diploma" in (degree_type or "").strip().lower()


def _domain_for(template_key: str, degree_type: str | None) -> str:
    """Return the policy-selected domain for a trigger, or "" if the
    trigger has no domain policy (caller keeps the provider default)."""
    policy = (getattr(settings, "EMAIL_SENDER_DOMAIN_POLICY", {}) or {}).get(
        template_key,
    )
    if not policy:
        return ""
    if policy == _COURSE:
        return (
            getattr(settings, "EMAIL_DOMAIN_DIPLOMA", "")
            if is_diploma(degree_type)
            else getattr(settings, "EMAIL_DOMAIN_DEGREE", "")
        )
    if policy == _PORTAL:
        return getattr(settings, "EMAIL_DOMAIN_PORTAL", "")
    if policy == _HR:
        return getattr(settings, "EMAIL_DOMAIN_HR", "")
    # Literal domain configured directly in the policy map.
    return policy


def transport_for(domain: str) -> tuple[str, dict | None]:
    """Map a sending domain to the transport that physically delivers it.

    Single source of truth for the institute's domain↔service table:

        jdindia.com          → SMTP, dedicated Zoho connection
        mail.jdinstitute.com → MSG91 (templated transactional API)
        jdinstitute.edu.in   → SMTP, project default (Gmail/Workspace)
        <anything else>      → SMTP, project default

    Returns ``(kind, smtp_config)`` where ``kind`` is "msg91" or "smtp".
    For "smtp", ``smtp_config`` is a dedicated connection dict, or None to
    use the project's default email backend.
    """
    smtp_by_domain = getattr(settings, "EMAIL_SMTP_BY_DOMAIN", {}) or {}
    if domain in smtp_by_domain:
        return "smtp", smtp_by_domain[domain]
    if domain and domain == getattr(settings, "MSG91_DOMAIN", ""):
        return "msg91", None
    return "smtp", None


def resolve_sender(
    template_key: str, *, degree_type: str | None = None,
) -> SenderInfo | None:
    """Resolve the sender domain + From-address for a trigger.

    Returns None when the trigger has no domain policy — the dispatcher
    then leaves the provider default untouched. Returns a `SenderInfo`
    with an empty `from_email` when the policy picks a domain that isn't
    a configured live sender yet (same fallback to provider default, but
    the chosen domain is still visible for logging / diagnosis).
    """
    domain = _domain_for(template_key, degree_type)
    if not domain:
        return None
    by_domain = getattr(settings, "EMAIL_SENDER_BY_DOMAIN", {}) or {}
    return SenderInfo(domain=domain, from_email=by_domain.get(domain, ""))
