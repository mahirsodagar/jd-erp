from django.conf import settings
from django.db import models


class Task(models.Model):
    """Lightweight to-do mirrored from JD_ERP's `task_master`. A task
    has one creator and one assignee; both can see the task. The
    assignee writes a free-text `assignee_remarks` while working and
    flips the status to COMPLETED when done."""

    class Status(models.IntegerChoices):
        PENDING = 0, "Pending"
        COMPLETED = 1, "Completed"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    end_date = models.DateField(
        help_text="When the assignee is expected to finish.",
    )

    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="assigned_tasks",
    )
    assignee_remarks = models.TextField(
        blank=True,
        help_text="Notes from the assignee while working on the task.",
    )

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.PENDING, db_index=True,
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_tasks",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["created_by", "status"]),
        ]
        constraints = [
            # Mirrors PHP's "Task Name Already Submitted" guard.
            models.UniqueConstraint(
                fields=["name", "assignee"],
                name="uniq_task_name_per_assignee",
            ),
        ]

    def __str__(self):
        return f"#{self.id} {self.name} → {self.assignee_id}"
