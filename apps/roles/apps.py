from django.apps import AppConfig


class RolesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.roles"
    label = "roles"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Permission, Role
        auditlog.register(Role)
        auditlog.register(Permission)
