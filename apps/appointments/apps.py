from django.apps import AppConfig


class AppointmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.appointments"
    label = "appointments"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import StudentAppointment
        auditlog.register(StudentAppointment)
