from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class ScheduleAccess(BasePermission):
    """Read access for any authenticated user (so instructors / students
    can fetch their timetable). Mutations require the matching granular
    `academics.schedule.{add,edit,delete}` permission."""

    message = "Permission denied for schedule changes."

    _SUFFIX = {"POST": "add", "PUT": "edit", "PATCH": "edit", "DELETE": "delete"}

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        suffix = self._SUFFIX.get(request.method, "edit")
        return has_perm(u, f"academics.schedule.{suffix}")
