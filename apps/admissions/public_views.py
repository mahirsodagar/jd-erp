"""Public, no-auth endpoints used by the self-fill application form.

Mounted under `/api/public/application/<token>/` — see config/urls.py.
The token is a one-shot UUID stored on `Lead.application_token`,
generated when staff clicks "Send application link". Cleared on submit.
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
    from apps.master.models import City, State
    return {
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "campus": {"id": lead.campus_id, "name": lead.campus.name,
                   "code": lead.campus.code},
        "program": {"id": lead.program_id, "name": lead.program.name,
                    "code": lead.program.code},
        "institute": (
            {"id": lead.campus.institute_id,
             "name": getattr(lead.campus.institute, "name", "")}
            if lead.campus.institute_id else None
        ),
        # Reference data the form needs — bundled here so the form
        # makes a single round-trip and stays unauthenticated.
        "states": list(
            State.objects.values("id", "name", "code").order_by("name")
        ),
        "cities": list(
            City.objects.filter(is_active=True)
            .values("id", "name", "state").order_by("name")
        ),
    }
