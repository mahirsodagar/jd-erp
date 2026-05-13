"""Custom throttle scopes used across modules.

These all use Django's cache framework (default LocMemCache in dev /
single-worker PA, swap to Redis for multi-worker prod). The rate
strings live in DRF_SETTINGS["DEFAULT_THROTTLE_RATES"] and can be
overridden via env vars (THROTTLE_LOGIN etc.)."""

from rest_framework.throttling import (
    AnonRateThrottle, SimpleRateThrottle, UserRateThrottle,
)


class LoginRateThrottle(AnonRateThrottle):
    """Throttle login + refresh by IP. Pairs with django-axes username
    lockout (axes counts failures; throttle bounds total request rate
    so an attacker can't burn through axes' 5-failure window across
    many usernames at high speed)."""
    scope = "login"


class LeadIntakeThrottle(SimpleRateThrottle):
    """Throttle the public lead-intake endpoint by API key + IP. When
    no API key is present, falls back to IP alone (a misconfigured
    caller can still be rate-limited)."""
    scope = "lead_intake"

    def get_cache_key(self, request, view):
        api_key = request.headers.get("X-API-Key") or "no-key"
        ident = f"{api_key}:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class PasswordChangeThrottle(UserRateThrottle):
    """Throttle password-change requests per authenticated user.
    Tighter than the default user rate to slow credential-replay /
    enumeration if a stolen JWT is in play."""
    scope = "password_change"


class ForgotPasswordThrottle(AnonRateThrottle):
    """Throttle forgot/reset endpoints by IP — keeps an attacker from
    spamming the forgot endpoint to discover account existence (also a
    backstop on email-cost abuse)."""
    scope = "forgot_password"
