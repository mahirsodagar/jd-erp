"""Public, no-auth endpoints used by the self-fill application form.

Mounted under `/api/public/application/<token>/` — see config/urls.py.
The token is a UUID stored on `Lead.application_token`, generated when
staff clicks "Send application link". The same token stays valid for
re-edits so students can fill incrementally after counsellor review.

Counsellors close the form for the student by setting
`Lead.application_locked_for_student=True` via the staff endpoints in
apps/leads/views.py — once closed, POSTs here return 403.
"""

import json

from django.http import Http404
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.leads.models import Lead

from .application_terms import terms_for
from .services import submit_application_from_lead


def _bool(value) -> bool:
    """Truthiness for a value that may have crossed a multipart boundary
    and arrived as the *string* "false"."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def _resolve_lead(token: str) -> Lead:
    try:
        lead = Lead.objects.select_related(
            "campus", "program", "program__institute",
        ).get(application_token=token)
    except (Lead.DoesNotExist, ValueError):
        raise Http404("Invalid or expired application link.")
    return lead


class PublicApplicationView(APIView):
    """`GET` — return pre-fill (lead name/email/phone + program/campus).
    `POST` — submit the full application (creates Student + docs)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request, token):
        lead = _resolve_lead(token)
        return Response(_prefill(lead))

    def post(self, request, token):
        lead = _resolve_lead(token)

        # `documents` arrives as a JSON string when sent via multipart;
        # accept both dict and string here for flexibility.
        raw_docs = request.data.get("documents") or "[]"
        if isinstance(raw_docs, str):
            try:
                documents = json.loads(raw_docs)
            except json.JSONDecodeError:
                return Response(
                    {"documents": "Must be valid JSON."},
                    status=http.HTTP_400_BAD_REQUEST,
                )
        else:
            documents = raw_docs

        # Numeric FK fields — coerce because multipart sends them as
        # strings.
        def _int_or_none(key):
            v = request.data.get(key)
            if v in (None, "", "null"):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        payload = {
            # Student-overridable placement.
            "campus": _int_or_none("campus"),
            "program": _int_or_none("program"),
            "student_name": request.data.get("student_name"),
            "father_name": request.data.get("father_name", ""),
            "mother_name": request.data.get("mother_name", ""),
            "gender": request.data.get("gender"),
            "dob": request.data.get("dob"),
            "category": request.data.get("category"),
            "study_medium": request.data.get("study_medium"),
            "nationality": request.data.get("nationality"),
            "blood_group": request.data.get("blood_group", ""),
            "current_address": request.data.get("current_address", ""),
            "current_city": _int_or_none("current_city"),
            "current_state": _int_or_none("current_state"),
            "current_pincode": request.data.get("current_pincode", ""),
            "permanent_address": request.data.get("permanent_address", ""),
            "permanent_city": _int_or_none("permanent_city"),
            "permanent_state": _int_or_none("permanent_state"),
            "permanent_pincode": request.data.get("permanent_pincode", ""),
            "student_mobile": request.data.get("student_mobile"),
            "father_mobile": request.data.get("father_mobile", ""),
            "mother_mobile": request.data.get("mother_mobile", ""),
            "student_email": request.data.get("student_email"),
            "father_email": request.data.get("father_email", ""),
            "mother_email": request.data.get("mother_email", ""),
            "father_occupation": request.data.get("father_occupation", ""),
            "mother_occupation": request.data.get("mother_occupation", ""),
            # Consent. Multipart sends booleans as strings, so compare
            # against the truthy spellings a form can produce.
            "declaration_accepted": _bool(request.data.get("declaration_accepted")),
            "rules_accepted": _bool(request.data.get("rules_accepted")),
            "documents": documents,
            "_photo_file": request.FILES.get("photo"),
            # Per-row certificate uploads. Frontend sends multipart
            # parts named `document_file_{i}` aligned by index with
            # the documents JSON. We keep them index-aligned (None for
            # rows without an upload) so the service layer can attach
            # them to the matching StudentDocument.
            "_document_files": [
                request.FILES.get(f"document_file_{i}")
                for i in range(len(documents))
            ],
        }

        try:
            student, creds = submit_application_from_lead(
                lead=lead, payload=payload,
            )
        except PermissionError as e:
            # Form closed by counsellor — 403 with the message verbatim.
            return Response({"detail": str(e)}, status=http.HTTP_403_FORBIDDEN)
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        except KeyError as e:
            return Response(
                {str(e).strip("'\""): "Required."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "student_id": student.id,
                "application_form_id": student.application_form_id,
                **creds,
            },
            status=http.HTTP_201_CREATED,
        )


def _fee_structures() -> list[dict]:
    """Headline fee numbers per (campus, program), for the fee-structure
    panel on the public form.

    The student can change campus/program on the form, so we ship every
    active template and let the frontend pick the matching one. Only the
    program-wide template (course is NULL) is published — course-level
    templates are an internal refinement the student hasn't chosen yet.
    Where several academic years exist we keep the most recent, matching
    the lookup order in `apps.leads.send_links`.
    """
    from apps.master.models import FeeTemplate

    rows: dict[tuple[int, int], dict] = {}
    for t in (
        FeeTemplate.objects
        .filter(is_active=True, course__isnull=True)
        .select_related("academic_year")
        .order_by("academic_year__id", "id")  # newest last — it wins
    ):
        rows[(t.campus_id, t.program_id)] = {
            "campus": t.campus_id,
            "program": t.program_id,
            "academic_year": str(t.academic_year),
            "application_fee": str(t.application_fee),
            "course_fee": str(t.course_fee),
            "registration_fee": str(t.registration_fee),
            "other_fee": str(t.other_fee),
            "total_fee": str(t.total_fee),
            "notes": t.notes,
        }
    return list(rows.values())


# The bucket that holds every program no university confers. It is not a
# University row and must never become one — both institutes' 2026 terms
# say in writing that JD "does not award or confer academic degrees". It
# exists so the 40-odd JD-certified programs remain reachable from a
# form whose first question is "which university?".
JD_UNIVERSITY = {
    "id": None,
    "code": "JD",
    "name": "JD Certified (no university affiliation)",
}


def _university_options(programs: list[dict]) -> list[dict]:
    """The university dropdown, derived from the programs actually on
    offer so no option can be picked into an empty program list.

    Ordered alphabetically with the JD bucket pinned last — it is the
    catch-all, not a peer of the degree-awarding bodies.
    """
    seen: dict[int, dict] = {}
    has_jd = False
    for p in programs:
        if p["university"] is None:
            has_jd = True
            continue
        seen.setdefault(p["university"], {
            "id": p["university"],
            "code": p["university_code"],
            "name": p["university_name"],
        })
    options = sorted(seen.values(), key=lambda u: u["name"])
    if has_jd:
        options.append(dict(JD_UNIVERSITY))
    return options


def _prefill(lead: Lead) -> dict:
    """Minimal payload the public form needs — never leaks lead status,
    history, internal ids beyond what the student already typed."""
    from apps.master.models import Campus, City, Program, State

    # Programs need their campus links so the form can filter the
    # Program dropdown by selected Campus.
    # `institute` rides on the program because that is where it lives —
    # the form reads it off the selected program for branding/terms.
    # `university` is the degree-awarding body the student picks first;
    # it is NULL for JD-certified programs, which is a real answer
    # ("JD does not award or confer academic degrees") rather than
    # missing data — see the `University` model docstring.
    programs = []
    for p in (
        Program.objects.filter(is_active=True)
        .select_related("institute", "university")
        .prefetch_related("campuses")
        .order_by("name")
    ):
        programs.append({
            "id": p.id, "name": p.name, "code": p.code,
            "campus_ids": list(p.campuses.values_list("id", flat=True)),
            "institute": p.institute_id,
            "institute_code": p.institute.code if p.institute_id else "",
            "institute_name": p.institute.name if p.institute_id else "",
            "university": p.university_id,
            "university_code": p.university.code if p.university_id else JD_UNIVERSITY["code"],
            "university_name": p.university.name if p.university_id else JD_UNIVERSITY["name"],
        })

    universities = _university_options(programs)

    # If the student already submitted once, send their saved values
    # so the form can prefill for editing.
    existing = getattr(lead, "promoted_student", None)
    student_data = None
    if existing is not None:
        student_data = {
            "id": existing.id,
            "application_form_id": existing.application_form_id,
            "student_name": existing.student_name,
            "father_name": existing.father_name,
            "mother_name": existing.mother_name,
            "gender": existing.gender,
            "dob": existing.dob.isoformat() if existing.dob else None,
            "category": existing.category,
            "study_medium": existing.study_medium,
            "nationality": existing.nationality,
            "blood_group": existing.blood_group,
            "current_address": existing.current_address,
            "current_city": existing.current_city_id,
            "current_state": existing.current_state_id,
            "current_pincode": existing.current_pincode,
            "permanent_address": existing.permanent_address,
            "permanent_city": existing.permanent_city_id,
            "permanent_state": existing.permanent_state_id,
            "permanent_pincode": existing.permanent_pincode,
            "student_mobile": existing.student_mobile,
            "student_email": existing.student_email,
            "father_mobile": existing.father_mobile,
            "mother_mobile": existing.mother_mobile,
            "father_email": existing.father_email,
            "mother_email": existing.mother_email,
            "father_occupation": existing.father_occupation,
            "mother_occupation": existing.mother_occupation,
            "campus": existing.campus_id,
            "program": existing.program_id,
            # Consent already given. The form seeds its checkboxes from
            # these, so a returning student isn't made to re-agree.
            "declaration_accepted_at": (
                existing.declaration_accepted_at.isoformat()
                if existing.declaration_accepted_at else None
            ),
            "rules_accepted_at": (
                existing.rules_accepted_at.isoformat()
                if existing.rules_accepted_at else None
            ),
            "documents": list(
                existing.documents.values(
                    "id", "header", "regno_yearpassing", "school_college",
                    "university_board", "certificate_no", "percent_obtained",
                )
            ),
        }

    return {
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        # Lock state — frontend uses this to render read-only when closed.
        "is_closed": lead.application_locked_for_student,
        "closed_at": (
            lead.application_locked_at.isoformat()
            if lead.application_locked_at else None
        ),
        # Defaults from the lead.
        "campus": {"id": lead.campus_id, "name": lead.campus.name,
                   "code": lead.campus.code},
        "program": {"id": lead.program_id, "name": lead.program.name,
                    "code": lead.program.code},
        # Institute comes from the PROGRAM, not the campus — a campus
        # hosts programs from several institutes, so it cannot name one.
        "institute": (
            {"id": lead.program.institute_id,
             "code": getattr(lead.program.institute, "code", ""),
             "name": getattr(lead.program.institute, "name", "")}
            if lead.program_id and lead.program.institute_id else None
        ),
        # Previously-saved student values (None on first visit).
        "student": student_data,
        # Declaration + rules + disclaimer, served rather than duplicated
        # in the frontend so the form, the portal and the PDF all show
        # the same wording. See apps/admissions/application_terms.py.
        "terms": terms_for(
            getattr(lead.program.institute, "code", "")
            if lead.program_id and lead.program.institute_id else "",
        ),
        # Reference data the form needs — bundled here so the form
        # makes a single round-trip and stays unauthenticated.
        "campuses": list(
            Campus.objects.filter(is_active=True)
            .values("id", "name", "code").order_by("name")
        ),
        "programs": programs,
        # Asked before Program — a student knows which university's
        # degree they want long before they know our program codes.
        "universities": universities,
        # Headline fee numbers per (campus, program) — the form shows the
        # one matching the student's current selection.
        "fee_structures": _fee_structures(),
        "states": list(
            State.objects.values("id", "name", "code").order_by("name")
        ),
        "cities": list(
            City.objects.filter(is_active=True)
            .values("id", "name", "state").order_by("name")
        ),
    }
