from django.contrib import admin

from .models import Attendance, ScheduleSlot


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
