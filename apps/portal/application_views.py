"""The student's submitted application form, read-only.

Same record the public form wrote (`admissions.public_views`), played
back through the portal so a student can check what they declared without
being able to change it. Strictly a GET: corrections go through the
admissions office, which is what keeps the form a permanent record.

Values are returned both raw and as `*_display` labels, because the form
stores codes (`M`, `GEN`, `SSLC`) that mean nothing to a student.
"""

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admissions.models import Student, StudentDocument

from .permissions import IsStudentOrParent

#: Human labels for the coded columns, taken from the model's own
#: choices so a new option can never silently render as its code.
_GENDER = dict(Student.Gender.choices)
_MEDIUM = dict(Student.StudyMedium.choices)
_CATEGORY = dict(Student.Category.choices)
_NATIONALITY = dict(Student.Nationality.choices)
_DOC_HEADER = dict(StudentDocument.Header.choices)


def _file_url(request, filefield):
    if not filefield:
        return None
    return request.build_absolute_uri(filefield.url)


class ApplicationFormView(APIView):
    """`GET /api/portal/application/` — the filled form, read-only."""

    permission_classes = [IsStudentOrParent]

    def get(self, request):
        ctx = request.portal_ctx
        s = (
            Student.objects
            .select_related(
                "institute", "campus", "program", "course", "academic_year",
                "current_city", "current_state",
                "permanent_city", "permanent_state",
                "lead_origin",
            )
            .get(pk=ctx.student.pk)
        )

        documents = [
            {
                "id": d.id,
                "header": d.header,
                "header_display": _DOC_HEADER.get(d.header, d.header),
                "regno_yearpassing": d.regno_yearpassing,
                "school_college": d.school_college,
                "university_board": d.university_board,
                "certificate_no": d.certificate_no,
                "percent_obtained": (
                    str(d.percent_obtained)
                    if d.percent_obtained is not None else None
                ),
                "file_url": _file_url(request, d.file),
                "uploaded_on": d.uploaded_on.isoformat(),
            }
            for d in s.documents.all().order_by("id")
        ]

        lead = s.lead_origin
        return Response({
            "application_form_id": s.application_form_id,
            "registration_number": s.registration_number,
            "submitted_on": s.created_on.isoformat(),
            "last_updated_on": s.updated_on.isoformat(),
            "photo_url": _file_url(request, s.photo),

            "placement": {
                "institute_name": s.institute.name,
                "campus_name": s.campus.name,
                "program_name": s.program.name,
                "course_name": getattr(s.course, "name", None),
                "academic_year": s.academic_year.code,
            },
            "personal": {
                "student_name": s.student_name,
                "dob": s.dob.isoformat() if s.dob else None,
                "gender": s.gender,
                "gender_display": _GENDER.get(s.gender, s.gender),
                "category": s.category,
                "category_display": _CATEGORY.get(s.category, s.category),
                "study_medium": s.study_medium,
                "study_medium_display": _MEDIUM.get(s.study_medium, s.study_medium),
                "nationality": s.nationality,
                "nationality_display": _NATIONALITY.get(s.nationality, s.nationality),
                "blood_group": s.blood_group,
            },
            "family": {
                "father_name": s.father_name,
                "father_mobile": s.father_mobile,
                "father_email": s.father_email,
                "father_occupation": s.father_occupation,
                "mother_name": s.mother_name,
                "mother_mobile": s.mother_mobile,
                "mother_email": s.mother_email,
                "mother_occupation": s.mother_occupation,
            },
            "contact": {
                "student_mobile": s.student_mobile,
                "student_email": s.student_email,
                "institute_email": s.institute_email,
            },
            "current_address": {
                "address": s.current_address,
                "city": getattr(s.current_city, "name", None),
                "state": getattr(s.current_state, "name", None),
                "pincode": s.current_pincode,
            },
            "permanent_address": {
                "address": s.permanent_address,
                "city": getattr(s.permanent_city, "name", None),
                "state": getattr(s.permanent_state, "name", None),
                "pincode": s.permanent_pincode,
            },
            "documents": documents,
            # Application fee, when this student came in through a lead.
            # Absent for students created directly by staff.
            "application_fee": None if lead is None else {
                "paid": lead.application_fee_paid_at is not None,
                "paid_at": (
                    lead.application_fee_paid_at.isoformat()
                    if lead.application_fee_paid_at else None
                ),
                "amount": (
                    str(lead.application_fee_amount)
                    if lead.application_fee_amount is not None else None
                ),
                "mode": lead.application_fee_mode,
                "reference": lead.application_fee_ref,
            },
        })
