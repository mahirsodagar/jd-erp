from django.conf import settings
from django.db import models


class RelievingApplication(models.Model):
    """Exit workflow. Submitted by the employee (or by HR on behalf),
    walks through up to 4 manager approvals snapshotted at submission
    time, then HR finalizes and generates relieving + experience
    letters.
    """

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        IN_REVIEW = "IN_REVIEW", "In review"
        APPROVED = "APPROVED", "Approved (pending HR finalize)"
        COMPLETED = "COMPLETED", "Completed (letters issued)"
        REJECTED = "REJECTED", "Rejected"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="relieving_applications",
    )
    reason = models.TextField()
    last_working_date_requested = models.DateField()
    last_working_date_approved = models.DateField(
        null=True, blank=True,
        help_text="Set by HR at finalization. Used in the relieving letter.",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SUBMITTED,
        db_index=True,
    )

    # Rejection trail
    rejected_at_level = models.PositiveSmallIntegerField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Letter artefacts (numbers stamped at finalize; PDFs rendered on demand)
    relieving_letter_no = models.CharField(max_length=40, blank=True)
    experience_letter_no = models.CharField(max_length=40, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="relieving_finalized",
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="relieving_submissions",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-submitted_at",)
        indexes = [
            models.Index(fields=["employee", "status"]),
        ]
        constraints = [
            # Only one open application per employee at a time
            # (open = SUBMITTED, IN_REVIEW, APPROVED).
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(status__in=["SUBMITTED", "IN_REVIEW", "APPROVED"]),
                name="uniq_open_relieving_per_employee",
            ),
        ]

    def __str__(self):
        return f"Relieving {self.id} for {self.employee_id} ({self.status})"


class RelievingApproval(models.Model):
    """Per-level approval row. Approver is snapshotted from the
    employee's reporting_manager_<level> at submission time so later
    RM changes don't reroute already-pending applications."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SKIPPED = "SKIPPED", "Skipped (RM not configured)"

    application = models.ForeignKey(
        RelievingApplication, on_delete=models.CASCADE,
        related_name="approvals",
    )
    level = models.PositiveSmallIntegerField()  # 1..4
    approver = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="relieving_approvals",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="relieving_decisions",
    )
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("application", "level")
        unique_together = (("application", "level"),)
        indexes = [
            models.Index(fields=["approver", "status"]),
        ]

    def __str__(self):
        return f"L{self.level} of #{self.application_id} → {self.status}"
