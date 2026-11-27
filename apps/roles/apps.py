from django.apps import AppConfig


class RolesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.roles"
    label = "roles"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Permission, Role
        # m2m_fields: a role's permission set and membership ARE the
        # privilege grants — without this only the name/description
        # changes were logged.
        auditlog.register(Role, m2m_fields={"permissions", "users"})
        auditlog.register(Permission)
