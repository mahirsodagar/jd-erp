from django.apps import AppConfig


class FeesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fees"
    label = "fees"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Concession, FeeReceipt, Installment
        auditlog.register(Installment)
        auditlog.register(FeeReceipt)
        auditlog.register(Concession)
