from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class ScheduleAccess(BasePermission):
    """Mutation gate for schedule-backed endpoints.

    Reads pass through for any authenticated user — the attendance
    report views ride on this class and do their own, finer checks
    (a student may read their OWN attendance). Mutations require the
    matching granular `academics.schedule.{add,edit,delete}` permission.

    For the staff timetable itself, use `TimetableAccess` below, which
    also gates reads.
    """

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


class TimetableAccess(ScheduleAccess):
    """`ScheduleAccess` plus a read gate for the staff timetable.

    Reading the institute timetable used to be open to any authenticated
    user, so anyone with a login could enumerate every instructor's
    teaching load and every batch's schedule. Staff now need
    `academics.schedule.view`.

    Students and instructors are unaffected: they reach their own
    sessions through `MyTimetableView` (/schedule/me), which is not
    behind this class.
    """

    message = "Permission denied for the timetable."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return has_perm(u, "academics.schedule.view")
        return super().has_permission(request, view)
