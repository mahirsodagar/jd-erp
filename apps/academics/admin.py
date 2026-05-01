from django.contrib import admin

from .models import (
    AlumniRecord, Assignment, AssignmentSubmission, Attendance, Certificate,
    MarksEntry, ScheduleSlot,
)


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ("certificate_no", "type", "status", "student",
                    "issued_at", "requested_on")
    list_filter = ("status", "type")
    search_fields = ("certificate_no", "student__student_name",
                     "student__application_form_id")
    autocomplete_fields = ("student", "enrollment",
                           "requested_by", "issued_by")
    readonly_fields = ("certificate_no", "snapshot",
                       "requested_by", "requested_on",
                       "issued_by", "issued_at",
                       "created_at", "updated_at")


@admin.register(AlumniRecord)
class AlumniRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "graduation_year", "final_program",
                    "current_status", "workplace")
    list_filter = ("current_status", "graduation_year", "final_program")
    search_fields = ("student__student_name",
                     "student__application_form_id",
                     "workplace", "job_title")
    autocomplete_fields = ("student", "final_program", "final_batch")


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "batch", "due_date",
                    "max_marks", "is_published", "created_at")
    list_filter = ("is_published", "subject", "batch")
    search_fields = ("title", "subject__name", "subject__code", "batch__name")
    autocomplete_fields = ("subject", "batch", "created_by")


@admin.register(AssignmentSubmission)
class AssignmentSubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "status",
                    "submitted_at", "grade", "graded_by")
    list_filter = ("status",)
    search_fields = ("student__student_name", "student__application_form_id",
                     "assignment__title")
    autocomplete_fields = ("assignment", "student", "graded_by")
    readonly_fields = ("created_at", "updated_at", "graded_at")


@admin.register(MarksEntry)
class MarksEntryAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "semester", "batch",
                    "ia_marks", "ea_marks", "published")
    list_filter = ("published", "semester", "batch")
    search_fields = ("student__student_name", "student__application_form_id",
                     "subject__code")
    autocomplete_fields = ("student", "subject", "batch", "semester",
                           "entered_by", "published_by")
    readonly_fields = ("published_at", "published_by",
                       "created_at", "updated_at")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = (
        "date", "time_slot", "batch", "subject", "instructor",
        "classroom", "status", "attendance_frozen",
    )
    list_filter = ("status", "attendance_frozen", "date", "batch__campus")
    search_fields = (
        "subject__name", "subject__code",
        "batch__name", "batch__short_name",
        "instructor__emp_code", "instructor__first_name",
    )
    autocomplete_fields = ("batch", "subject", "instructor",
                           "classroom", "time_slot", "created_by",
                           "attendance_frozen_by")
    date_hierarchy = "date"
    readonly_fields = ("classroom_conflict_overridden",
                       "attendance_frozen_at", "attendance_frozen_by",
                       "created_by", "created_at", "updated_at")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("schedule_slot", "student", "status",
                    "marked_by", "marked_at")
    list_filter = ("status", "schedule_slot__batch__campus")
    search_fields = (
        "student__student_name", "student__application_form_id",
    )
    autocomplete_fields = ("schedule_slot", "student", "marked_by")
    readonly_fields = ("marked_at", "created_at")


# G.4 — Tests
from .models import Test, TestAttempt, TestQuestion, TestResponse  # noqa: E402


class TestQuestionInline(admin.TabularInline):
    model = TestQuestion
    extra = 0
    fields = ("sort_order", "type", "description", "options",
              "answer_key", "marks")


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "status", "total_marks",
                    "duration_min", "created_at")
    list_filter = ("status", "subject")
    search_fields = ("name", "subject__code")
    autocomplete_fields = ("subject", "program", "academic_year", "created_by")
    inlines = (TestQuestionInline,)


@admin.register(TestQuestion)
class TestQuestionAdmin(admin.ModelAdmin):
    list_display = ("test", "sort_order", "type", "marks")
    list_filter = ("type",)
    search_fields = ("description", "test__name")
    autocomplete_fields = ("test",)


@admin.register(TestAttempt)
class TestAttemptAdmin(admin.ModelAdmin):
    list_display = ("test", "student", "status",
                    "start_dt", "end_dt", "submitted_at", "total_score")
    list_filter = ("status",)
    search_fields = ("student__student_name",
                     "student__application_form_id",
                     "test__name")
    autocomplete_fields = ("test", "student")
    readonly_fields = ("started_at", "submitted_at",
                       "total_score", "created_at", "updated_at")


@admin.register(TestResponse)
class TestResponseAdmin(admin.ModelAdmin):
    list_display = ("attempt", "question", "marks_awarded",
                    "is_auto_graded", "reviewed_at")
    list_filter = ("is_auto_graded", "question__type")
    autocomplete_fields = ("attempt", "question", "reviewed_by")
    readonly_fields = ("reviewed_at", "created_at", "updated_at")
