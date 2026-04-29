from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


def can_view_all_campuses(user) -> bool:
    return user.is_superuser or _has(user, "admissions.student.view_all_campuses")


def is_self_student(user, student) -> bool:
    return (
        user.is_authenticated and student is not None
        and student.user_account_id == user.id
    )


class StudentAccessPolicy(BasePermission):
    """Used on HR-facing endpoints. Students get separate `me/`
    endpoints — they should not hit the HR list."""

    message = "You do not have permission for this student."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return _has(u, "admissions.student.view")

    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_superuser or can_view_all_campuses(u):
            return True
        return u.campuses.filter(pk=obj.campus_id).exists()


def filter_visible(qs, user):
    if can_view_all_campuses(user):
        return qs
    return qs.filter(campus__in=user.campuses.all())
