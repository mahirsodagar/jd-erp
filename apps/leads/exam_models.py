"""Entrance Exam models for the Leads pipeline.

A near-clone of the academics Online-Test feature (apps/academics/models.py),
retargeted from admissions.Student to leads.Lead. Prospective candidates
have no user account, so each attempt carries a public `access_token`
used to take the exam from a tokenized link (mirrors the self-fill
application form on `Lead.application_token`).

These models live in the `leads` app and are re-exported from
`apps/leads/models.py` so Django registers them under the leads app_label.
"""

import uuid

from django.conf import settings
from django.db import models


class EntranceExam(models.Model):
    """Staff-built entrance exam, optionally tied to a Program. Question
    rows hang off this; per-lead `EntranceExamAttempt` rows are created
    when staff map the exam to leads."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    name = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    duration_min = models.PositiveSmallIntegerField(
        help_text="How long a candidate has once they start.",
    )
    program = models.ForeignKey(
        "master.Program", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="entrance_exams",
    )
    academic_year = models.ForeignKey(
        "master.AcademicYear", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="entrance_exams",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT,
    )
    total_marks = models.DecimalField(
        max_digits=5, decimal_places=1, default=0,
        help_text="Auto-recomputed from sum(question.marks).",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="entrance_exams_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["program", "status"]),
        ]

    def __str__(self):
        return f"{self.name} (entrance)"


class EntranceExamQuestion(models.Model):
    """A question in an EntranceExam."""

    class Type(models.TextChoices):
        MCQ = "MCQ", "Multiple Choice (single correct)"
        SHORT = "SHORT", "Short Answer"

    exam = models.ForeignKey(
        EntranceExam, on_delete=models.CASCADE, related_name="questions",
    )
    description = models.TextField()
    type = models.CharField(max_length=10, choices=Type.choices)
    options = models.JSONField(
        default=list, blank=True,
        help_text="MCQ: list of strings. SHORT: ignored.",
    )
    answer_key = models.CharField(
        max_length=200, blank=True,
        help_text="MCQ: index of correct option (0..N-1). "
                  "SHORT: optional reference answer for graders.",
    )
    marks = models.DecimalField(max_digits=5, decimal_places=1, default=1)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("exam", "sort_order", "id")

    def __str__(self):
        return f"Q{self.id} of {self.exam_id} ({self.type})"


class EntranceExamAttempt(models.Model):
    """One row per (exam, lead). Created when staff map the exam. The
    `access_token` is the key embedded in the public exam link."""

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        SUBMITTED = "SUBMITTED", "Submitted"
        GRADED = "GRADED", "Graded"

    exam = models.ForeignKey(
        EntranceExam, on_delete=models.CASCADE, related_name="attempts",
    )
    lead = models.ForeignKey(
        "leads.Lead", on_delete=models.PROTECT, related_name="exam_attempts",
    )

    access_token = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        help_text="UUID embedded in the public exam link.",
    )

    start_dt = models.DateTimeField(
        help_text="Earliest the candidate can start.",
    )
    end_dt = models.DateTimeField(
        help_text="Latest the candidate can submit.",
    )

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.NOT_STARTED,
    )
    total_score = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = (("exam", "lead"),)
        indexes = [
            models.Index(fields=["exam", "status"]),
            models.Index(fields=["lead", "status"]),
        ]

    def __str__(self):
        return f"{self.lead_id} attempt of {self.exam_id}"


class EntranceExamResponse(models.Model):
    """One row per (attempt, question)."""

    attempt = models.ForeignKey(
        EntranceExamAttempt, on_delete=models.CASCADE, related_name="responses",
    )
    question = models.ForeignKey(
        EntranceExamQuestion, on_delete=models.CASCADE, related_name="responses",
    )

    answer = models.TextField(
        blank=True,
        help_text="MCQ: chosen option index as string. SHORT: free text.",
    )
    marks_awarded = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
    )
    is_auto_graded = models.BooleanField(default=False)
    feedback = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="exam_responses_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("attempt", "question__sort_order")
        unique_together = (("attempt", "question"),)
        indexes = [
            models.Index(fields=["attempt", "is_auto_graded"]),
        ]

    def __str__(self):
        return f"resp {self.id} of attempt {self.attempt_id}"
