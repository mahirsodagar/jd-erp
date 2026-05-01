from django.conf import settings
from django.db import models


# --- 1. Faculty daily activity log ----------------------------------

class FacultyDailyReport(models.Model):
    """Instructor's free-text log + hours, one row per (faculty, date).

    Mirrors PHP `faculty_daily_report`. Computed fields like
    classes_taken / leaves_taken / class_hours can be derived from
    ScheduleSlot/Attendance/LeaveApplication at read-time, so we keep
    only the manual fields here."""

    faculty = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="daily_reports",
    )
    date = models.DateField(db_index=True)
    description = models.TextField(blank=True)
    hours_taught = models.DecimalField(
        max_digits=4, decimal_places=1, default=0,
        help_text="Self-reported teaching hours.",
    )
    non_academic_hours = models.DecimalField(
        max_digits=4, decimal_places=1, default=0,
        help_text="Committee work, mentoring, admin tasks etc.",
    )
    remarks = models.TextField(blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="faculty_daily_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date", "faculty")
        unique_together = (("faculty", "date"),)
        indexes = [models.Index(fields=["faculty", "date"])]

    def __str__(self):
        return f"{self.faculty_id} on {self.date}"


# --- 2. Admin daily report ------------------------------------------

class AdminDailyReport(models.Model):
    """Admin/HR users log two slots per day — a simple monthly grid for
    accountability. PHP `admin_daily_report`."""

    rep_date = models.DateField(db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="admin_daily_reports",
    )
    slot1 = models.TextField(
        blank=True, help_text="Activities in the 9:30-12:30 slot.",
    )
    slot2 = models.TextField(
        blank=True, help_text="Activities in the 1:30-5:30 slot.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-rep_date", "user")
        unique_together = (("rep_date", "user"),)

    def __str__(self):
        return f"{self.user_id} on {self.rep_date}"


# --- 3. Course-end report -------------------------------------------

class CourseEndReport(models.Model):
    """Filed when an instructor completes a course in a batch. Used by
    HOD/auditor to track delivery quality."""

    instructor = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="course_end_reports",
    )
    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT,
        related_name="course_end_reports",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT,
        related_name="course_end_reports",
    )
    completed_on = models.DateField()

    summary = models.TextField()
    learning_outcomes = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    suggestions = models.TextField(blank=True)

    avg_attendance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    avg_marks_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )

    hod_status = models.CharField(
        max_length=10,
        choices=[("PENDING", "Pending"), ("APPROVED", "Approved"),
                 ("RETURNED", "Returned for revision")],
        default="PENDING",
    )
    hod_remarks = models.TextField(blank=True)
    hod_reviewed_at = models.DateTimeField(null=True, blank=True)
    hod_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="course_end_reviews",
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="course_end_submissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-completed_on",)
        unique_together = (("instructor", "subject", "batch"),)

    def __str__(self):
        return f"CourseEnd {self.subject_id}/{self.batch_id} by {self.instructor_id}"


# --- 4. Batch mentor monthly report ---------------------------------

class BatchMentorReport(models.Model):
    """Class teacher's monthly read-out: engagement, concerns, risks."""

    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT,
        related_name="mentor_reports",
    )
    mentor = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="batch_mentor_reports",
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()  # 1..12

    avg_attendance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    avg_marks_pct = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )

    behavioural_notes = models.TextField(blank=True)
    academic_concerns = models.TextField(blank=True)
    dropout_risks = models.TextField(blank=True)
    initiatives = models.TextField(blank=True)
    additional_remarks = models.TextField(blank=True)

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="batch_mentor_submissions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-year", "-month")
        unique_together = (("batch", "year", "month"),)

    def __str__(self):
        return f"{self.batch_id} {self.year}-{self.month:02d}"


# --- 5. Student feedback --------------------------------------------

class StudentFeedback(models.Model):
    """Mid-course or end-of-course feedback. Anonymous-to-instructor in
    the API (we expose only aggregates), but auditors can see who said
    what."""

    class FeedbackType(models.TextChoices):
        MIDWAY = "MIDWAY", "Mid-course"
        END = "END", "End-of-course"

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.PROTECT,
        related_name="feedback_given",
    )
    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT,
        related_name="feedback_received",
    )
    instructor = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="feedback_received",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT,
        related_name="feedback",
    )

    type = models.CharField(max_length=10, choices=FeedbackType.choices)

    rating_overall = models.PositiveSmallIntegerField(
        help_text="1 (poor) to 5 (excellent)",
    )
    rating_clarity = models.PositiveSmallIntegerField(default=0)
    rating_engagement = models.PositiveSmallIntegerField(default=0)
    rating_responsiveness = models.PositiveSmallIntegerField(default=0)

    what_worked = models.TextField(blank=True)
    suggestions = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = (("student", "subject", "instructor", "batch", "type"),)
        indexes = [
            models.Index(fields=["instructor", "type"]),
            models.Index(fields=["subject", "batch", "type"]),
        ]


# --- 6. Faculty self-appraisal --------------------------------------

class FacultySelfAppraisal(models.Model):
    """Quarterly self-appraisal — the auditor uses this for yearly
    appraisal aggregation."""

    class Quarter(models.IntegerChoices):
        Q1 = 1, "Q1 (Apr-Jun)"
        Q2 = 2, "Q2 (Jul-Sep)"
        Q3 = 3, "Q3 (Oct-Dec)"
        Q4 = 4, "Q4 (Jan-Mar)"

    faculty = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="self_appraisals",
    )
    year = models.PositiveSmallIntegerField()
    quarter = models.PositiveSmallIntegerField(choices=Quarter.choices)

    achievements = models.TextField(blank=True)
    challenges = models.TextField(blank=True)
    plans = models.TextField(blank=True)

    green_flags = models.TextField(
        blank=True,
        help_text="Notable positives — mentorship, initiatives, results.",
    )
    red_flags = models.TextField(
        blank=True,
        help_text="Areas needing improvement.",
    )

    auditor_remarks = models.TextField(blank=True)
    auditor_reviewed_at = models.DateTimeField(null=True, blank=True)
    auditor_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="self_appraisals_reviewed",
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="self_appraisals_submitted",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-year", "-quarter")
        unique_together = (("faculty", "year", "quarter"),)

    def __str__(self):
        return f"{self.faculty_id} {self.year} Q{self.quarter}"


# --- 7. Compliance flag (generic anomaly tracker) -------------------

class ComplianceFlag(models.Model):
    """Auditor logs an issue against a faculty / batch / student.
    Tracks resolution for monthly compliance summaries."""

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Category(models.TextChoices):
        TIMETABLE = "TIMETABLE", "Timetable / class compliance"
        ATTENDANCE = "ATTENDANCE", "Attendance / freeze compliance"
        REPORTING = "REPORTING", "Daily report not submitted"
        FEEDBACK = "FEEDBACK", "Negative feedback trend"
        ACADEMIC = "ACADEMIC", "Academic outcome concern"
        OTHER = "OTHER", "Other"

    target_faculty = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compliance_flags",
    )
    target_batch = models.ForeignKey(
        "master.Batch", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compliance_flags",
    )
    target_student = models.ForeignKey(
        "admissions.Student", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compliance_flags",
    )
    target_description = models.CharField(
        max_length=200, blank=True,
        help_text="Free-text target if no FK fits.",
    )

    category = models.CharField(max_length=20, choices=Category.choices)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.MEDIUM,
    )
    description = models.TextField()

    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compliance_resolved",
    )
    resolution_remarks = models.TextField(blank=True)

    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="compliance_raised",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["resolved_at"]),
            models.Index(fields=["category", "severity"]),
        ]

    def __str__(self):
        return f"[{self.severity}/{self.category}] {self.description[:40]}"
