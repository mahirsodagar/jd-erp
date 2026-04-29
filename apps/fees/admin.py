from django.contrib import admin

from .models import Concession, FeeReceipt, Installment


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "sequence", "due_date", "amount", "created_on")
    list_filter = ("enrollment__campus", "enrollment__program")
    search_fields = (
        "enrollment__student__student_name",
        "enrollment__student__application_form_id",
    )
    autocomplete_fields = ("enrollment", "created_by")


@admin.register(FeeReceipt)
class FeeReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_no", "enrollment", "amount", "payment_mode",
        "received_date", "status",
    )
    list_filter = ("status", "payment_mode", "enrollment__campus")
    search_fields = (
        "receipt_no",
        "enrollment__student__student_name",
        "enrollment__student__application_form_id",
        "instrument_ref",
    )
    autocomplete_fields = ("enrollment", "installment",
                           "received_by", "cancelled_by")
    readonly_fields = ("receipt_no", "created_on", "updated_on",
                       "cancelled_by", "cancelled_on")


@admin.register(Concession)
class ConcessionAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "amount", "status", "requested_on", "decided_on")
    list_filter = ("status",)
    search_fields = (
        "enrollment__student__student_name",
        "enrollment__student__application_form_id",
    )
    autocomplete_fields = ("enrollment", "requested_by", "approver")
    readonly_fields = ("requested_by", "requested_on",
                       "approver", "decided_on")
