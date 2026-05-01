from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"

    def ready(self):
        from auditlog.registry import auditlog
        from . import signals  # noqa: F401
        from .models import NotificationDispatchLog, NotificationTemplate, ScheduledNotification
        auditlog.register(NotificationTemplate)
        auditlog.register(NotificationDispatchLog)
        auditlog.register(ScheduledNotification)
