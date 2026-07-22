from django.apps import AppConfig


class LeavesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leaves"
    label = "leaves"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            CompOffApplication, LeaveAllocation,
            LeaveApplication, LeaveType,
        )
        auditlog.register(LeaveType)
        auditlog.register(LeaveAllocation)
        auditlog.register(LeaveApplication)
        auditlog.register(CompOffApplication)
