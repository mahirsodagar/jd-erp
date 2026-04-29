from django.apps import AppConfig


class AdmissionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admissions"
    label = "admissions"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Enrollment, Student, StudentDocument
        auditlog.register(Student)
        auditlog.register(StudentDocument)
        auditlog.register(Enrollment)
