from django.contrib import admin

from .models import PaymentOrder, PaymentRequest, SmartGatewayWebhookEvent


class PaymentOrderInline(admin.TabularInline):
    model = PaymentOrder
    extra = 0
    fields = (
        "order_id", "status", "amount", "txn_id", "payment_method_type",
        "charged_at", "created_on",
    )
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        # Orders are minted by the gateway flow, never by hand.
        return False


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id", "purpose", "lead", "amount", "status",
        "attempt_count", "paid_at", "created_on",
    )
    list_filter = ("purpose", "status", "created_on")
    search_fields = (
        "token", "lead__name", "lead__phone", "lead__email",
        "orders__order_id", "orders__txn_id",
    )
    raw_id_fields = ("lead", "created_by", "paid_order")
    readonly_fields = ("token", "attempt_count", "created_on", "updated_on")
    inlines = [PaymentOrderInline]


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_id", "request", "status", "amount", "txn_id",
        "payment_method_type", "charged_at", "created_on",
    )
    list_filter = ("status", "payment_method_type", "created_on")
    search_fields = ("order_id", "sg_order_ref", "txn_id", "txn_uuid")
    raw_id_fields = ("request",)
    readonly_fields = ("last_payload", "created_on", "updated_on")

    def has_add_permission(self, request):
        return False


@admin.register(SmartGatewayWebhookEvent)
class SmartGatewayWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id", "event_name", "status", "order",
        "received_at", "processed_at",
    )
    list_filter = ("event_name", "status", "received_at")
    search_fields = ("event_id", "error_message")
    raw_id_fields = ("order",)
    readonly_fields = tuple(
        f.name for f in SmartGatewayWebhookEvent._meta.fields
    )

    def has_add_permission(self, request):
        # Written only by the webhook receiver.
        return False
