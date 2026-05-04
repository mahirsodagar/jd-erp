from django.apps import AppConfig


class StudentLeavesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.student_leaves"
    label = "student_leaves"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import StudentLeaveApplication
        auditlog.register(StudentLeaveApplication)
