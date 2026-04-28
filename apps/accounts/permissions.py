from rest_framework.permissions import BasePermission


class HasPerm(BasePermission):
    """Checks that the request user has the permission key declared on
    the view as `required_perm`. Superusers bypass.

    Permission keys are simple strings like 'accounts.user.manage' that
    map to Permission rows attached to a user's roles.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        perm = getattr(view, "required_perm", None)
        if not perm:
            return True
        return user.roles.filter(permissions__key=perm).exists()
