"""Entrance-exam orchestration: total_marks recompute, MCQ auto-grade,
score finalization, mapping to leads, reporting.

Mirrors apps/academics/test_service.py, retargeted to leads.Lead.
"""

from datetime import timedelta
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
    # No result mail here: even an MCQ-only exam waits for staff to
    # decide Pass / Fail on the grading page (client, 2026-11-26).
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
    """Move attempt to GRADED when every response has marks_awarded set.
    The result (Pass / Fail) and its mail wait for `grade_attempt`."""
    pending = attempt.responses.filter(marks_awarded__isnull=True).count()
    if pending:
        return
    total = attempt.responses.aggregate(s=Sum("marks_awarded"))["s"] or Decimal("0")
    attempt.total_score = total
    attempt.status = EntranceExamAttempt.Status.GRADED
    attempt.save(update_fields=["total_score", "status", "updated_at"])


@transaction.atomic
def grade_attempt(*, attempt: EntranceExamAttempt, marks: list[dict],
                  result: str, actor) -> EntranceExamAttempt:
    """The grading page's single action (client, 2026-11-26): save every
    short-answer mark + feedback, total the attempt, and record the
    staff member's Pass / Fail decision — then mail the matching result.

    `marks` = [{"response": id, "marks_awarded": Decimal, "feedback": str}]
    for the SHORT-answer responses (MCQ rows keep their auto marks; a
    mark sent for one is applied too, so a staff override is possible).
    Every short response must end up marked. Once the result mail has
    gone out the decision is locked — a 400 tells staff so.
    """
    if attempt.status not in (EntranceExamAttempt.Status.SUBMITTED,
                              EntranceExamAttempt.Status.GRADED):
        raise ValueError("The candidate has not submitted this exam yet.")
    if result not in EntranceExamAttempt.Result.values:
        raise ValueError("result must be PASS or FAIL.")
    if attempt.result_mailed_at is not None and attempt.result != result:
        raise ValueError(
            f"The {attempt.get_result_display().lower()} result has already been "
            "mailed to the candidate; it can't be changed here.")

    by_id = {r.id: r for r in attempt.responses.select_related("question")}
    now = timezone.now()
    for m in marks:
        r = by_id.get(m["response"])
        if r is None:
            raise ValueError(f"Response {m['response']} is not part of this attempt.")
        awarded = Decimal(m["marks_awarded"])
        if awarded < 0:
            raise ValueError("Marks must be non-negative.")
        if awarded > r.question.marks:
            raise ValueError(
                f"Q{r.question.sort_order}: {awarded} exceeds the question's "
                f"maximum of {r.question.marks}.")
        r.marks_awarded = awarded
        r.feedback = (m.get("feedback") or "")
        r.reviewed_by = actor
        r.reviewed_at = now
        r.is_auto_graded = False
        r.save(update_fields=["marks_awarded", "feedback", "reviewed_by",
                              "reviewed_at", "is_auto_graded", "updated_at"])

    unmarked = [r for r in by_id.values() if r.marks_awarded is None]
    if unmarked:
        raise ValueError(
            "Enter marks for every question before deciding: "
            + ", ".join(f"Q{r.question.sort_order}" for r in unmarked))

    total = attempt.responses.aggregate(s=Sum("marks_awarded"))["s"] or Decimal("0")
    attempt.total_score = total
    attempt.status = EntranceExamAttempt.Status.GRADED
    attempt.result = result
    attempt.result_decided_at = now
    attempt.result_decided_by = actor
    attempt.save(update_fields=["total_score", "status", "result",
                                "result_decided_at", "result_decided_by",
                                "updated_at"])
    _notify_result(attempt, actor=actor)
    return attempt


def _notify_result(attempt: EntranceExamAttempt, *, actor=None) -> None:
    """Mail the Pass or Fail result once staff have decided it. Runs after
    the grading transaction commits so a rollback never leaves a mail
    behind, and a mail failure never undoes the grading."""
    from .send_links import send_entrance_exam_result

    def _go():
        try:
            send_entrance_exam_result(attempt=attempt, actor=actor)
        except Exception:  # noqa: BLE001 — logged; grading must stand
            import logging
            logging.getLogger("apps.leads").exception(
                "entrance exam result mail failed for attempt %s", attempt.pk)

    transaction.on_commit(_go)


# --- Window helpers --------------------------------------------------

#: Slack after `started_at + duration_min` for the browser's auto-submit
#: to reach us (slow networks, clock skew).
EXAM_SUBMIT_GRACE = timedelta(minutes=2)

def can_attempt_now(attempt: EntranceExamAttempt) -> tuple[bool, str]:
    now = timezone.now()
    if attempt.exam.status != EntranceExam.Status.PUBLISHED:
        return False, f"Exam is {attempt.exam.status} (must be PUBLISHED)."
    if now < attempt.start_dt:
        return False, "Window has not opened yet."
    if now > attempt.end_dt:
        return False, "Window has closed."
    # The timer is enforced here too, not only in the browser: once
    # started, answers are accepted until duration + a short grace for
    # the auto-submit round trip (2026-11-27).
    if attempt.started_at and attempt.exam.duration_min:
        deadline = (attempt.started_at
                    + timedelta(minutes=attempt.exam.duration_min)
                    + EXAM_SUBMIT_GRACE)
        if now > deadline:
            return False, "Time is up for this attempt."
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
            "result": a.result or None,
            "result_mailed_at": a.result_mailed_at,
        })
    rows.sort(key=lambda r: -(float(r["total_score"]) if r["total_score"] else -1))
    return {
        "exam_id": exam.id,
        "exam_name": exam.name,
        "program": exam.program.name if exam.program_id else None,
        "total_marks": str(exam.total_marks),
        "attempts": rows,
    }
