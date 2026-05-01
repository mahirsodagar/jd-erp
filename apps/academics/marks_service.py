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
