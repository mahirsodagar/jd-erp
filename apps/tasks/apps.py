from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Task
        auditlog.register(Task)
