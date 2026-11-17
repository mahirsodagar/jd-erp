from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.communications"
    label = "communications"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import EmailCampaign, EmailTemplate, Suppression
        auditlog.register(EmailCampaign, exclude_fields=["body_html"])
        auditlog.register(EmailTemplate, exclude_fields=["body_html"])
        auditlog.register(Suppression)
