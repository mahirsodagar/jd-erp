from django.contrib import admin

from .models import RelievingApplication, RelievingApproval


class RelievingApprovalInline(admin.TabularInline):
    model = RelievingApproval
    extra = 0
    autocomplete_fields = ("approver", "decided_by")
    readonly_fields = ("decided_at", "created_at")


@admin.register(RelievingApplication)
class RelievingApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "employee", "status",
        "last_working_date_requested", "last_working_date_approved",
        "submitted_at", "finalized_at",
    )
    list_filter = ("status",)
    search_fields = (
        "employee__emp_code", "employee__first_name", "employee__family_name",
        "relieving_letter_no", "experience_letter_no",
    )
    autocomplete_fields = ("employee", "submitted_by", "finalized_by")
    readonly_fields = (
        "status", "rejected_at_level", "rejection_reason",
        "relieving_letter_no", "experience_letter_no",
        "finalized_at", "finalized_by",
        "submitted_by", "submitted_at", "updated_at",
    )
    date_hierarchy = "submitted_at"
    inlines = [RelievingApprovalInline]


@admin.register(RelievingApproval)
class RelievingApprovalAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "level", "approver",
                    "status", "decided_at")
    list_filter = ("status", "level")
    search_fields = (
        "application__employee__emp_code",
        "approver__emp_code",
    )
    autocomplete_fields = ("application", "approver", "decided_by")
    readonly_fields = ("decided_at", "created_at")
