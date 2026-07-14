from django.contrib import admin

from .models import StudentAppointment


@admin.register(StudentAppointment)
class StudentAppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "team", "preferred_date",
                    "preferred_time", "status", "scheduled_date",
                    "decided_at")
    list_filter = ("status", "team")
    search_fields = ("student__student_name", "student__application_form_id")
    autocomplete_fields = ("student", "decided_by")
    readonly_fields = ("decided_at", "decided_by", "created_at", "updated_at")
