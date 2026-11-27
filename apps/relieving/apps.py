from django.apps import AppConfig


class RelievingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.relieving"
    label = "relieving"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import RelievingApplication, RelievingApproval, RelievingManager
        auditlog.register(RelievingApplication)
        auditlog.register(RelievingApproval)
        # The approver master decides who can sign off relieving.
        auditlog.register(RelievingManager)
