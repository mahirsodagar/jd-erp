from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class LeaveType(models.Model):
    class Category(models.TextChoices):
        LEAVE = "LEAVE", "Leave"
        ON_DUTY = "ON_DUTY", "On-duty"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    category = models.CharField(max_length=10, choices=Category.choices)
    half_day_allowed = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.code} ({self.name})"


class Session(models.Model):
    """Academic-year / leave-allocation period. Global to the institute."""

    code = models.CharField(max_length=10, unique=True, help_text="e.g. 2024-25")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.code

    def clean(self):
        if self.end_date < self.start_date:
            raise ValidationError({"end_date": "Must be on/after start_date."})
        if self.is_current:
            qs = Session.objects.filter(is_current=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"is_current": "Another session is already marked current."}
                )


class LeaveAllocation(models.Model):
    """Annual grant of LEAVE-category days for an employee in a session."""

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.CASCADE, related_name="leave_allocations",
    )
    session = models.ForeignKey(
        Session, on_delete=models.PROTECT, related_name="allocations",
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="allocations",
    )
    count = models.DecimalField(max_digits=5, decimal_places=1)
    start_date = models.DateField()
    end_date = models.DateField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leave_allocations_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_on",)
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "session", "leave_type", "start_date", "end_date"],
                name="uniq_alloc_per_emp_session_type_window",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "session"]),
            models.Index(fields=["leave_type", "start_date"]),
        ]


class LeaveApplication(models.Model):
    class Status(models.IntegerChoices):
        PENDING = 1, "Pending"
        APPROVED = 2, "Approved"
        REJECTED = 3, "Rejected"
        CANCELLED = 4, "Cancelled"
        WITHDRAWN = 5, "Withdrawn"

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="leave_applications",
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT, related_name="applications",
    )

    from_date = models.DateField()
    to_date = models.DateField()
    from_session = models.PositiveSmallIntegerField(
        help_text="1=AM, 2=Full day, 3=Permission slot 1, 4=Permission slot 2",
    )
    count = models.DecimalField(max_digits=5, decimal_places=1)

    reason = models.TextField()
    manager_email = models.EmailField(
        help_text="Snapshot at apply-time so RM changes don't reroute.",
    )
    cc_emails = models.CharField(max_length=255, blank=True)

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.PENDING,
    )
    approver_remarks = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="approved_leaves",
    )

    applied_on = models.DateTimeField(auto_now_add=True)
    decided_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-applied_on",)
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["from_date", "to_date"]),
            models.Index(fields=["manager_email"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(to_date__gte=models.F("from_date")),
                name="leave_app_to_after_from",
            ),
        ]

    def __str__(self):
        return f"{self.employee_id} {self.leave_type.code} {self.from_date}→{self.to_date}"


class CompOffApplication(models.Model):
    class Status(models.IntegerChoices):
        PENDING = 1, "Pending"
        APPROVED = 2, "Approved"
        REJECTED = 3, "Rejected"

    employee = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT, related_name="compoff_applications",
    )
    worked_date = models.DateField()
    worked_session_1 = models.PositiveSmallIntegerField(default=0)  # 0/1
    worked_session_2 = models.PositiveSmallIntegerField(default=0)  # 0/1
    count = models.DecimalField(max_digits=3, decimal_places=1)

    reason = models.TextField()
    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.PENDING,
    )
    approver = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compoff_decisions",
    )
    approver_remarks = models.TextField(blank=True)

    applied_on = models.DateTimeField(auto_now_add=True)
    decided_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-applied_on",)
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["worked_date"]),
        ]


class Holiday(models.Model):
    date = models.DateField()
    name = models.CharField(max_length=120)
    campus = models.ForeignKey(
        "master.Campus", null=True, blank=True,
        on_delete=models.CASCADE, related_name="holidays",
        help_text="Null = applies to all campuses.",
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="Optional / restricted holiday — does not auto-deduct from leave count.",
    )

    class Meta:
        ordering = ("date",)
        constraints = [
            models.UniqueConstraint(
                fields=["date", "campus"],
                name="uniq_holiday_date_campus",
            ),
        ]
        indexes = [
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.date} — {self.name}"


class EmailDispatchLog(models.Model):
    """Stand-in for the Celery email pipeline. We log intended emails on
    PythonAnywhere free (which blocks SMTP) so they can be replayed when
    a real outbound channel is configured."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    template = models.CharField(max_length=80)
    to = models.CharField(max_length=400)
    cc = models.CharField(max_length=400, blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    context = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    related_application = models.ForeignKey(
        LeaveApplication, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="email_logs",
    )
    related_compoff = models.ForeignKey(
        CompOffApplication, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="email_logs",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "created_at"])]
