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
    """Throttle the public lead-intake endpoint per IP.

    The bucket used to include the presented API key, so a caller could
    reset it by changing the key — and since DRF checks permissions
    before throttles, guessing keys was never throttled at all. Views
    using this throttle run it before the key check (see
    `ThrottleBeforePermissionMixin`)."""
    scope = "lead_intake"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope, "ident": self.get_ident(request),
        }


class ThrottleBeforePermissionMixin:
    """APIView mixin: run throttles BEFORE permission checks so that a
    flood of bad API keys / tokens is rate-limited too. DRF's default
    order (permissions, then throttles) only ever throttles callers
    who are already authorised."""

    def initial(self, request, *args, **kwargs):
        self.format_kwarg = self.get_format_suffix(**kwargs)
        neg = self.perform_content_negotiation(request)
        request.accepted_renderer, request.accepted_media_type = neg
        version, scheme = self.determine_version(request, *args, **kwargs)
        request.version, request.versioning_scheme = version, scheme
        self.perform_authentication(request)
        self.check_throttles(request)
        self.check_permissions(request)


class WebsiteWebhookThrottle(AnonRateThrottle):
    """Throttle the website (Forminator) webhook per IP. Looser than
    lead_intake because the whole website posts from one server."""
    scope = "website_webhook"


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
