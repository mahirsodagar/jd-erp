from rest_framework.permissions import BasePermission


class IsSuperuser(BasePermission):
    """Audit logs are viewable by superusers only (per spec)."""

    message = "Audit logs are restricted to superusers."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)
