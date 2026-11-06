"""Public webhook for the JD website (WordPress Forminator forms).

Port of legacy `admin/webhooks/webhook.php`. Every form on
www.jdinstitute.edu.in POSTs its raw Forminator payload here:

    name_1 / email_1 / phone_1 / phone_2 / date_1
    select_1  campus ("Bangalore", "Goa", "one" ...)
    select_3  course (default field)
    select_4  Goa course on old forms, enquiry type on new ones
    select_5 / select_6 / select_7  course for Cochin / Hyderabad / Vijayawada
    select_2  "how did you know"
    hidden_1..3  utm_source / utm_medium / utm_campaign
    hidden_8  legacy numeric lead_source id (unreliable; form_title is used)
    form_title / current_url / entry_time  Forminator metadata

Differences from the PHP on purpose:
  * every raw payload is stored as a WebsiteLeadEvent before mapping;
  * free-text values go through WebsiteValueMap, then (for courses) an
    exact match on Program.name, then the "*" fallback row — the lead is
    created with the fallback and the raw text is kept in remarks, so a
    missing mapping never loses an enquiry;
  * the lead goes through services.create_lead, so dedupe, occurrence
    numbering and round-robin assignment apply like any other lead;
  * authenticated by LEAD_INTAKE_API_KEY, as a header or ?key= (Forminator
    cannot set headers without an add-on);
  * the response is always 200 once the key is accepted, because
    Forminator neither retries nor alerts on errors.
"""

import hmac
import logging
import re

from django.conf import settings
from django.db import transaction
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.throttles import WebsiteWebhookThrottle
from apps.master.models import Program

from .models import WebsiteLeadEvent, WebsiteValueMap
from .services import create_lead

log = logging.getLogger(__name__)

WILDCARD = "*"

# Which Forminator field carries the course for each campus code. The
# default field (select_3) is always tried after the campus-specific one.
CAMPUS_COURSE_FIELD = {
    "GOA": "select_4",
    "COK": "select_5",
    "HYD": "select_6",
    "BZA": "select_7",
}
COURSE_FIELDS = ("select_3", "select_4", "select_5", "select_6", "select_7")

# Placeholder dropdown values the site sends when nothing was chosen.
PLACEHOLDERS = {"", "one", "two", "select", "select campus", "select course",
                "preferred centre", "preferred center", "source"}

_DURATION_SUFFIX = re.compile(
    r"\s*[-–]?\s*\d+(\.\d+)?\s*(years?|yrs?|months?|weeks?)\s*$", re.IGNORECASE,
)


def normalise(value) -> str:
    """Lower-case, hyphens/underscores to spaces, drop a trailing
    "- 4 Years" style duration, collapse whitespace."""
    s = str(value or "").strip().lower()
    s = _DURATION_SUFFIX.sub("", s)
    s = re.sub(r"[-_/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_placeholder(raw) -> bool:
    return normalise(raw) in PLACEHOLDERS


class _Resolver:
    """Resolve website strings through WebsiteValueMap with one query
    per kind, remembering what fell back so the event can show it."""

    def __init__(self):
        self.warnings: list[str] = []
        rows = WebsiteValueMap.objects.filter(is_active=True).select_related(
            "campus", "program", "source",
        )
        self._maps: dict[str, dict[str, object]] = {k: {} for k, _ in WebsiteValueMap.Kind.choices}
        for row in rows:
            self._maps[row.kind][row.website_value] = row.target

    def lookup(self, kind: str, raw):
        if raw is None or is_placeholder(raw):
            return None
        return self._maps[kind].get(normalise(raw))

    def fallback(self, kind: str, label: str, raw):
        target = self._maps[kind].get(WILDCARD)
        shown = str(raw or "").strip() or "(blank)"
        if target is None:
            raise ValueError(
                f"No {label} mapping for {shown!r} and no '*' fallback row — "
                f"seed WebsiteValueMap (manage.py seed_website_maps)."
            )
        self.warnings.append(f"Unmapped {label} {shown!r}; used {target}.")
        return target

    # -- per-kind helpers -------------------------------------------------

    def campus(self, raw):
        return self.lookup("campus", raw) or self.fallback("campus", "campus", raw)

    def source(self, form_title):
        return self.lookup("source", form_title) or self.fallback("source", "form", form_title)

    def program(self, candidates: list[str]):
        """`candidates` is the ordered list of raw course strings. First
        hit wins: mapping table, then an exact (normalised) Program name."""
        for raw in candidates:
            hit = self.lookup("program", raw)
            if hit is not None:
                return hit
        wanted = {normalise(c) for c in candidates if not is_placeholder(c)}
        if wanted:
            by_name = {}
            for p in Program.objects.filter(is_active=True).order_by("pk"):
                by_name.setdefault(normalise(p.name), p)
            for raw in candidates:
                hit = by_name.get(normalise(raw))
                if hit is not None:
                    return hit
        shown = next((c for c in candidates if not is_placeholder(c)), "")
        return self.fallback("program", "course", shown)


def _str(payload: dict, key: str) -> str:
    v = payload.get(key)
    return "" if v is None else str(v).strip()


def build_lead(payload: dict) -> tuple[dict, dict, list[str]]:
    """Translate a raw Forminator payload into create_lead() kwargs.

    Returns (lead_data, utm, warnings). Raises ValueError when the
    payload cannot become a lead at all (no name, no phone)."""
    name = _str(payload, "name_1")
    phone = _str(payload, "phone_1").replace(" ", "")
    email = _str(payload, "email_1")
    if not name or not phone:
        raise ValueError("Payload has no name_1/phone_1 — not a lead form.")

    r = _Resolver()
    campus_raw = _str(payload, "select_1")
    campus = r.campus(campus_raw)

    # Course: campus-specific field first, then the default field, then
    # anything else that was filled, so an old Goa form (course in
    # select_4) and a new one (enquiry type in select_4) both work.
    ordered = []
    specific = CAMPUS_COURSE_FIELD.get(campus.code)
    if specific:
        ordered.append(specific)
    ordered.append("select_3")
    ordered += [f for f in COURSE_FIELDS if f not in ordered]
    candidates = [_str(payload, f) for f in ordered if _str(payload, f)]
    program = r.program(candidates)

    form_title = _str(payload, "form_title")
    source = r.source(form_title)

    # Everything the Lead model has no column for is kept in remarks so
    # the counsellor sees exactly what the student typed.
    lines = [f"Website form: {form_title or '(untitled)'}"]
    if candidates:
        lines.append("Course interest: " + " | ".join(dict.fromkeys(candidates)))
    if campus_raw and not is_placeholder(campus_raw):
        lines.append(f"Campus chosen: {campus_raw}")
    how = _str(payload, "select_2")
    if how and not is_placeholder(how):
        lines.append(f"How did you know: {how}")
    dob = _str(payload, "date_1")
    if dob:
        lines.append(f"DOB: {dob}")
    page = _str(payload, "current_url") or _str(payload, "hidden_6")
    if page:
        lines.append(f"Page: {page}")
    lines += [f"Note: {w}" for w in r.warnings]

    data = {
        "name": name[:160],
        "email": email[:254],
        "phone": phone[:32],
        "alternative_phone": _str(payload, "phone_2").replace(" ", "")[:32],
        "campus": campus,
        "program": program,
        "source": source,
        "remarks": "\n".join(lines),
    }
    utm = {
        "utm_source": _str(payload, "hidden_1")[:120],
        "utm_medium": _str(payload, "hidden_2")[:120],
        "utm_campaign": _str(payload, "hidden_3")[:160],
        "utm_term": "",
        "utm_content": form_title[:200],
    }
    return data, utm, r.warnings


class HasWebsiteWebhookKey(BasePermission):
    """Same secret as the JSON intake endpoint (LEAD_INTAKE_API_KEY), but
    also accepted as `?key=` because Forminator's free webhook action
    cannot add request headers."""

    message = "Invalid or missing webhook key."

    def has_permission(self, request, view):
        configured = getattr(settings, "LEAD_INTAKE_API_KEY", "") or ""
        if not configured:
            return False
        provided = request.headers.get("X-API-Key") or request.query_params.get("key") or ""
        return bool(provided) and hmac.compare_digest(provided, configured)


def _client_ip(request):
    return (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR")
        or None
    )


class WebsiteLeadWebhookView(APIView):
    authentication_classes = []
    permission_classes = [HasWebsiteWebhookKey]
    throttle_classes = [WebsiteWebhookThrottle]

    def post(self, request):
        payload = request.data
        if hasattr(payload, "dict"):          # form-encoded fallback
            payload = payload.dict()
        if not isinstance(payload, dict):
            payload = {"_raw": payload}

        event = WebsiteLeadEvent.objects.create(
            remote_ip=_client_ip(request),
            form_title=_str(payload, "form_title")[:200],
            payload=payload,
            status=WebsiteLeadEvent.Status.FAILED,
        )
        try:
            with transaction.atomic():
                data, utm, warnings = build_lead(payload)
                lead = create_lead(data=data, created_by=None, utm=utm)
        except Exception as exc:  # noqa: BLE001 — recorded, never re-raised
            log.warning("website webhook: event %s failed: %s", event.pk, exc)
            event.error = str(exc)[:2000]
            event.save(update_fields=["error"])
            return Response({"ok": False, "event_id": event.pk, "error": event.error})

        event.lead = lead
        event.warnings = warnings
        event.status = (WebsiteLeadEvent.Status.DUPLICATE if lead.is_repeated
                        else WebsiteLeadEvent.Status.CREATED)
        event.save(update_fields=["lead", "warnings", "status"])
        return Response({
            "ok": True, "event_id": event.pk, "lead_id": lead.pk,
            "is_repeated": lead.is_repeated, "warnings": warnings,
        })
