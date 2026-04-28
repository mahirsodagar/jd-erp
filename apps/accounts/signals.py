"""Auditlog registration for tenant-scoped account models."""

from auditlog.registry import auditlog

from .models import User

auditlog.register(
    User,
    exclude_fields=["password", "last_login"],
)
