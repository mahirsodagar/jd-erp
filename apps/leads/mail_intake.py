"""Process one stored inbound email into a lead.

    process_email(email_row)  → sets status / lead / parsed / warnings

Steps:
  1. pick the matching LeadMailRule (first active rule whose From /
     Subject filters match); its parser may be IGNORE;
  2. parse the body (mail_parsers) into raw fields;
  3. map campus / course / source through WebsiteValueMap exactly like
     the website webhook, with the rule's source and default campus
     taking precedence where set;
  4. if a lead with the same phone or email was created within
     LEAD_MAIL_DUP_WINDOW_HOURS the mail is the notification copy of a
     submission already in the ERP (the website posts the same enquiry
     to the webhook): link it and stop — status ALREADY;
  5. otherwise services.create_lead → CREATED, or REPEAT when the
     person enquired before.

Everything the Lead has no column for is written to remarks so the
counsellor sees exactly what the student typed.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import mail_parsers
from .mail_models import InboundLeadEmail, LeadMailRule
from .services import create_lead, normalize_phone
from .website_webhook import _Resolver, is_placeholder

log = logging.getLogger(__name__)

Status = InboundLeadEmail.Status


def pick_rule(from_address: str, subject: str):
    for rule in LeadMailRule.objects.filter(is_active=True).select_related(
            "source", "default_campus"):
        if rule.matches(from_address, subject):
            return rule
    return None


def dup_window_hours() -> int:
    return int(getattr(settings, "LEAD_MAIL_DUP_WINDOW_HOURS", 24) or 0)


def recent_matching_lead(*, email: str, phone: str):
    """A lead created inside the dedupe window with the same contact —
    i.e. this mail is a second copy of a submission we already have."""
    from .models import Lead

    hours = dup_window_hours()
    if hours <= 0:
        return None
    phone_norm = normalize_phone(phone)
    email = (email or "").strip()
    if not phone_norm and not email:
        return None
    q = Q()
    if phone_norm:
        q |= Q(phone_normalized=phone_norm)
    if email:
        q |= Q(email__iexact=email)
    since = timezone.now() - timedelta(hours=hours)
    return (Lead.objects.filter(q, created_at__gte=since)
            .order_by("created_at").first())


# Website forms live on two sites. The JDSD site (www.jdsd.in) has its own
# source rows in seed_lead_sources; the form title alone cannot tell the
# sites apart, so the page URL decides. Returns None when no such source
# row exists, so the normal title → WebsiteValueMap lookup still runs.
def website_source_hint(fields: dict):
    from apps.master.models import LeadSource

    page = (fields.get("page_url") or "").lower()
    title = (fields.get("form_title") or "").lower()
    if "jdsd.in" not in page:
        return None
    slug = "jdsd-brochure-download" if "brochure" in title else (
        "jdsd-course-price-reveal" if "price" in title else "jdsd-website")
    return LeadSource.objects.filter(slug=slug, is_active=True).first()


def build_lead(fields: dict, rule, *, from_address: str, subject: str,
               sent_at) -> tuple[dict, dict, list[str]]:
    """Raw parsed fields → create_lead kwargs. Raises ValueError when
    there is not enough to make a lead."""
    name = (fields.get("name") or "").strip()
    phone = (fields.get("phone") or "").replace(" ", "").strip()
    email = (fields.get("email") or "").strip()
    if not name or not (phone or email):
        raise ValueError("No name with a phone or email in this mail.")

    r = _Resolver()

    campus_raw = fields.get("campus_raw") or ""
    campus = r.lookup("campus", campus_raw)
    if campus is None and rule is not None and rule.default_campus_id:
        campus = rule.default_campus
        if campus_raw and not is_placeholder(campus_raw):
            r.warnings.append(f"Unmapped campus {campus_raw!r}; used rule default {campus}.")
    if campus is None:
        campus = r.fallback("campus", "campus", campus_raw)

    candidates = [c for c in (fields.get("course_raw"),) if c]
    if fields.get("page_url"):
        slug = mail_parsers.course_slug(fields["page_url"])
        if slug and slug not in candidates:
            candidates.append(slug)
    program = r.program(candidates)

    if rule is not None and rule.source_id:
        source = rule.source
    else:
        source = website_source_hint(fields) or r.source(fields.get("form_title") or "")

    lines = [f"Email lead: {fields.get('form_title') or subject or '(no subject)'}"]
    if fields.get("course_raw"):
        lines.append(f"Course interest: {fields['course_raw']}")
    if campus_raw and not is_placeholder(campus_raw):
        lines.append(f"Campus chosen: {campus_raw}")
    for label, key in (("How did you know", "how_known"), ("DOB", "dob"),
                       ("Qualification", "qualification"), ("Message", "message"),
                       ("Page", "page_url")):
        if fields.get(key):
            lines.append(f"{label}: {fields[key]}")
    lines.append(f"From: {from_address}" + (f" on {sent_at:%d-%m-%Y %H:%M}" if sent_at else ""))
    lines += [f"Note: {w}" for w in r.warnings]

    data = {
        "name": name[:160],
        "email": email[:254],
        "phone": phone[:32],
        "alternative_phone": (fields.get("alt_phone") or "").replace(" ", "")[:32],
        "campus": campus,
        "program": program,
        "source": source,
        "remarks": "\n".join(lines),
    }
    utm = {
        "utm_source": (fields.get("utm_source") or "")[:120],
        "utm_medium": (fields.get("utm_medium") or "")[:120],
        "utm_campaign": (fields.get("utm_campaign") or "")[:160],
        "utm_term": "",
        "utm_content": (fields.get("utm_content") or fields.get("form_title") or "")[:200],
    }
    return data, utm, r.warnings


def process_email(row: InboundLeadEmail, *, force: bool = False) -> InboundLeadEmail:
    """Parse + map + create. Idempotent: a row that already has a lead is
    left alone unless `force` (used by Retry after fixing a mapping on
    an UNPARSED / ERROR row — never on one that already made a lead)."""
    if row.lead_id and not force:
        return row
    if row.status == Status.IGNORED and not force:
        return row

    rule = pick_rule(row.from_address, row.subject)
    row.rule = rule
    row.warnings = []
    row.error = ""

    if rule is not None and rule.parser == LeadMailRule.Parser.IGNORE:
        row.parser = "ignore"
        row.parsed = {}
        row.status = Status.IGNORED
        row.processed_at = timezone.now()
        row.save()
        return row

    wanted = rule.parser if rule is not None else "auto"
    parser, fields = mail_parsers.parse(
        wanted, from_address=row.from_address, subject=row.subject,
        text_body=row.text_body, html_body=row.html_body,
    )
    row.parser = parser
    row.parsed = {k: v for k, v in fields.items() if k != "ok"}

    if not fields.get("ok"):
        row.status = Status.UNPARSED
        row.error = "Could not find a name with a phone or email."
        row.processed_at = timezone.now()
        row.save()
        return row

    existing = recent_matching_lead(email=fields.get("email", ""),
                                    phone=fields.get("phone", ""))
    if existing is not None:
        row.lead = existing
        row.status = Status.ALREADY
        row.warnings = [f"Matches lead #{existing.pk} created "
                        f"{existing.created_at:%d-%m-%Y %H:%M} (within "
                        f"{dup_window_hours()}h) — not created again."]
        row.processed_at = timezone.now()
        row.save()
        return row

    try:
        with transaction.atomic():
            data, utm, warnings = build_lead(
                fields, rule, from_address=row.from_address,
                subject=row.subject, sent_at=row.sent_at)
            lead = create_lead(data=data, created_by=None, utm=utm)
    except Exception as exc:  # noqa: BLE001 — recorded on the row
        log.warning("lead mail %s failed: %s", row.pk, exc)
        row.status = Status.ERROR
        row.error = str(exc)[:2000]
        row.processed_at = timezone.now()
        row.save()
        return row

    row.lead = lead
    row.warnings = warnings
    row.status = Status.REPEAT if lead.is_repeated else Status.CREATED
    row.processed_at = timezone.now()
    row.save()
    return row


def create_manually(row: InboundLeadEmail, *, data: dict, user) -> InboundLeadEmail:
    """Staff filled the form on the Email Inbox page for an UNPARSED /
    ERROR / IGNORED mail. `data` is already validated create_lead kwargs."""
    remarks = data.get("remarks") or ""
    tail = f"Email lead (manual): {row.subject or '(no subject)'} from {row.from_address}"
    data["remarks"] = f"{remarks}\n{tail}".strip()
    with transaction.atomic():
        lead = create_lead(data=data, created_by=user, utm=None)
        row.lead = lead
        row.status = Status.MANUAL
        row.error = ""
        row.processed_at = timezone.now()
        row.processed_by = user
        row.save()
    return row
