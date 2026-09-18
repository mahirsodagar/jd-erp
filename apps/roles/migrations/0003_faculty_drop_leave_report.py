"""Take `leaves.report.view` off the Faculty role.

It was in the Faculty baseline only so the sidebar would show the Leaves
menu, but the key also opens the campus-wide leave report — so every
employee could read their colleagues' leaves. The Leaves menu is now
shown to anyone with an employee profile, and the key is no longer part
of `FACULTY_PERMISSION_KEYS`.

Only the Faculty role is touched: a role an admin deliberately gave the
report (HR, HoD, …) keeps it. Reversing re-adds it to Faculty.
"""

from django.db import migrations

KEY = "leaves.report.view"
ROLE = "Faculty"


def _faculty_and_perm(apps):
    Role = apps.get_model("roles", "Role")
    Permission = apps.get_model("roles", "Permission")
    return (Role.objects.filter(name=ROLE).first(),
            Permission.objects.filter(key=KEY).first())


def drop(apps, schema_editor):
    role, perm = _faculty_and_perm(apps)
    if role and perm:
        role.permissions.remove(perm)


def restore(apps, schema_editor):
    role, perm = _faculty_and_perm(apps)
    if role and perm:
        role.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("roles", "0002_granular_permissions"),
    ]

    operations = [
        migrations.RunPython(drop, restore),
    ]
