from rest_framework import serializers

from .models import PaymentOrder, PaymentRequest
from .services import pay_url_for


class PaymentOrderSerializer(serializers.ModelSerializer):
    is_paid = serializers.BooleanField(read_only=True)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentOrder
        fields = (
            "id", "order_id", "sg_order_ref", "status", "amount",
            "txn_id", "payment_method", "payment_method_type",
            "bank_error_code", "bank_error_message",
            "session_expires_at", "charged_at",
            "is_paid", "is_terminal", "created_on", "updated_on",
        )
        read_only_fields = fields


class PaymentRequestSerializer(serializers.ModelSerializer):
    lead_name = serializers.CharField(
        source="lead.name", read_only=True, default="",
    )
    orders = PaymentOrderSerializer(many=True, read_only=True)
    #: The URL that actually goes out in the SMS. Built rather than
    #: stored, so it follows the configured public base URL.
    pay_url = serializers.SerializerMethodField()

    class Meta:
        model = PaymentRequest
        fields = (
            "id", "token", "purpose", "lead", "lead_name", "installment",
            "amount", "currency", "description",
            "status", "paid_at", "attempt_count", "pay_url", "orders",
            "created_by", "created_on", "updated_on",
        )
        # Every field is gateway- or service-owned; the API is read-only.
        read_only_fields = fields

    def get_pay_url(self, obj) -> str:
        return pay_url_for(obj)
