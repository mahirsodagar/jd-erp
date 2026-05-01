from django.apps import AppConfig


class AuditReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit_reports"
    label = "audit_reports"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            AdminDailyReport, BatchMentorReport, ComplianceFlag,
            CourseEndReport, FacultyDailyReport, FacultySelfAppraisal,
            StudentFeedback,
        )
        for m in (
            FacultyDailyReport, AdminDailyReport, CourseEndReport,
            BatchMentorReport, StudentFeedback, FacultySelfAppraisal,
            ComplianceFlag,
        ):
            auditlog.register(m)
