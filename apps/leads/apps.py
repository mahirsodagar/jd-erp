from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leads"
    label = "leads"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            CounsellorPool, CounsellorPoolMembership,
            Lead, LeadCommunication, LeadFollowup, LeadStatusHistory, LeadUtm,
        )
        auditlog.register(Lead)
        auditlog.register(LeadFollowup)
        auditlog.register(LeadCommunication)
        auditlog.register(LeadStatusHistory)
        auditlog.register(LeadUtm)
        auditlog.register(CounsellorPool)
        auditlog.register(CounsellorPoolMembership)
