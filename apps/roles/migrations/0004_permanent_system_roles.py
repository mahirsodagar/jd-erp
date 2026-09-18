"""Make Faculty, HOD and HR permanent (system) roles, like Admin.

Creates any that don't exist yet (matched case-insensitively, so an
existing "Hod" is adopted rather than duplicated) and flags them
`is_system`. Permissions are left exactly as they are.
Reversing only clears the flag; created roles are kept.
"""

from django.db import migrations

ROLES = {
    "Faculty": "Baseline access for employees.",
    "HOD": "Head of department.",
    "HR": "Human resources.",
}


def forwards(apps, schema_editor):
    Role = apps.get_model("roles", "Role")
    for name, description in ROLES.items():
        role = Role.objects.filter(name__iexact=name).first()
        if role is None:
            Role.objects.create(name=name, description=description,
                                is_system=True)
        elif not role.is_system:
            role.is_system = True
            role.save(update_fields=["is_system"])


def backwards(apps, schema_editor):
    Role = apps.get_model("roles", "Role")
    Role.objects.filter(name__in=["HOD", "HR"]).update(is_system=False)


class Migration(migrations.Migration):

    dependencies = [
        ("roles", "0003_faculty_drop_leave_report"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
