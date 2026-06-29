"""Entrance-exam orchestration: total_marks recompute, MCQ auto-grade,
score finalization, mapping to leads, reporting.

Mirrors apps/academics/test_service.py, retargeted to leads.Lead.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .exam_models import (
    EntranceExam, EntranceExamAttempt, EntranceExamQuestion,
    EntranceExamResponse,
)


def recompute_total_marks(exam: EntranceExam) -> EntranceExam:
    total = exam.questions.aggregate(s=Sum("marks"))["s"] or Decimal("0")
    if exam.total_marks != total:
        exam.total_marks = total
        exam.save(update_fields=["total_marks", "updated_at"])
    return exam


# --- MCQ auto-grade --------------------------------------------------

def _auto_grade(question: EntranceExamQuestion, response_text: str) -> Decimal:
    if question.type != EntranceExamQuestion.Type.MCQ:
        return Decimal("0")
    if not question.answer_key:
        return Decimal("0")
    return question.marks if response_text == question.answer_key else Decimal("0")


@transaction.atomic
def submit_attempt(*, attempt: EntranceExamAttempt, answers: list[dict]) -> dict:
    """Persist candidate answers, auto-grade MCQ, set attempt to SUBMITTED.

    answers = [{"question": <id>, "answer": <str>}, ...]
    Unknown question ids and answers from outside this exam are ignored.
    """
    valid_qs = {q.id: q for q in attempt.exam.questions.all()}

    auto_total = Decimal("0")
    has_short = False
    for a in answers:
        qid = a.get("question")
        ans = a.get("answer", "")
        q = valid_qs.get(qid)
        if q is None:
            continue
        is_mcq = (q.type == EntranceExamQuestion.Type.MCQ)
        marks = _auto_grade(q, ans) if is_mcq else None
        EntranceExamResponse.objects.update_or_create(
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
        attempt.status = EntranceExamAttempt.Status.SUBMITTED
        attempt.total_score = None  # finalized after review
    else:
        attempt.status = EntranceExamAttempt.Status.GRADED
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
def review_response(*, response: EntranceExamResponse, marks_awarded: Decimal,
                    feedback: str, reviewed_by) -> EntranceExamResponse:
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


def _maybe_finalize(attempt: EntranceExamAttempt) -> None:
    """Move attempt to GRADED when every response has marks_awarded set."""
    pending = attempt.responses.filter(marks_awarded__isnull=True).count()
    if pending:
        return
    total = attempt.responses.aggregate(s=Sum("marks_awarded"))["s"] or Decimal("0")
    attempt.total_score = total
    attempt.status = EntranceExamAttempt.Status.GRADED
    attempt.save(update_fields=["total_score", "status", "updated_at"])


# --- Window helpers --------------------------------------------------

def can_attempt_now(attempt: EntranceExamAttempt) -> tuple[bool, str]:
    now = timezone.now()
    if attempt.exam.status != EntranceExam.Status.PUBLISHED:
        return False, f"Exam is {attempt.exam.status} (must be PUBLISHED)."
    if now < attempt.start_dt:
        return False, "Window has not opened yet."
    if now > attempt.end_dt:
        return False, "Window has closed."
    if attempt.status == EntranceExamAttempt.Status.SUBMITTED:
        return False, "Already submitted."
    if attempt.status == EntranceExamAttempt.Status.GRADED:
        return False, "Already graded."
    return True, ""


# --- Mapping ---------------------------------------------------------

@transaction.atomic
def map_exam_to_leads(*, exam: EntranceExam, lead_ids: list[int],
                      start_dt, end_dt) -> dict:
    from .models import Lead
    created, skipped = [], []
    for lid in lead_ids:
        lead = Lead.objects.filter(pk=lid).first()
        if lead is None:
            skipped.append({"lead": lid, "reason": "not found"})
            continue
        if EntranceExamAttempt.objects.filter(exam=exam, lead=lead).exists():
            skipped.append({"lead": lid, "reason": "already mapped"})
            continue
        a = EntranceExamAttempt.objects.create(
            exam=exam, lead=lead,
            start_dt=start_dt, end_dt=end_dt,
        )
        created.append(a.id)
    return {"created": created, "skipped": skipped}


# --- Reports ---------------------------------------------------------

def exam_report(exam: EntranceExam) -> dict:
    rows = []
    for a in exam.attempts.select_related("lead").all():
        rows.append({
            "attempt_id": a.id,
            "lead_id": a.lead_id,
            "lead_name": a.lead.name,
            "lead_email": a.lead.email,
            "access_token": str(a.access_token),
            "status": a.status,
            "submitted_at": a.submitted_at,
            "total_score": str(a.total_score) if a.total_score is not None else None,
        })
    rows.sort(key=lambda r: -(float(r["total_score"]) if r["total_score"] else -1))
    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "program": exam.program.name if exam.program_id else None,
        "total_marks": str(exam.total_marks),
        "attempts": rows,
    }
