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

from .services import submit_application_from_lead


def _resolve_lead(token: str) -> Lead:
    try:
        lead = Lead.objects.select_related(
            "campus", "program", "campus__institute",
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
            "documents": documents,
            "_photo_file": request.FILES.get("photo"),
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


def _prefill(lead: Lead) -> dict:
    """Minimal payload the public form needs — never leaks lead status,
    history, internal ids beyond what the student already typed."""
    from apps.master.models import Campus, City, Program, State

    # Programs need their campus links so the form can filter the
    # Program dropdown by selected Campus.
    programs = []
    for p in (
        Program.objects.filter(is_active=True)
        .prefetch_related("campuses")
        .order_by("name")
    ):
        programs.append({
            "id": p.id, "name": p.name, "code": p.code,
            "campus_ids": list(p.campuses.values_list("id", flat=True)),
        })

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
        "institute": (
            {"id": lead.campus.institute_id,
             "code": getattr(lead.campus.institute, "code", ""),
             "name": getattr(lead.campus.institute, "name", "")}
            if lead.campus.institute_id else None
        ),
        # Previously-saved student values (None on first visit).
        "student": student_data,
        # Reference data the form needs — bundled here so the form
        # makes a single round-trip and stays unauthenticated.
        "campuses": list(
            Campus.objects.filter(is_active=True)
            .values("id", "name", "code", "institute").order_by("name")
        ),
        "programs": programs,
        "states": list(
            State.objects.values("id", "name", "code").order_by("name")
        ),
        "cities": list(
            City.objects.filter(is_active=True)
            .values("id", "name", "state").order_by("name")
        ),
    }
