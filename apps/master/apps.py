from django.apps import AppConfig


class MasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.master"
    label = "master"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Campus, City, Institute, LeadSource, Program, State
        auditlog.register(Campus)
        auditlog.register(Program)
        auditlog.register(LeadSource)
        auditlog.register(Institute)
        auditlog.register(State)
        auditlog.register(City)
