from django.conf import settings
from django.db import models


class AuthLog(models.Model):
    """Authentication / access-control events. Distinct from
    django-auditlog's data-change log (which tracks model row changes).

    Both tables live inside each tenant schema, so logs never leak
    across tenants.
    """

    class Event(models.TextChoices):
        LOGIN_SUCCESS = "login_success", "Login success"
        LOGIN_FAILURE = "login_failure", "Login failure"
        LOGOUT = "logout", "Logout"
        PASSWORD_CHANGE = "password_change", "Password change (self)"
        PASSWORD_RESET = "password_reset", "Password reset (admin)"
        ROLE_CREATE = "role_create", "Role created"
        ROLE_UPDATE = "role_update", "Role updated"
        ROLE_DELETE = "role_delete", "Role deleted"
        LOCKOUT = "lockout", "Account locked out"

    event = models.CharField(max_length=32, choices=Event.choices, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="auth_log_actions",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="auth_log_targets",
    )
    identifier = models.CharField(
        max_length=160, blank=True,
        help_text="Login identifier supplied (for failed logins where actor is unknown).",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["event", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
