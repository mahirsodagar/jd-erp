from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    label = "payments"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import PaymentRequest

        # Orders and webhook events are append-only and already carry
        # their own raw payloads — auditing them would duplicate the row.
        auditlog.register(PaymentRequest)
