from django.conf import settings
from django.db import models


class ScheduleSlot(models.Model):
    """One published class on the timetable.

    Maps PHP `timetable_pub`. Each row is a (batch, subject, instructor,
    classroom, date, time-slot) tuple. Attendance attaches to this row
    via the future apps/attendance app (G.2).
    """

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT, related_name="schedule_slots",
    )
    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT, related_name="schedule_slots",
    )
    instructor = models.ForeignKey(
        "employees.Employee", on_delete=models.PROTECT,
        related_name="teaching_slots",
    )
    classroom = models.ForeignKey(
        "master.Classroom", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="schedule_slots",
    )
    time_slot = models.ForeignKey(
        "master.TimeSlot", on_delete=models.PROTECT,
        related_name="schedule_slots",
    )
    date = models.DateField(db_index=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SCHEDULED,
    )
    notes = models.CharField(max_length=400, blank=True)

    # Set when classroom-conflict warnings were overridden via force=True.
    classroom_conflict_overridden = models.BooleanField(default=False)

    # Module G.2 — once frozen, attendance edits require
    # `academics.attendance.edit_frozen`.
    attendance_frozen = models.BooleanField(default=False)
    attendance_frozen_at = models.DateTimeField(null=True, blank=True)
    attendance_frozen_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="frozen_schedule_slots",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="schedule_slots_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("date", "time_slot__start_time")
        indexes = [
            models.Index(fields=["batch", "date"]),
            models.Index(fields=["instructor", "date"]),
            models.Index(fields=["classroom", "date"]),
        ]
        constraints = [
            # Same instructor cannot be scheduled in two slots that
            # share the same date and time_slot — enforced at the DB
            # level for cancelled-state safety; the conflict service
            # gives a friendlier 409.
            models.UniqueConstraint(
                fields=["instructor", "date", "time_slot"],
                condition=models.Q(status="SCHEDULED"),
                name="uniq_instructor_date_slot_active",
            ),
            models.UniqueConstraint(
                fields=["batch", "date", "time_slot"],
                condition=models.Q(status="SCHEDULED"),
                name="uniq_batch_date_slot_active",
            ),
        ]

    def __str__(self):
        return f"{self.batch.short_name or self.batch_id} {self.subject.code} {self.date} {self.time_slot.label}"


class Attendance(models.Model):
    """One row per (schedule_slot, student). Created on first mark."""

    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"
        ON_DUTY = "ON_DUTY", "On Duty"
        EXCUSED = "EXCUSED", "Excused"

    schedule_slot = models.ForeignKey(
        ScheduleSlot, on_delete=models.CASCADE, related_name="attendance_entries",
    )
    student = models.ForeignKey(
        "admissions.Student", on_delete=models.PROTECT,
        related_name="attendance_entries",
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    note = models.CharField(max_length=200, blank=True)

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="attendance_marked",
    )
    marked_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("schedule_slot", "student")
        unique_together = (("schedule_slot", "student"),)
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["schedule_slot", "status"]),
        ]

    def __str__(self):
        return f"{self.student_id}@{self.schedule_slot_id}: {self.status}"


# === G.3 — Assignments + Marks ======================================

class Assignment(models.Model):
    """Faculty-created homework / project for a (subject, batch) pair.

    Per PHP scope `assignment_master + assignment_mapping`, but we keep
    submissions on-demand (no pre-mapping) and fall back to the
    Assignment.due_date unless an extension is set on the Submission."""

    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT, related_name="assignments",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT, related_name="assignments",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    max_marks = models.DecimalField(max_digits=5, decimal_places=1)
    due_date = models.DateTimeField()
    attachment = models.FileField(
        upload_to="assignments/", blank=True, null=True,
    )

    is_published = models.BooleanField(
        default=True,
        help_text="When False, students don't see the assignment.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assignments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-due_date", "-created_at")
        indexes = [
            models.Index(fields=["batch", "subject"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.batch.short_name or self.batch_id})"


class AssignmentSubmission(models.Model):
    """One row per (assignment, student). Created on first submit."""

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        LATE = "LATE", "Late submission"
        GRADED = "GRADED", "Graded"
        RESUBMIT = "RESUBMIT", "Resubmit requested"

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name="submissions",
    )
    student = models.ForeignKey(
        "admissions.Student", on_delete=models.PROTECT,
        related_name="assignment_submissions",
    )

    file = models.FileField(upload_to="submissions/", blank=True, null=True)
    text_response = models.TextField(blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    extended_due_date = models.DateTimeField(
        null=True, blank=True,
        help_text="Per-student deadline override.",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUBMITTED,
    )

    grade = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
    )
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="submissions_graded",
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-submitted_at", "-created_at")
        unique_together = (("assignment", "student"),)
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["assignment", "status"]),
        ]

    def __str__(self):
        return f"{self.student_id} → {self.assignment_id} [{self.status}]"


class MarksEntry(models.Model):
    """IA + EA marks per (student, subject, semester, batch). Drafted by
    faculty, published by HOD. Once published, edits require
    `academics.marks.edit_published`."""

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.PROTECT, related_name="marks",
    )
    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT, related_name="marks",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT, related_name="marks",
    )
    semester = models.ForeignKey(
        "master.Semester", on_delete=models.PROTECT, related_name="marks",
    )

    ia_marks = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        help_text="Internal Assessment.",
    )
    ia_max = models.DecimalField(max_digits=5, decimal_places=1, default=20)
    ea_marks = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        help_text="External Assessment.",
    )
    ea_max = models.DecimalField(max_digits=5, decimal_places=1, default=80)

    published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="marks_published",
    )

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="marks_entered",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("student", "semester", "subject")
        unique_together = (("student", "subject", "semester"),)
        indexes = [
            models.Index(fields=["batch", "semester"]),
            models.Index(fields=["student", "published"]),
        ]

    def __str__(self):
        return f"{self.student_id} {self.subject.code} S{self.semester.number}"

    @property
    def total_marks(self):
        ia = float(self.ia_marks or 0)
        ea = float(self.ea_marks or 0)
        return ia + ea

    @property
    def total_max(self):
        return float(self.ia_max or 0) + float(self.ea_max or 0)

    @property
    def percentage(self):
        if not self.total_max:
            return 0.0
        return round((self.total_marks / self.total_max) * 100, 2)


# === G.5 — Certificates + Alumni ====================================

class Certificate(models.Model):
    """Issued document for a student. Six types covered."""

    class Type(models.TextChoices):
        COMPLETION = "COMPLETION", "Course Completion"
        PROVISIONAL = "PROVISIONAL", "Provisional"
        BONAFIDE = "BONAFIDE", "Bonafide"
        TRANSFER = "TRANSFER", "Transfer"
        CHARACTER = "CHARACTER", "Character"
        NO_DUES = "NO_DUES", "No Dues"

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        ISSUED = "ISSUED", "Issued"
        REJECTED = "REJECTED", "Rejected"
        REVOKED = "REVOKED", "Revoked"

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.PROTECT,
        related_name="certificates",
    )
    enrollment = models.ForeignKey(
        "admissions.Enrollment", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="certificates",
        help_text="Source enrollment for context (program / batch).",
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.REQUESTED,
    )

    certificate_no = models.CharField(max_length=60, blank=True, db_index=True)

    purpose = models.CharField(max_length=200, blank=True)
    remarks = models.TextField(blank=True)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="certificates_requested",
    )
    requested_on = models.DateTimeField(auto_now_add=True)

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="certificates_issued",
    )
    issued_at = models.DateTimeField(null=True, blank=True)

    # Snapshot for the PDF — stamped at issue time so later edits to
    # the student / program don't change the artefact.
    snapshot = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-requested_on",)
        indexes = [
            models.Index(fields=["student", "type"]),
            models.Index(fields=["status", "type"]),
        ]

    def __str__(self):
        return f"{self.type} {self.certificate_no or 'pending'} → {self.student_id}"


class AlumniRecord(models.Model):
    """Snapshot of a student at graduation + ongoing alumni profile."""

    class CurrentStatus(models.TextChoices):
        JOB = "JOB", "Working a job"
        ENTREPRENEUR = "ENTREPRENEUR", "Entrepreneur"
        HIGHER_STUDIES = "HIGHER_STUDIES", "Pursuing higher studies"
        FAMILY_BUSINESS = "FAMILY_BUSINESS", "Family business"
        UNKNOWN = "UNKNOWN", "Unknown"

    student = models.OneToOneField(
        "admissions.Student", on_delete=models.PROTECT, related_name="alumni",
    )

    graduation_year = models.PositiveSmallIntegerField()
    final_program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="alumni",
    )
    final_batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT, related_name="alumni",
    )
    final_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )

    current_status = models.CharField(
        max_length=20, choices=CurrentStatus.choices,
        default=CurrentStatus.UNKNOWN,
    )
    workplace = models.CharField(max_length=200, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    linkedin_url = models.URLField(blank=True)

    last_known_email = models.EmailField(blank=True)
    last_known_phone = models.CharField(max_length=20, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-graduation_year", "student__student_name")
        indexes = [
            models.Index(fields=["graduation_year", "final_program"]),
            models.Index(fields=["current_status"]),
        ]

    def __str__(self):
        return f"{self.student.student_name} ({self.graduation_year})"
