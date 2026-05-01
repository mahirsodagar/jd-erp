"""Online-test orchestration: total_marks recompute, MCQ auto-grade,
score finalization."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Test, TestAttempt, TestQuestion, TestResponse


def recompute_total_marks(test: Test) -> Test:
    total = test.questions.aggregate(s=Sum("marks"))["s"] or Decimal("0")
    if test.total_marks != total:
        test.total_marks = total
        test.save(update_fields=["total_marks", "updated_at"])
    return test


# --- MCQ auto-grade --------------------------------------------------

def _auto_grade(question: TestQuestion, response_text: str) -> Decimal:
    if question.type != TestQuestion.Type.MCQ:
        return Decimal("0")
    if not question.answer_key:
        return Decimal("0")
    return question.marks if response_text == question.answer_key else Decimal("0")


@transaction.atomic
def submit_attempt(*, attempt: TestAttempt, answers: list[dict]) -> dict:
    """Persist student answers, auto-grade MCQ, set attempt to SUBMITTED.

    answers = [{"question": <id>, "answer": <str>}, ...]
    Unknown question ids and answers from outside this test are ignored.
    """
    valid_qs = {q.id: q for q in attempt.test.questions.all()}

    auto_total = Decimal("0")
    has_short = False
    for a in answers:
        qid = a.get("question")
        ans = a.get("answer", "")
        q = valid_qs.get(qid)
        if q is None:
            continue
        is_mcq = (q.type == TestQuestion.Type.MCQ)
        marks = _auto_grade(q, ans) if is_mcq else None
        TestResponse.objects.update_or_create(
            attempt=attempt, question=q,
            defaults={
                "answer": ans,
                "marks_awarded": marks,
                "is_auto_graded": is_mcq,
            },
        )
        if is_mcq and marks is not None:
            auto_total += Decimal(marks)
        if not is_mcq:
            has_short = True

    attempt.submitted_at = timezone.now()
    if has_short:
        attempt.status = TestAttempt.Status.SUBMITTED
        attempt.total_score = None  # finalized after review
    else:
        attempt.status = TestAttempt.Status.GRADED
        attempt.total_score = auto_total
    attempt.save(update_fields=[
        "submitted_at", "status", "total_score", "updated_at",
    ])
    return {
        "status": attempt.status,
        "auto_score": str(auto_total),
        "pending_short_review": has_short,
    }


@transaction.atomic
def review_response(*, response: TestResponse, marks_awarded: Decimal,
                    feedback: str, reviewed_by) -> TestResponse:
    if marks_awarded < 0:
        raise ValueError("marks_awarded must be non-negative.")
    if marks_awarded > response.question.marks:
        raise ValueError(
            f"marks_awarded {marks_awarded} exceeds question max "
            f"{response.question.marks}."
        )
    response.marks_awarded = marks_awarded
    response.feedback = feedback or ""
    response.reviewed_by = reviewed_by
    response.reviewed_at = timezone.now()
    response.is_auto_graded = False  # manual review wins
    response.save(update_fields=[
        "marks_awarded", "feedback", "reviewed_by", "reviewed_at",
        "is_auto_graded", "updated_at",
    ])
    _maybe_finalize(response.attempt)
    return response


def _maybe_finalize(attempt: TestAttempt) -> None:
    """Move attempt to GRADED when every response has marks_awarded set."""
    pending = attempt.responses.filter(marks_awarded__isnull=True).count()
    if pending:
        return
    total = attempt.responses.aggregate(s=Sum("marks_awarded"))["s"] or Decimal("0")
    attempt.total_score = total
    attempt.status = TestAttempt.Status.GRADED
    attempt.save(update_fields=["total_score", "status", "updated_at"])


# --- Window helpers --------------------------------------------------

def can_attempt_now(attempt: TestAttempt) -> tuple[bool, str]:
    now = timezone.now()
    if attempt.test.status != Test.Status.PUBLISHED:
        return False, f"Test is {attempt.test.status} (must be PUBLISHED)."
    if now < attempt.start_dt:
        return False, "Window has not opened yet."
    if now > attempt.end_dt:
        return False, "Window has closed."
    if attempt.status == TestAttempt.Status.SUBMITTED:
        return False, "Already submitted."
    if attempt.status == TestAttempt.Status.GRADED:
        return False, "Already graded."
    return True, ""


# --- Mapping ---------------------------------------------------------

@transaction.atomic
def map_test_to_students(*, test: Test, student_ids: list[int],
                         start_dt, end_dt) -> dict:
    from apps.admissions.models import Student
    created, skipped = [], []
    for sid in student_ids:
        s = Student.objects.filter(pk=sid).first()
        if s is None:
            skipped.append({"student": sid, "reason": "not found"})
            continue
        if TestAttempt.objects.filter(test=test, student=s).exists():
            skipped.append({"student": sid, "reason": "already mapped"})
            continue
        a = TestAttempt.objects.create(
            test=test, student=s,
            start_dt=start_dt, end_dt=end_dt,
        )
        created.append(a.id)
    return {"created": created, "skipped": skipped}


# --- Reports ---------------------------------------------------------

def test_report(test: Test) -> dict:
    rows = []
    for a in test.attempts.select_related("student").all():
        rows.append({
            "attempt_id": a.id,
            "student_id": a.student_id,
            "student_name": a.student.student_name,
            "application_form_id": a.student.application_form_id,
            "status": a.status,
            "submitted_at": a.submitted_at,
            "total_score": str(a.total_score) if a.total_score is not None else None,
        })
    rows.sort(key=lambda r: -(float(r["total_score"]) if r["total_score"] else -1))
    return {
        "test_id": test.id,
        "test_name": test.name,
        "subject": test.subject.name,
        "total_marks": str(test.total_marks),
        "attempts": rows,
    }
