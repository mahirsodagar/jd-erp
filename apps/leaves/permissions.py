from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class LeaveAccessPolicy(BasePermission):
    """Authentication + the *minimum* read perm to use any leave endpoint."""

    message = "Authentication required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated)


def get_employee_for(user):
    """The Employee record linked to this User, or None if the user is
    HR-only (no Employee row, like the bootstrap superuser)."""
    return getattr(user, "employee", None)
