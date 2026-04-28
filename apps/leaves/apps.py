from django.apps import AppConfig


class LeavesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leaves"
    label = "leaves"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            CompOffApplication, Holiday, LeaveAllocation,
            LeaveApplication, LeaveType, Session,
        )
        auditlog.register(LeaveType)
        auditlog.register(Session)
        auditlog.register(LeaveAllocation)
        auditlog.register(LeaveApplication)
        auditlog.register(CompOffApplication)
        auditlog.register(Holiday)
