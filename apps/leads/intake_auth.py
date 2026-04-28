"""API-key auth for the public lead-intake endpoint.

External systems (website forms, ad platforms, Zapier) POST leads with
an `X-API-Key` header. The key lives in the LEAD_INTAKE_API_KEY env var.
There is no user behind the request — `request.user` will be
AnonymousUser, and the view should not assume otherwise.
"""

import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasIntakeApiKey(BasePermission):
    message = "Invalid or missing intake API key."

    def has_permission(self, request, view):
        configured = getattr(settings, "LEAD_INTAKE_API_KEY", "") or ""
        if not configured:
            # If the key is unset in env, refuse all intake requests
            # rather than silently accepting them.
            return False
        provided = request.headers.get("X-API-Key", "")
        return bool(provided) and hmac.compare_digest(provided, configured)
