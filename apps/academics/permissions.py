from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class ScheduleAccess(BasePermission):
    """Read access for any authenticated user (so instructors / students
    can fetch their timetable). Mutations require `academics.schedule.manage`."""

    message = "Permission denied for schedule changes."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return has_perm(u, "academics.schedule.manage")
