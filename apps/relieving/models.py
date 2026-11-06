from django.conf import settings
from django.db import models


class RelievingManager(models.Model):
    """Relieving Managers master — one row per institute × level 1–4.

    Legacy `hrsave.php` hard-coded four approver mailboxes (Academic
    Manager → Vice Principal → Principal → Operations) for everyone.
    This master is the "one step up": HR picks the four approvers per
    institute from the employee list, with no deploy. Every application
    is routed through all four; `services.submit` refuses to route while
    any level is unset or its approver is inactive.
    """

    LEVELS = (1, 2, 3, 4)
    DEFAULT_LABELS = {
        1: "Academic Manager",
        2: "Vice Principal",
        3: "Principal",
        4: "Operations / HR",
    }

    institute = models.ForeignKey(
        "master.Institute", on_delete=models.PROTECT,
        related_name="relieving_managers",
    )
    level = models.PositiveSmallIntegerField()  # 1..4
    label = models.CharField(
        max_length=60,
        help_text="Shown as the level's title (e.g. 'Vice Principal').",
    )
    approver = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="relieving_manager_levels",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("institute", "level")
        unique_together = (("institute", "level"),)

    def __str__(self):
        return f"{self.institute_id} L{self.level} {self.label} → {self.approver_id}"


class RelievingApplication(models.Model):
    """Exit workflow. Submitted by the employee (or by HR on behalf),
    walks through the 4 approvals snapshotted at submission time from
    the institute's `RelievingManager` master. Completion of a RELIEVING
    application issues both letter numbers and mails the relieving
    letter; HR sends the experience letter separately. A PART_TIME
    application (legacy "Full time to Part time", rltype=2) runs the
    same chain but completion only records the decision — no letters,
    employee stays active.
    """

    class Type(models.TextChoices):
        RELIEVING = "RELIEVING", "Relieving"
        PART_TIME = "PART_TIME", "Full-time to Part-time"

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
    application_type = models.CharField(
        max_length=12, choices=Type.choices, default=Type.RELIEVING,
        db_index=True,
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
    # The experience letter is mailed separately by HR (legacy parity:
    # a manual button, typically after full & final settlement).
    experience_letter_sent_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def is_relieving(self) -> bool:
        return self.application_type == self.Type.RELIEVING


class RelievingApproval(models.Model):
    """Per-level approval row. Approver (and the level's label) are
    snapshotted from the institute's `RelievingManager` master at
    submission time so later master edits don't reroute already-pending
    applications."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        # Only when the level's approver is the applicant themselves
        # (e.g. the Principal resigning) — nobody approves their own exit.
        SKIPPED = "SKIPPED", "Skipped"

    application = models.ForeignKey(
        RelievingApplication, on_delete=models.CASCADE,
        related_name="approvals",
    )
    level = models.PositiveSmallIntegerField()  # 1..4
    label = models.CharField(max_length=60, blank=True)
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
