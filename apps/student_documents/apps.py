from django.apps import AppConfig


class StudentDocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.student_documents"
    label = "student_documents"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import DocumentRequest
        auditlog.register(DocumentRequest)
