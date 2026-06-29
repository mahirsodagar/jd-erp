from django.contrib import admin

from .models import DocumentRequest


@admin.register(DocumentRequest)
class DocumentRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "doc_type", "status", "decided_at")
    list_filter = ("status", "doc_type")
    search_fields = ("student__student_name", "student__application_form_id")
    autocomplete_fields = ("student", "decided_by")
    readonly_fields = ("decided_at", "decided_by", "created_at", "updated_at")
