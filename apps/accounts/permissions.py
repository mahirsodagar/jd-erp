from rest_framework.permissions import BasePermission


# Maps the HTTP method to the granular CRUD suffix used when a view
# declares `perm_base` instead of a single `required_perm`.
METHOD_PERM_SUFFIX = {
    "GET": "view",
    "HEAD": "view",
    "OPTIONS": "view",
    "POST": "add",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}


class HasPerm(BasePermission):
    """Checks that the request user has the required permission. Superusers bypass.

    A view declares its requirement in one of two ways:

    - `required_perm = "accounts.user.view"` — a single fixed key, checked
      for every method. Use for non-CRUD / action endpoints.
    - `perm_base = "master.campus"` — a CRUD resource base. The actual key
      is resolved per request method via `METHOD_PERM_SUFFIX`, e.g. a GET
      needs `master.campus.view`, a POST `master.campus.add`, PATCH/PUT
      `master.campus.edit`, DELETE `master.campus.delete`.

    Permission keys map to Permission rows attached to a user's roles.
    """

    message = "You do not have permission to perform this action."

    def _resolve(self, request, view):
        perm = getattr(view, "required_perm", None)
        if perm:
            return perm
        base = getattr(view, "perm_base", None)
        if base:
            suffix = METHOD_PERM_SUFFIX.get(request.method, "edit")
            return f"{base}.{suffix}"
        return None

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        perm = self._resolve(request, view)
        if not perm:
            return True
        return user.roles.filter(permissions__key=perm).exists()
