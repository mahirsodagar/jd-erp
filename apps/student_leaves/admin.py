from django.contrib import admin

from .models import StudentLeaveApplication


@admin.register(StudentLeaveApplication)
class StudentLeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "leave_date", "leave_edate",
                    "status", "decided_at")
    list_filter = ("status",)
    search_fields = ("student__student_name", "student__application_form_id")
    autocomplete_fields = ("student", "decided_by")
    readonly_fields = ("decided_at", "decided_by", "created_at", "updated_at")
