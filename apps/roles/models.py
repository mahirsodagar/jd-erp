from django.conf import settings
from django.db import models


class Permission(models.Model):
    """Catalogue of permission keys. Seeded per module (e.g.
    accounts.user.manage, sales.order.create). Tenant admins assign
    these to roles; they don't define new keys themselves."""

    key = models.CharField(max_length=120, unique=True)
    label = models.CharField(max_length=160)
    module = models.CharField(max_length=60, db_index=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("module", "key")

    def __str__(self):
        return self.key


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(
        default=False,
        help_text="System roles (e.g. Tenant Admin) cannot be deleted.",
    )

    permissions = models.ManyToManyField(
        Permission, related_name="roles", blank=True,
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="roles", blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name
