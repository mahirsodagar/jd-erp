from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academics"
    label = "academics"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            AlumniRecord, Assignment, AssignmentSubmission, Attendance,
            Certificate, MarksEntry, ScheduleSlot, Test, TestAttempt,
            TestQuestion, TestResponse,
        )
        auditlog.register(ScheduleSlot)
        auditlog.register(Attendance)
        auditlog.register(Assignment)
        auditlog.register(AssignmentSubmission)
        auditlog.register(MarksEntry)
        auditlog.register(Certificate)
        auditlog.register(AlumniRecord)
        auditlog.register(Test)
        auditlog.register(TestQuestion)
        auditlog.register(TestAttempt)
        auditlog.register(TestResponse)
