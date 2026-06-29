"""Business logic for Lesson plans + their two-reviewer approval flow."""

from django.db import transaction
from django.utils import timezone

from .models import Lesson


# Decisions a reviewer may record.
_DECISIONS = {
    Lesson.ReviewStatus.APPROVED,
    Lesson.ReviewStatus.REJECTED,
    Lesson.ReviewStatus.IMPROVE,
}


@transaction.atomic
def review_lesson(*, lesson: Lesson, role: str, decision: str,
                  remarks: str = "", reviewer) -> Lesson:
    """Record one reviewer's decision (role = 'HOD' or 'MENTOR')."""
    if decision not in _DECISIONS:
        raise ValueError("decision must be APPROVED, REJECTED or IMPROVE.")

    now = timezone.now()
    if role == "HOD":
        lesson.hod_status = decision
        lesson.hod_remarks = remarks or ""
        lesson.hod_decided_at = now
        fields = ["hod_status", "hod_remarks", "hod_decided_at", "updated_at"]
    elif role == "MENTOR":
        lesson.mentor_status = decision
        lesson.mentor_remarks = remarks or ""
        lesson.mentor_decided_at = now
        fields = ["mentor_status", "mentor_remarks", "mentor_decided_at",
                  "updated_at"]
    else:
        raise ValueError("role must be HOD or MENTOR.")

    lesson.save(update_fields=fields)
    return lesson


@transaction.atomic
def reset_reviews(*, lesson: Lesson) -> Lesson:
    """Send a lesson back to PENDING for both reviewers — used when the
    author edits content after a decision so the plan is re-reviewed."""
    lesson.hod_status = Lesson.ReviewStatus.PENDING
    lesson.hod_decided_at = None
    lesson.mentor_status = Lesson.ReviewStatus.PENDING
    lesson.mentor_decided_at = None
    lesson.save(update_fields=[
        "hod_status", "hod_decided_at",
        "mentor_status", "mentor_decided_at", "updated_at",
    ])
    return lesson
