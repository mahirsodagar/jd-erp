from django.conf import settings
from django.db import models


class StudentAppointment(models.Model):
    """A student's request to meet a management/office team.

    The student proposes a preferred date + time and a reason. Staff who
    hold `appointments.decide` confirm (optionally rescheduling to a
    different slot + venue), decline, or later mark the meeting completed.
    Notifications are in-app only — the student sees the outcome in the
    portal; nothing is sent over WhatsApp/SMS/email.
    """

    class Team(models.TextChoices):
        MANAGEMENT = "MANAGEMENT", "Management"
        ADMISSIONS = "ADMISSIONS", "Admissions"
        ACCOUNTS = "ACCOUNTS", "Accounts / Fees"
        ACADEMICS = "ACADEMICS", "Academics"
        EXAMINATION = "EXAMINATION", "Examination"
        PLACEMENT = "PLACEMENT", "Placement"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        CONFIRMED = "CONFIRMED", "Confirmed"
        DECLINED = "DECLINED", "Declined"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.CASCADE,
        related_name="appointments",
    )
    # An appointment targets EITHER a generic office team OR a specific
    # faculty member. Exactly one of `team` / `faculty` is set (enforced
    # in the service layer).
    team = models.CharField(max_length=12, choices=Team.choices, blank=True)
    faculty = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.PROTECT, related_name="student_appointments",
    )
    reason = models.TextField()

    # Student's proposed slot.
    preferred_date = models.DateField()
    preferred_time = models.TimeField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED,
        db_index=True,
    )

    # Staff-confirmed slot. May match the preferred slot or differ (a
    # reschedule). Populated when a request is confirmed.
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True)

    staff_remarks = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="appointments_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["team", "status"]),
            models.Index(fields=["faculty", "status"]),
        ]

    @property
    def target_label(self) -> str:
        """Human name of whoever the student wants to meet."""
        if self.faculty_id:
            return self.faculty.full_name
        return self.get_team_display()

    def __str__(self):
        target = f"faculty#{self.faculty_id}" if self.faculty_id else self.team
        return f"{self.student_id}→{target} {self.preferred_date} ({self.status})"
