from django.contrib import admin

from .models import ScheduleSlot


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = (
        "date", "time_slot", "batch", "subject", "instructor",
        "classroom", "status",
    )
    list_filter = ("status", "date", "batch__campus")
    search_fields = (
        "subject__name", "subject__code",
        "batch__name", "batch__short_name",
        "instructor__emp_code", "instructor__first_name",
    )
    autocomplete_fields = ("batch", "subject", "instructor",
                           "classroom", "time_slot", "created_by")
    date_hierarchy = "date"
    readonly_fields = ("classroom_conflict_overridden",
                       "created_by", "created_at", "updated_at")
