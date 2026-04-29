from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


def can_view_all(user) -> bool:
    return user.is_superuser or _has(user, "fees.receipt.view_all")


def visible_enrollments_filter(qs, user):
    """Apply campus scope to a queryset of FeeReceipt / Installment /
    Concession by walking through their `enrollment` FK."""
    if can_view_all(user):
        return qs
    return qs.filter(enrollment__campus__in=user.campuses.all())


class FeeAccessPolicy(BasePermission):
    """Authentication + minimum receipt-read perm to use any fee endpoint."""

    message = "Fee access requires the appropriate role."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return _has(u, "fees.receipt.view") or _has(u, "fees.receipt.view_all")

    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_superuser or can_view_all(u):
            return True
        enrollment = getattr(obj, "enrollment", obj)
        return u.campuses.filter(pk=enrollment.campus_id).exists()
