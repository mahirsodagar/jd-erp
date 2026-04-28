"""Seed catalogue of permissions + default Admin role. Idempotent."""

from .models import Permission, Role


# Permission catalogue. Add new entries as new modules ship.
CATALOGUE = [
    # Module A — Authentication & Access Control
    ("accounts", "accounts.user.manage", "Manage users"),
    ("accounts", "accounts.user.view", "View users"),
    ("roles", "roles.role.manage", "Manage roles & permissions"),
    ("audit", "audit.log.view", "View audit logs"),
]


def seed_permissions():
    for module, key, label in CATALOGUE:
        Permission.objects.update_or_create(
            key=key,
            defaults={"module": module, "label": label},
        )


def seed_admin_role():
    role, _ = Role.objects.get_or_create(
        name="Admin",
        defaults={
            "description": "Full access — assign sparingly.",
            "is_system": True,
        },
    )
    role.is_system = True
    role.save(update_fields=["is_system"])
    role.permissions.set(Permission.objects.all())
    return role


def seed_all():
    seed_permissions()
    seed_admin_role()
