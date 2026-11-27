from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    label = "payments"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import PaymentOrder, PaymentRequest

        auditlog.register(PaymentRequest)
        # Orders carry their raw gateway payload already; audit only the
        # state transition so "who/when marked this paid" is on record.
        # Webhook events stay unaudited (append-only).
        auditlog.register(
            PaymentOrder, include_fields=["status", "charged_at", "txn_id"],
        )
