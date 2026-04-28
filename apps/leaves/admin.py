from django.contrib import admin

from .models import (
    CompOffApplication, EmailDispatchLog, Holiday,
    LeaveAllocation, LeaveApplication, LeaveType, Session,
)


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "half_day_allowed", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("code", "start_date", "end_date", "is_current")
    list_filter = ("is_current",)
    search_fields = ("code",)


@admin.register(LeaveAllocation)
class LeaveAllocationAdmin(admin.ModelAdmin):
    list_display = ("employee", "session", "leave_type",
                    "count", "start_date", "end_date", "created_on")
    list_filter = ("session", "leave_type")
    search_fields = ("employee__emp_code", "employee__first_name",
                     "employee__family_name")
    autocomplete_fields = ("employee", "session", "leave_type", "created_by")


@admin.register(LeaveApplication)
class LeaveApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "leave_type",
                    "from_date", "to_date", "count", "status", "applied_on")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__emp_code", "employee__first_name",
                     "employee__family_name", "manager_email")
    autocomplete_fields = ("employee", "leave_type", "approved_by")
    readonly_fields = ("count", "applied_on", "decided_on")


@admin.register(CompOffApplication)
class CompOffApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "worked_date",
                    "worked_session_1", "worked_session_2", "count",
                    "status", "applied_on")
    list_filter = ("status",)
    search_fields = ("employee__emp_code",)
    autocomplete_fields = ("employee", "approver")
    readonly_fields = ("count", "applied_on", "decided_on")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "campus", "is_optional")
    list_filter = ("campus", "is_optional")
    search_fields = ("name",)
    autocomplete_fields = ("campus",)


@admin.register(EmailDispatchLog)
class EmailDispatchLogAdmin(admin.ModelAdmin):
    list_display = ("template", "to", "status", "subject", "created_at", "sent_at")
    list_filter = ("status", "template")
    search_fields = ("to", "cc", "subject")
    readonly_fields = [f.name for f in EmailDispatchLog._meta.fields]
