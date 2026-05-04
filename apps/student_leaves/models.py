from django.conf import settings
from django.db import models


class StudentLeaveApplication(models.Model):
    """Student-side leave application. Distinct from employee LeaveApplication."""

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.CASCADE,
        related_name="leave_applications",
    )
    leave_date = models.DateField()
    leave_edate = models.DateField()
    student_remarks = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUBMITTED,
        db_index=True,
    )

    batch_mentor_email = models.EmailField()
    module_mentor_email = models.EmailField(blank=True)
    cc_emails = models.JSONField(default=list, blank=True)

    approver_remarks = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="student_leaves_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["student", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(leave_edate__gte=models.F("leave_date")),
                name="student_leave_dates_ordered",
            ),
        ]

    def __str__(self):
        return f"{self.student_id}: {self.leave_date}→{self.leave_edate} ({self.status})"

    @property
    def days(self) -> int:
        return (self.leave_edate - self.leave_date).days + 1
