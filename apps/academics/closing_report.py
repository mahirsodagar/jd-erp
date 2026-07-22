"""Closing Report module — the batch-closure completion sheet.

Ports the legacy PHP ``academics/closing_report.php`` flow. For one
batch it composes a single document:

  A. Batch header  — name, class mentor, course duration, start/end
     dates (derived from the batch's scheduled-slot date extremes).
  B. Mentor details — one row per module actually taught to the batch,
     with the instructor(s) who taught it and the teaching start/end.
  C. Student awards — one row per ACTIVE / ALUMNI student with a
     computed attendance %, plus the editable Awards / Portfolio /
     Remarks fields (stored in ``ClosingAward``).

Attendance % follows the same convention as the rest of the Academics
reporting suite (Attendance Report / Batch Report): "present-like" =
PRESENT + LATE + ON_DUTY over the rows actually marked.
"""

from django.db.models import Count, Max, Min, Q

from apps.admissions.models import Enrollment
from apps.master.models import Batch

from .models import Attendance, ClosingAward, ScheduleSlot

PRESENT_LIKE = ("PRESENT", "LATE", "ON_DUTY")

# Students shown on a closing sheet: active + alumni (legacy
# `enrollment_status IN (1,5)`, mapped to this schema's Status codes).
CLOSING_STATUSES = (Enrollment.Status.ACTIVE, Enrollment.Status.ALUMNI)


def _pct(present: int, total: int) -> int:
    return round(present / total * 100) if total else 0


def _duration(first, last) -> str:
    """Human course duration between two dates, e.g. "1 year, 5 months"."""
    if not first or not last:
        return ""
    months = (last.year - first.year) * 12 + (last.month - first.month)
    if last.day < first.day:
        months -= 1
    months = max(months, 0)
    years, rem = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if rem or not years:
        parts.append(f"{rem} month{'s' if rem != 1 else ''}")
    return ", ".join(parts)


def closing_report(batch) -> dict:
    slots = ScheduleSlot.objects.filter(
        batch=batch, status=ScheduleSlot.Status.SCHEDULED,
    )

    # --- A. Batch header ---------------------------------------------
    span = slots.aggregate(first=Min("date"), last=Max("date"))
    header = {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "mentor": batch.mentor.full_name if batch.mentor_id else "",
        "program": batch.program.name,
        "campus": batch.campus.name,
        "academic_year": batch.academic_year.code,
        "start_date": str(span["first"]) if span["first"] else None,
        "end_date": str(span["last"]) if span["last"] else None,
        "duration": _duration(span["first"], span["last"]),
    }

    # --- B. Mentor details (one row per module taught) ---------------
    modules = (slots
               .values("subject_id", "subject__name", "subject__code")
               .annotate(first=Min("date"), last=Max("date"))
               .order_by("subject__code"))
    # instructor names per subject (distinct) — `full_name` is a model
    # property, so resolve it off the Employee instance rather than in
    # a `.values()` projection.
    from collections import defaultdict
    by_subject: dict[int, set] = defaultdict(set)
    for slot in slots.select_related("instructor").only(
        "subject_id", "instructor__first_name",
        "instructor__middle_name", "instructor__family_name",
    ):
        name = slot.instructor.full_name
        if name:
            by_subject[slot.subject_id].add(name)
    mentor_details = [
        {
            "subject_id": m["subject_id"],
            "course_name": m["subject__name"],
            "code": m["subject__code"],
            "mentors": " / ".join(sorted(by_subject.get(m["subject_id"], []))),
            "start_date": str(m["first"]) if m["first"] else None,
            "end_date": str(m["last"]) if m["last"] else None,
        }
        for m in modules
    ]

    # --- C. Students + attendance % + awards -------------------------
    roster = (Enrollment.objects
              .filter(batch=batch, status__in=CLOSING_STATUSES)
              .select_related("student")
              .order_by("student__student_name"))
    student_ids = [e.student_id for e in roster]

    att = (Attendance.objects
           .filter(schedule_slot__batch=batch, student_id__in=student_ids)
           .values("student_id")
           .annotate(
               present=Count("id", filter=Q(status__in=PRESENT_LIKE)),
               total=Count("id"),
           ))
    att_by_student = {a["student_id"]: (a["present"], a["total"]) for a in att}

    awards_by_student = {
        a.student_id: a
        for a in ClosingAward.objects.filter(batch=batch,
                                             student_id__in=student_ids)
    }

    students = []
    for e in roster:
        s = e.student
        present, total = att_by_student.get(s.id, (0, 0))
        aw = awards_by_student.get(s.id)
        students.append({
            "student_id": s.id,
            "application_form_id": s.application_form_id,
            "name": s.student_name,
            "attendance_pct": _pct(present, total),
            "awards": aw.awards if aw else "",
            "portfolio": aw.portfolio if aw else "",
            "remarks": aw.remarks if aw else "",
        })

    return {
        "header": header,
        "mentor_details": mentor_details,
        "students": students,
    }


def save_award(*, student, batch, user=None, **fields) -> ClosingAward:
    """Upsert the awards / portfolio / remarks for one (student, batch).

    ``fields`` may contain any of ``awards`` / ``portfolio`` /
    ``remarks``; only the supplied ones are written."""
    allowed = {k: (v or "").strip()
               for k, v in fields.items()
               if k in ("awards", "portfolio", "remarks")}
    obj, created = ClosingAward.objects.get_or_create(
        student=student, batch=batch,
        defaults={**allowed, "created_by": user},
    )
    if not created and allowed:
        for k, v in allowed.items():
            setattr(obj, k, v)
        obj.save(update_fields=[*allowed.keys(), "updated_at"])
    return obj
