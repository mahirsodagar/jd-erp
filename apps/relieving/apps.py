from django.apps import AppConfig


class RelievingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.relieving"
    label = "relieving"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import RelievingApplication, RelievingApproval
        auditlog.register(RelievingApplication)
        auditlog.register(RelievingApproval)
