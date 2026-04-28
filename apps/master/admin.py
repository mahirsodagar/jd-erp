from django.contrib import admin

from .models import Campus, LeadSource, Program


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "state", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "city")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "degree_type", "duration_months", "is_active")
    list_filter = ("is_active", "degree_type")
    search_fields = ("name", "code")
    filter_horizontal = ("campuses",)


@admin.register(LeadSource)
class LeadSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
