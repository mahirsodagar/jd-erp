"""Auditlog registration for tenant-scoped account models."""

from auditlog.registry import auditlog

from .models import User

auditlog.register(
    User,
    # visible_password is the plaintext copy — never into the audit table.
    exclude_fields=["password", "last_login", "visible_password"],
    # Campus assignment is what every *_all_campuses scope resolves on.
    m2m_fields={"campuses"},
)
