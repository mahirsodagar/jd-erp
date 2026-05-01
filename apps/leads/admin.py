from django.contrib import admin

from .models import (
    CounsellorPool, CounsellorPoolMembership,
    Lead, LeadCommunication, LeadFollowup, LeadStatusHistory, LeadUtm,
)


class PoolMembershipInline(admin.TabularInline):
    model = CounsellorPoolMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(CounsellorPool)
class CounsellorPoolAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active", "pointer", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    inlines = (PoolMembershipInline,)


@admin.register(CounsellorPoolMembership)
class CounsellorPoolMembershipAdmin(admin.ModelAdmin):
    list_display = ("pool", "user", "sort_order", "is_active")
    list_filter = ("pool", "is_active")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("pool", "user")


class LeadFollowupInline(admin.TabularInline):
    model = LeadFollowup
    extra = 0
    readonly_fields = ("created_by", "created_at")


class LeadCommunicationInline(admin.TabularInline):
    model = LeadCommunication
    extra = 0
    readonly_fields = ("logged_by", "logged_at")


class LeadUtmInline(admin.StackedInline):
    model = LeadUtm
    extra = 0
    can_delete = False


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "email", "phone",
        "campus", "program", "source", "assign_to",
        "status", "is_repeated", "created_at",
    )
    list_filter = ("status", "source", "campus", "program", "is_repeated")
    search_fields = ("name", "email", "phone")
    autocomplete_fields = ("campus", "program", "source", "assign_to", "duplicate_of")
    inlines = (LeadUtmInline, LeadFollowupInline, LeadCommunicationInline)
    readonly_fields = ("is_repeated", "duplicate_of",
                       "created_by", "created_at", "updated_at")


@admin.register(LeadStatusHistory)
class LeadStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("lead", "old_status", "new_status", "changed_by", "changed_at")
    list_filter = ("new_status",)
    readonly_fields = [f.name for f in LeadStatusHistory._meta.fields]
