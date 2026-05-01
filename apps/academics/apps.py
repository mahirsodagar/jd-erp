from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academics"
    label = "academics"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Attendance, ScheduleSlot
        auditlog.register(ScheduleSlot)
        auditlog.register(Attendance)
