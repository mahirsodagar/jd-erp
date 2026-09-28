"""Register the Drop Out / Re-activate permission keys and give them to
Admin — as a data migration so production gets them on `migrate`
without re-running `seed_permissions` (which resets customised roles).
"""

from django.db import migrations

KEYS = [
    ("admissions.student.dropout", "Mark a student as Dropout (with remarks)"),
    ("admissions.student.reactivate", "Re-activate a dropped-out student"),
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("roles", "Permission")
    Role = apps.get_model("roles", "Role")
    perms = [
        Permission.objects.update_or_create(
            key=key, defaults={"module": "admissions", "label": label},
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
        ("admissions", "0012_student_status_change"),
        ("roles", "0004_permanent_system_roles"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
