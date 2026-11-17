from django.contrib import admin

from .models import (
    EmailCampaign, EmailCampaignRecipient, EmailTemplate, Suppression,
)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "subject", "updated_at", "updated_by")
    search_fields = ("name", "subject")


@admin.register(Suppression)
class SuppressionAdmin(admin.ModelAdmin):
    list_display = ("email", "reason", "source", "added_at")
    list_filter = ("reason",)
    search_fields = ("email", "source")


class RecipientInline(admin.TabularInline):
    model = EmailCampaignRecipient
    extra = 0
    fields = ("name", "email", "status", "error", "sent_at")
    readonly_fields = fields
    can_delete = False
    max_num = 200


@admin.register(EmailCampaign)
class EmailCampaignAdmin(admin.ModelAdmin):
    list_display = ("subject", "source", "status", "created_by", "created_at", "scheduled_at")
    list_filter = ("status", "source")
    search_fields = ("subject", "audience_summary")
    readonly_fields = ("created_at", "started_at", "completed_at")
    inlines = [RecipientInline]
