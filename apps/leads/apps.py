from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leads"
    label = "leads"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            Counsellor,
            Lead, LeadCommunication, LeadFollowup, LeadStatusHistory, LeadUtm,
        )
        auditlog.register(Lead)
        auditlog.register(LeadFollowup)
        auditlog.register(LeadCommunication)
        auditlog.register(LeadStatusHistory)
        auditlog.register(LeadUtm)
        auditlog.register(Counsellor)
        # Entrance exams: grading and the pass/fail decision are
        # admissions-relevant and were unaudited.
        from .exam_models import EntranceExam, EntranceExamAttempt
        auditlog.register(EntranceExam)
        auditlog.register(EntranceExamAttempt)
