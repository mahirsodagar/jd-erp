from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def can_view_all_campuses(user) -> bool:
    return user.is_superuser or _has(user, "employees.employee.view_all_campuses")


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class EmployeeAccessPolicy(BasePermission):
    """Listing & retrieval are auto-scoped to the caller's `User.campuses`
    unless they have `employees.employee.view_all_campuses`. The viewset
    is responsible for `filter_visible(qs, user)` on lists; this class
    enforces the object-level rule on detail views."""

    message = "You do not have permission for this employee."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return _has(u, "employees.employee.view")

    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_superuser or can_view_all_campuses(u):
            return True
        # Self always allowed to read own record.
        if obj.user_account_id == u.id:
            return True
        # Otherwise must be in caller's campuses.
        return u.campuses.filter(pk=obj.campus_id).exists()


def filter_visible(qs, user):
    if can_view_all_campuses(user):
        return qs
    # Caller sees employees within their campuses, plus their own record.
    own_id = getattr(user, "id", None)
    return qs.filter(campus__in=user.campuses.all()) | qs.filter(user_account_id=own_id)


def is_self(user, employee) -> bool:
    return user.is_authenticated and employee.user_account_id == user.id
