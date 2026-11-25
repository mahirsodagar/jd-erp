"""Resolve, lint and render system e-mail templates.

    resolve(key, institute)   → the subject/body/reply-to/cc/attachments
                                 that apply: institute override → global
                                 → registry default
    lint(trigger, subject, body) → unknown placeholders (save is refused
                                 while this is non-empty)
    build(key, context, …)    → fully rendered subject + HTML, with the
                                 institute layout wrapped around the body
                                 when the template asks for it

Placeholders are `{{Name}}` (client style) or `{name}`; both forms are
substituted. Unknown names are left in place at send time (an imperfect
mail beats a dropped one) — the lint on save is what keeps them out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.utils import timezone

from . import registry
from .models import EmailLayout, SystemEmailTemplate

_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}",
)
_BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.I | re.S)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.I | re.S)
_HTML_DOC_RE = re.compile(r"<\s*(!doctype|html)\b", re.I)

#: The slot the layout's header/footer surround.
CONTENT_SLOT = "{{Content}}"


# --- Placeholders -----------------------------------------------------------

def placeholders(text: str) -> set[str]:
    """Every placeholder name used in `text`, both spellings."""
    return {m.group(1) or m.group(2) for m in _PLACEHOLDER_RE.finditer(text or "")}


def render_text(template_text: str, context: dict) -> str:
    """Substitute known placeholders; leave unknown ones untouched so a
    CSS block or a literal brace never breaks the mail."""
    if not template_text:
        return ""
    context = context or {}

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in context:
            v = context[name]
            return "" if v is None else str(v)
        return m.group(0)

    return _PLACEHOLDER_RE.sub(sub, template_text)


def lint(trigger: registry.Trigger, subject: str, body_html: str) -> list[str]:
    """Names used in subject/body that this trigger will never fill.
    Sorted, de-duplicated. Empty = OK to save."""
    allowed = trigger.allowed_names()
    used = placeholders(subject) | placeholders(body_html)
    # CSS braces like `body{font-size:14px}` match the single-brace form
    # only when the inside is a bare identifier, which real CSS never is
    # — but `{Content}` style single names in a layout are fine too.
    return sorted(n for n in used if n not in allowed)


def lint_layout(header_html: str, footer_html: str) -> list[str]:
    used = placeholders(header_html) | placeholders(footer_html)
    return sorted(n for n in used if n not in registry.COMMON_NAMES)


# --- Resolution -------------------------------------------------------------

@dataclass
class Resolved:
    trigger: registry.Trigger
    subject: str
    body_html: str
    reply_to: str = ""
    cc_extra: str = ""
    use_layout: bool = True
    #: "institute" | "global" | "default"
    source: str = "default"
    template: SystemEmailTemplate | None = None
    version: object = None  # SystemEmailTemplateVersion | None
    attachments: list = field(default_factory=list)  # SystemEmailAttachment rows


def _institute_from(institute=None, *, institute_code: str = ""):
    if institute is not None:
        return institute
    code = (institute_code or "").strip()
    if not code:
        return None
    from apps.master.models import Institute

    return Institute.objects.filter(code__iexact=code).first()


def resolve(key: str, institute=None, *, institute_code: str = "") -> Resolved | None:
    """What applies for `key` at this institute, or None for an unknown
    key. Attachments come from the row that supplied the body."""
    trigger = registry.get(key)
    if trigger is None:
        return None
    inst = _institute_from(institute, institute_code=institute_code)

    rows = {
        (r.institute_id is not None): r
        for r in SystemEmailTemplate.objects.filter(trigger_key=key, is_active=True)
        .filter(models_q_scope(inst))
        .prefetch_related("attachments")
    }
    row = rows.get(True) if inst is not None else None
    source = "institute"
    if row is None:
        row = rows.get(False)
        source = "global"
    if row is None:
        return Resolved(
            trigger=trigger, subject=trigger.default_subject, body_html=trigger.body(),
            use_layout=trigger.use_layout, source="default",
        )
    version = row.versions.order_by("-number").first()
    return Resolved(
        trigger=trigger, subject=row.subject, body_html=row.body_html,
        reply_to=row.reply_to, cc_extra=row.cc_extra, use_layout=row.use_layout,
        source=source, template=row, version=version,
        attachments=list(row.attachments.all()),
    )


def models_q_scope(inst):
    from django.db.models import Q

    q = Q(institute__isnull=True)
    if inst is not None:
        q |= Q(institute=inst)
    return q


def resolve_layout(institute=None, *, institute_code: str = "") -> EmailLayout | None:
    """The enabled layout for this institute, else the enabled global
    one, else None (no wrapping)."""
    inst = _institute_from(institute, institute_code=institute_code)
    if inst is not None:
        row = EmailLayout.objects.filter(institute=inst, is_enabled=True).first()
        if row is not None and (row.header_html or row.footer_html):
            return row
    row = EmailLayout.objects.filter(institute__isnull=True, is_enabled=True).order_by("pk").first()
    if row is not None and (row.header_html or row.footer_html):
        return row
    return None


# --- Rendering --------------------------------------------------------------

def body_inner(html: str) -> tuple[str, str]:
    """`(styles, inner)` — the `<style>` blocks and the content inside
    `<body>` of a full HTML document; a fragment comes back as-is."""
    html = html or ""
    styles = "".join(_STYLE_RE.findall(html))
    m = _BODY_RE.search(html)
    inner = m.group(1) if m else _STYLE_RE.sub("", html)
    return styles, inner.strip()


def wrap(body_html: str, layout: EmailLayout | None, context: dict) -> str:
    """Put the (rendered) body inside the layout's header/footer. With no
    layout a fragment is still promoted to a full document so mail
    clients render it consistently; a full document passes through."""
    if layout is None:
        if _HTML_DOC_RE.search(body_html or ""):
            return body_html
        return _document("", body_html)
    styles, inner = body_inner(body_html)
    header = render_text(layout.header_html, context)
    footer = render_text(layout.footer_html, context)
    return _document(styles, f"{header}\n{inner}\n{footer}")


def _document(styles: str, inner: str) -> str:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"{styles}</head><body style=\"margin:0;padding:0;\">{inner}</body></html>"
    )


def full_context(trigger: registry.Trigger, context: dict) -> dict:
    """The caller's context + common variables (resolved from the
    institute / campus routing keys when the caller did not fill them)
    + the trigger's legacy alias names."""
    from .context import campus_vars, institute_vars, today_vars

    ctx = dict(context or {})
    for k, v in today_vars().items():
        ctx.setdefault(k, v)
    if "Institute_Name" not in ctx and ctx.get("institute_code"):
        inst = _institute_from(institute_code=ctx["institute_code"])
        for k, v in institute_vars(inst).items():
            ctx.setdefault(k, v)
    if "Campus_Name" not in ctx and ctx.get("campus_code"):
        from apps.master.models import Campus

        campus = Campus.objects.filter(code__iexact=ctx["campus_code"]).first()
        for k, v in campus_vars(campus).items():
            ctx.setdefault(k, v)
    if not ctx.get("Institute_Name"):
        from django.conf import settings

        ctx["Institute_Name"] = (getattr(settings, "DEFAULT_FROM_NAME", "") or "JD Institute").strip()
    for name in registry.COMMON_NAMES:
        ctx.setdefault(name, "")
    # Both spellings always resolve: the shipped HTML uses the old names,
    # a legacy caller may still pass only the old names.
    for old, new in trigger.aliases.items():
        if old in ctx and new not in ctx:
            ctx[new] = ctx[old]
        ctx.setdefault(old, ctx.get(new, ""))
    return ctx


@dataclass
class Built:
    subject: str
    html: str
    resolved: Resolved
    context: dict


def build(
    key: str, context: dict, *, institute=None,
    subject_override: str | None = None, body_override: str | None = None,
    use_layout_override: bool | None = None,
) -> Built | None:
    """Rendered subject + HTML for one send. The `*_override` arguments
    let the page preview unsaved text through the exact send path."""
    inst_code = (context or {}).get("institute_code", "")
    res = resolve(key, institute, institute_code=inst_code)
    if res is None:
        return None
    ctx = full_context(res.trigger, context)
    subject = render_text(
        res.subject if subject_override is None else subject_override, ctx,
    )
    body = render_text(
        res.body_html if body_override is None else body_override, ctx,
    )
    use_layout = res.use_layout if use_layout_override is None else use_layout_override
    layout = resolve_layout(institute, institute_code=inst_code) if use_layout else None
    html = wrap(body, layout, ctx)
    # Subjects are one line.
    subject = " ".join(subject.split())[:200]
    return Built(subject=subject, html=html, resolved=res, context=ctx)


# --- Saving -----------------------------------------------------------------

class TemplateLintError(ValueError):
    def __init__(self, unknown: list[str]):
        self.unknown = unknown
        super().__init__(
            "Unknown variable(s): " + ", ".join("{{%s}}" % n for n in unknown),
        )


def save_template(
    *, key: str, institute=None, subject: str, body_html: str, reply_to: str = "",
    cc_extra: str = "", use_layout: bool = True, editor_mode: str = "visual",
    is_active: bool = True, note: str = "", user=None,
) -> SystemEmailTemplate:
    """Create/update the row for (key, institute) and append a version.
    Raises TemplateLintError on unknown placeholders, KeyError on an
    unknown trigger."""
    trigger = registry.get(key)
    if trigger is None:
        raise KeyError(key)
    unknown = lint(trigger, subject, body_html)
    if unknown:
        raise TemplateLintError(unknown)

    row, _created = SystemEmailTemplate.objects.get_or_create(
        trigger_key=key, institute=institute,
        defaults={"subject": subject, "body_html": body_html},
    )
    row.subject = subject
    row.body_html = body_html
    row.reply_to = (reply_to or "").strip()
    row.cc_extra = ", ".join(_split(cc_extra))
    row.use_layout = bool(use_layout)
    row.editor_mode = editor_mode
    row.is_active = bool(is_active)
    row.updated_by = user
    row.save()
    _snapshot(row, note=note, user=user)
    return row


def reset_template(*, key: str, institute=None, user=None) -> SystemEmailTemplate | None:
    """Back to the code default (content, reply-to, CC, layout flag).
    History is kept — this is just another version. None when there was
    nothing customised."""
    trigger = registry.get(key)
    if trigger is None:
        raise KeyError(key)
    row = SystemEmailTemplate.objects.filter(trigger_key=key, institute=institute).first()
    if row is None:
        return None
    row.subject = trigger.default_subject
    row.body_html = trigger.body()
    row.reply_to = ""
    row.cc_extra = ""
    row.use_layout = trigger.use_layout
    row.editor_mode = "html" if _HTML_DOC_RE.search(row.body_html) else "visual"
    row.is_active = True
    row.updated_by = user
    row.save()
    _snapshot(row, note="Reset to default", user=user)
    return row


def revert_template(row: SystemEmailTemplate, version, *, user=None) -> SystemEmailTemplate:
    row.subject = version.subject
    row.body_html = version.body_html
    row.reply_to = version.reply_to
    row.cc_extra = version.cc_extra
    row.use_layout = version.use_layout
    row.editor_mode = version.editor_mode
    row.updated_by = user
    row.save()
    _snapshot(row, note=f"Reverted to v{version.number}", user=user)
    return row


def is_customised(row: SystemEmailTemplate | None, trigger: registry.Trigger) -> bool:
    """Whether a row differs from the code default in any way an admin
    can change."""
    if row is None:
        return False
    return (
        row.subject != trigger.default_subject
        or row.body_html.strip() != trigger.body().strip()
        or bool(row.reply_to) or bool(row.cc_extra)
        or row.use_layout != trigger.use_layout
        or row.attachments.exists()
    )


def _snapshot(row: SystemEmailTemplate, *, note: str, user):
    from .models import SystemEmailTemplateVersion

    last = row.versions.order_by("-number").values_list("number", flat=True).first() or 0
    return SystemEmailTemplateVersion.objects.create(
        template=row, number=last + 1, subject=row.subject, body_html=row.body_html,
        reply_to=row.reply_to, cc_extra=row.cc_extra, use_layout=row.use_layout,
        editor_mode=row.editor_mode, note=(note or "")[:200], created_by=user,
    )


def save_layout(*, institute=None, header_html: str, footer_html: str,
                is_enabled: bool = True, note: str = "", user=None) -> EmailLayout:
    from .models import EmailLayoutVersion

    unknown = lint_layout(header_html, footer_html)
    if unknown:
        raise TemplateLintError(unknown)
    if institute is None:
        row = EmailLayout.global_row()
    else:
        row, _ = EmailLayout.objects.get_or_create(institute=institute)
    row.header_html = header_html or ""
    row.footer_html = footer_html or ""
    row.is_enabled = bool(is_enabled)
    row.updated_by = user
    row.save()
    last = row.versions.order_by("-number").values_list("number", flat=True).first() or 0
    EmailLayoutVersion.objects.create(
        layout=row, number=last + 1, header_html=row.header_html,
        footer_html=row.footer_html, is_enabled=row.is_enabled,
        note=(note or "")[:200], created_by=user,
    )
    return row


def _split(addresses: str) -> list[str]:
    out, seen = [], set()
    for a in (addresses or "").replace(";", ",").split(","):
        a = a.strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def now_iso() -> str:
    return timezone.now().isoformat()
