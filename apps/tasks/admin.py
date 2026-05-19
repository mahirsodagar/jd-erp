from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "assignee", "end_date", "status",
                    "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "description", "assignee__username",
                     "created_by__username")
    autocomplete_fields = ("assignee", "created_by")
    readonly_fields = ("completed_at", "created_at", "updated_at")
