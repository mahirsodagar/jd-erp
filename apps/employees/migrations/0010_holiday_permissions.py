"""Register the Holiday Calendar permission keys and give them to Admin.

Done as a data migration so production picks them up on `migrate`
without re-running `seed_permissions`, which would reset customised
role grants.
"""

from django.db import migrations

KEYS = [
    ("hr.holiday.add", "Add a holiday to the calendar"),
    ("hr.holiday.edit", "Edit a holiday"),
    ("hr.holiday.delete", "Delete a holiday"),
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("roles", "Permission")
    Role = apps.get_model("roles", "Role")
    perms = [
        Permission.objects.update_or_create(
            key=key, defaults={"module": "hr", "label": label},
        )[0]
        for key, label in KEYS
    ]
    admin = Role.objects.filter(name="Admin").first()
    if admin is not None:
        admin.permissions.add(*perms)


def backwards(apps, schema_editor):
    Permission = apps.get_model("roles", "Permission")
    Permission.objects.filter(key__in=[k for k, _ in KEYS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("employees", "0009_holiday"),
        ("roles", "0004_permanent_system_roles"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
