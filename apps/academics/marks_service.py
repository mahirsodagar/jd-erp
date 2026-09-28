"""Submission grading + marks publish + transcript helpers."""

from django.db import transaction
from django.utils import timezone

from .models import AssignmentSubmission, MarksEntry


def submission_status_after_save(sub: AssignmentSubmission) -> str:
    """Compute the right status for a submission based on timing.
    Called when a student creates / updates their submission."""
    if sub.grade is not None:
        return AssignmentSubmission.Status.GRADED
    deadline = sub.extended_due_date or sub.assignment.due_date
    if sub.submitted_at and deadline and sub.submitted_at > deadline:
        return AssignmentSubmission.Status.LATE
    return AssignmentSubmission.Status.SUBMITTED


@transaction.atomic
def grade_submission(*, submission: AssignmentSubmission,
                     grade, feedback: str, graded_by) -> AssignmentSubmission:
    if grade is not None:
        if float(grade) < 0:
            raise ValueError("Grade must be non-negative.")
        if submission.assignment.max_marks and float(grade) > float(
            submission.assignment.max_marks
        ):
            raise ValueError(
                f"Grade {grade} exceeds max_marks "
                f"{submission.assignment.max_marks}."
            )
    submission.grade = grade
    submission.feedback = feedback or ""
    submission.graded_by = graded_by
    submission.graded_at = timezone.now()
    submission.status = AssignmentSubmission.Status.GRADED
    submission.save(update_fields=[
        "grade", "feedback", "graded_by", "graded_at", "status", "updated_at",
    ])
    return submission


# --- Marks publishing -------------------------------------------------

@transaction.atomic
def publish_marks(*, marks: MarksEntry, by_user) -> MarksEntry:
    marks.published = True
    marks.published_at = timezone.now()
    marks.published_by = by_user
    marks.save(update_fields=[
        "published", "published_at", "published_by", "updated_at",
    ])
    return marks


@transaction.atomic
def unpublish_marks(*, marks: MarksEntry, by_user) -> MarksEntry:
    marks.published = False
    marks.published_at = None
    marks.published_by = None
    marks.save(update_fields=[
        "published", "published_at", "published_by", "updated_at",
    ])
    return marks


# --- Batch marks sheet ------------------------------------------------
# Port of legacy academics/marksentry.php: one grid per (batch, semester,
# subject) with IA + EA per student. Legacy saved cell-by-cell with no
# server validation; here the whole sheet saves atomically.

def marks_sheet_roster(*, batch, subject):
    """Active enrollments in the batch; an elective narrows to the
    students who picked it (same rule as the attendance roster)."""
    from apps.admissions.models import Enrollment

    from .attendance_service import _elective_ids

    qs = (Enrollment.objects
          .filter(batch=batch, status=Enrollment.Status.ACTIVE)
          .select_related("student")
          .order_by("student__student_name"))
    if not subject.is_elective:
        return list(qs)
    wanted = str(subject.id)
    return [e for e in qs if wanted in _elective_ids(e.elective_subjects)]


def marks_sheet(*, batch, semester, subject) -> dict:
    """Roster + existing marks for one sheet. Students who already have
    marks but are no longer active in the batch are still listed."""
    existing = {
        m.student_id: m
        for m in MarksEntry.objects.filter(
            subject=subject, semester=semester, batch=batch,
        ).select_related("student")
    }
    students = {e.student_id: e.student
                for e in marks_sheet_roster(batch=batch, subject=subject)}
    for sid, m in existing.items():
        students.setdefault(sid, m.student)

    first = next(iter(existing.values()), None)
    ia_max = first.ia_max if first else MarksEntry._meta.get_field("ia_max").default
    ea_max = first.ea_max if first else MarksEntry._meta.get_field("ea_max").default

    def s(v):
        return None if v is None else str(v)

    rows = []
    for sid, st in sorted(students.items(),
                          key=lambda kv: (kv[1].student_name or "").lower()):
        m = existing.get(sid)
        rows.append({
            "student_id": sid,
            "application_form_id": st.application_form_id,
            "name": st.student_name,
            "marks_id": m.id if m else None,
            "ia_marks": s(m.ia_marks) if m else None,
            "ea_marks": s(m.ea_marks) if m else None,
            "published": bool(m and m.published),
        })
    return {"ia_max": str(ia_max), "ea_max": str(ea_max), "rows": rows}


@transaction.atomic
def save_marks_sheet(*, batch, semester, subject, ia_max, ea_max, rows,
                     entered_by, can_edit_published: bool,
                     publish: bool) -> dict:
    """Upsert every row of a sheet. Raises ValueError({student: msg})
    before writing anything if a mark is out of range."""
    allowed = {e.student_id
               for e in marks_sheet_roster(batch=batch, subject=subject)}
    existing = {
        m.student_id: m
        for m in MarksEntry.objects.select_for_update().filter(
            subject=subject, semester=semester,
        )
    }
    allowed |= {sid for sid, m in existing.items() if m.batch_id == batch.id}

    errors = {}
    for r in rows:
        for key, cap in (("ia_marks", ia_max), ("ea_marks", ea_max)):
            v = r.get(key)
            if v is not None and not (0 <= v <= cap):
                label = "IA" if key == "ia_marks" else "EA"
                errors[r["student"]] = f"{label} must be between 0 and {cap}."
    if errors:
        raise ValueError(errors)

    saved, skipped = [], []
    for r in rows:
        sid = r["student"]
        ia, ea = r.get("ia_marks"), r.get("ea_marks")
        m = existing.get(sid)
        if sid not in allowed:
            skipped.append({"student": sid, "reason": "not in batch roster"})
            continue
        if m and m.batch_id != batch.id:
            skipped.append({"student": sid,
                            "reason": "marks already entered under another batch"})
            continue
        if m and m.published and not can_edit_published:
            skipped.append({"student": sid, "reason": "published"})
            continue
        if m is None and ia is None and ea is None:
            continue  # nothing entered, nothing to create
        if m is None:
            m = MarksEntry(student_id=sid, subject=subject, semester=semester,
                           batch=batch, entered_by=entered_by)
        m.ia_marks, m.ea_marks = ia, ea
        m.ia_max, m.ea_max = ia_max, ea_max
        m.save()
        existing[sid] = m
        saved.append(m.id)

    published = 0
    if publish:
        now = timezone.now()
        published = MarksEntry.objects.filter(
            subject=subject, semester=semester, batch=batch, published=False,
        ).update(published=True, published_at=now, published_by=entered_by,
                 updated_at=now)
    return {"saved": len(saved), "skipped": skipped, "published": published}


@transaction.atomic
def set_marks_sheet_published(*, batch, semester, subject, publish: bool,
                              by_user) -> int:
    qs = MarksEntry.objects.filter(
        subject=subject, semester=semester, batch=batch, published=not publish,
    )
    now = timezone.now()
    if publish:
        return qs.update(published=True, published_at=now,
                         published_by=by_user, updated_at=now)
    return qs.update(published=False, published_at=None, published_by=None,
                     updated_at=now)


# --- Transcript -------------------------------------------------------

def build_transcript(*, student, only_published: bool = True) -> dict:
    """Returns per-semester breakdown + overall aggregate.

    only_published=True is the student-facing default; faculty/HOD can
    pass False to see drafts."""
    qs = MarksEntry.objects.filter(student=student).select_related(
        "subject", "semester", "batch",
    )
    if only_published:
        qs = qs.filter(published=True)

    by_sem: dict[int, dict] = {}
    for m in qs:
        sem = m.semester
        bucket = by_sem.setdefault(sem.id, {
            "semester_id": sem.id,
            "semester_number": sem.number,
            "semester_name": sem.name,
            "subjects": [],
            "total_marks": 0.0,
            "total_max": 0.0,
        })
        bucket["subjects"].append({
            "subject_id": m.subject.id,
            "subject_code": m.subject.code,
            "subject_name": m.subject.name,
            "ia_marks": str(m.ia_marks) if m.ia_marks is not None else None,
            "ia_max": str(m.ia_max),
            "ea_marks": str(m.ea_marks) if m.ea_marks is not None else None,
            "ea_max": str(m.ea_max),
            "total": m.total_marks,
            "max": m.total_max,
            "percentage": m.percentage,
            "published": m.published,
        })
        bucket["total_marks"] += m.total_marks
        bucket["total_max"] += m.total_max

    semesters = []
    overall_marks = overall_max = 0.0
    for sem_id in sorted(by_sem.keys()):
        b = by_sem[sem_id]
        b["percentage"] = (
            round((b["total_marks"] / b["total_max"]) * 100, 2)
            if b["total_max"] else 0.0
        )
        b["total_marks"] = round(b["total_marks"], 2)
        b["total_max"] = round(b["total_max"], 2)
        overall_marks += b["total_marks"]
        overall_max += b["total_max"]
        semesters.append(b)

    return {
        "student_id": student.id,
        "name": student.student_name,
        "application_form_id": student.application_form_id,
        "semesters": semesters,
        "overall": {
            "total_marks": round(overall_marks, 2),
            "total_max": round(overall_max, 2),
            "percentage": (round((overall_marks / overall_max) * 100, 2)
                            if overall_max else 0.0),
        },
    }
