from rest_framework.permissions import BasePermission


class LeadVisibility(BasePermission):
    """Counselors see only leads where assign_to == self; users with
    `leads.lead.view_all` see everything. Superusers bypass.

    Object-level check is in `has_object_permission`; queryset-level
    filtering is done in the view via `filter_visible(qs, user)` below.
    """

    message = "You do not have permission to view this lead."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return _has_perm(u, "leads.lead.view_all") or _has_perm(u, "leads.lead.view")

    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_superuser or _has_perm(u, "leads.lead.view_all"):
            return True
        return obj.assign_to_id == u.id


def _has_perm(user, key: str) -> bool:
    return user.roles.filter(permissions__key=key).exists()


def can_see_all_leads(user) -> bool:
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or _has_perm(user, "leads.lead.view_all"))
    )


def filter_visible(qs, user):
    """Apply visibility scope to a Lead queryset."""
    if can_see_all_leads(user):
        return qs
    return qs.filter(assign_to=user)
