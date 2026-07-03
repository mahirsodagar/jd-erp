from django.contrib import admin

from .models import (
    AdminDailyReport, AuditAnswer, AuditForm, AuditFormField, AuditSubmission,
    BatchMentorReport, ComplianceFlag, CourseEndReport,
    FacultyDailyReport, FacultySelfAppraisal, StudentFeedback, ZeroHourReport,
)


@admin.register(FacultyDailyReport)
class FacultyDailyReportAdmin(admin.ModelAdmin):
    list_display = ("faculty", "date", "academic_hours",
                    "non_academic_hours", "others_hours")
    list_filter = ("date",)
    search_fields = ("faculty__emp_code", "faculty__first_name",
                     "faculty__family_name", "academic_description")
    autocomplete_fields = ("faculty", "submitted_by")
    date_hierarchy = "date"


@admin.register(AdminDailyReport)
class AdminDailyReportAdmin(admin.ModelAdmin):
    list_display = ("user", "rep_date")
    search_fields = ("user__username",)
    autocomplete_fields = ("user",)
    date_hierarchy = "rep_date"


@admin.register(CourseEndReport)
class CourseEndReportAdmin(admin.ModelAdmin):
    list_display = ("instructor", "subject", "batch", "completed_on", "hod_status")
    list_filter = ("hod_status",)
    search_fields = ("instructor__emp_code", "subject__code", "batch__name")
    autocomplete_fields = ("instructor", "subject", "batch",
                           "submitted_by", "hod_reviewed_by")
    readonly_fields = ("hod_reviewed_at", "hod_reviewed_by",
                       "submitted_by", "created_at", "updated_at")


@admin.register(BatchMentorReport)
class BatchMentorReportAdmin(admin.ModelAdmin):
    list_display = ("batch", "year", "month", "mentor",
                    "avg_attendance_pct", "avg_marks_pct")
    list_filter = ("year", "month")
    search_fields = ("batch__name", "mentor__emp_code")
    autocomplete_fields = ("batch", "mentor", "submitted_by")


@admin.register(ZeroHourReport)
class ZeroHourReportAdmin(admin.ModelAdmin):
    list_display = ("batch", "report_date", "mentor",
                    "batch_strength", "zero_hour_attendance")
    list_filter = ("report_date",)
    search_fields = ("batch__name", "mentor__emp_code")
    autocomplete_fields = ("batch", "mentor", "submitted_by")
    date_hierarchy = "report_date"
    readonly_fields = ("submitted_by", "created_at", "updated_at")


@admin.register(StudentFeedback)
class StudentFeedbackAdmin(admin.ModelAdmin):
    list_display = ("student", "instructor", "subject", "type",
                    "rating_overall", "created_at")
    list_filter = ("type",)
    search_fields = ("student__student_name", "instructor__emp_code",
                     "subject__code")
    autocomplete_fields = ("student", "instructor", "subject", "batch")


@admin.register(FacultySelfAppraisal)
class FacultySelfAppraisalAdmin(admin.ModelAdmin):
    list_display = ("faculty", "year", "quarter", "auditor_reviewed_at")
    list_filter = ("year", "quarter")
    search_fields = ("faculty__emp_code",)
    autocomplete_fields = ("faculty", "submitted_by", "auditor_reviewed_by")
    readonly_fields = ("auditor_reviewed_at", "auditor_reviewed_by",
                       "submitted_by", "created_at", "updated_at")


@admin.register(ComplianceFlag)
class ComplianceFlagAdmin(admin.ModelAdmin):
    list_display = ("category", "severity", "target_faculty", "target_batch",
                    "resolved_at", "created_at")
    list_filter = ("category", "severity")
    search_fields = ("description", "target_description")
    autocomplete_fields = ("target_faculty", "target_batch", "target_student",
                           "raised_by", "resolved_by")
    readonly_fields = ("resolved_at", "resolved_by",
                       "raised_by", "created_at", "updated_at")


class AuditFormFieldInline(admin.TabularInline):
    model = AuditFormField
    extra = 0


@admin.register(AuditForm)
class AuditFormAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "description")
    autocomplete_fields = ("created_by",)
    inlines = (AuditFormFieldInline,)
    readonly_fields = ("created_by", "created_at", "updated_at")


class AuditAnswerInline(admin.TabularInline):
    model = AuditAnswer
    extra = 0
    readonly_fields = ("field", "value")
    can_delete = False


@admin.register(AuditSubmission)
class AuditSubmissionAdmin(admin.ModelAdmin):
    list_display = ("id", "form", "submitted_by", "created_at")
    search_fields = ("form__title", "submitted_by__username")
    autocomplete_fields = ("form", "submitted_by")
    readonly_fields = ("form", "submitted_by", "created_at")
    inlines = (AuditAnswerInline,)
