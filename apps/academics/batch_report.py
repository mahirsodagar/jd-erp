"""Batch Report module — read-only batch listing (headcount + mentor +
feedback-link management) plus the per-batch student roster modal.

Ports the legacy PHP ``academics/batch_report.php`` flow: filter by
Academic Year + Campus + Program, list every batch with its active
headcount, mentor, and feedback-link fields; clicking a batch opens the
full student roster. The two inline actions (edit feedback link, toggle
enable) write back to ``Batch.feedback_link`` / ``feedback_link_enabled``.

Headcount convention: "total students" = ACTIVE enrolments for the
batch (mirrors the legacy ``active_status=0`` filter).
"""

from django.db.models import Count

from apps.admissions.models import Enrollment
from apps.master.models import Batch


def batch_list(*, academic_year=None, campus=None, program=None) -> list[dict]:
    """Every batch matching the year/campus/program filter, with its
    active-enrolment headcount, mentor, and feedback-link fields."""
    qs = (Batch.objects
          .select_related("program", "campus", "academic_year", "mentor")
          .order_by("name"))
    if academic_year:
        qs = qs.filter(academic_year_id=academic_year)
    if campus:
        qs = qs.filter(campus_id=campus)
    if program:
        qs = qs.filter(program_id=program)

    counts = dict(
        Enrollment.objects
        .filter(batch__in=qs, status=Enrollment.Status.ACTIVE)
        .values_list("batch_id")
        .annotate(total=Count("id"))
    )

    return [
        {
            "batch_id": b.id,
            "batch_name": b.name,
            "short_name": b.short_name,
            "program": b.program.name,
            "campus": b.campus.name,
            "academic_year": b.academic_year.code,
            "mentor": b.mentor.full_name if b.mentor_id else "",
            "total_students": counts.get(b.id, 0),
            "feedback_link": b.feedback_link,
            "feedback_link_enabled": b.feedback_link_enabled,
        }
        for b in qs
    ]


def batch_roster(batch) -> dict:
    """Full student roster for one batch — the 17-column modal table.

    Rows come from the batch's ACTIVE enrolments, ordered by student
    name."""
    enrolments = (Enrollment.objects
                  .filter(batch=batch, status=Enrollment.Status.ACTIVE)
                  .select_related("student", "student__program",
                                  "student__campus")
                  .order_by("student__student_name"))
    rows = []
    for e in enrolments:
        s = e.student
        rows.append({
            "student_id": s.id,
            "application_form_id": s.application_form_id,
            "registration_number": s.registration_number,
            "name": s.student_name,
            "mobile": s.student_mobile,
            "email": s.student_email,
            "institute_email": s.institute_email,
            "dob": str(s.dob) if s.dob else None,
            "blood_group": s.blood_group,
            "father_name": s.father_name,
            "father_mobile": s.father_mobile,
            "mother_name": s.mother_name,
            "mother_mobile": s.mother_mobile,
            "category": s.get_category_display(),
            "current_address": s.current_address,
            "permanent_address": s.permanent_address,
            "program": s.program.name,
            "campus": s.campus.name,
        })
    return {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "program": batch.program.name,
        "campus": batch.campus.name,
        "rows": rows,
    }
