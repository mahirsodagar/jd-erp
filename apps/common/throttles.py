"""Custom throttle scopes used across modules."""

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """Throttle login + refresh by IP. Pairs with django-axes username
    lockout (axes counts failures; throttle bounds total request rate)."""
    scope = "login"


class LeadIntakeThrottle(SimpleRateThrottle):
    """Throttle the public lead-intake endpoint by API key (when set) +
    fall back to IP."""
    scope = "lead_intake"

    def get_cache_key(self, request, view):
        api_key = request.headers.get("X-API-Key") or "no-key"
        ident = f"{api_key}:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}
