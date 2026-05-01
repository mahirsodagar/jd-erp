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
