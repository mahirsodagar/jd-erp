from django.apps import AppConfig


class MasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.master"
    label = "master"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Campus, LeadSource, Program
        auditlog.register(Campus)
        auditlog.register(Program)
        auditlog.register(LeadSource)
