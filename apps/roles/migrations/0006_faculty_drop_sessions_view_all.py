"""Take `dashboard.sessions.view_all` off the Faculty role.

Client rule (2026-11-23): the dashboard's Today's Sessions strip shows a
faculty member only the classes they are assigned to. The strip already
reads /timetable/me/ (instructor-filtered server-side) unless the user
holds `dashboard.sessions.view_all`, which switches it to the
institute-wide list. The Faculty role picked that key up from the
one-off permission backfill (it keyed off `academics.schedule.view_all`),
and since every employee carries Faculty as their baseline role, every
login saw everyone's sessions. Admin roles and HOD keep the key.

Reversing re-adds the key to Faculty.
"""

from django.db import migrations

KEY = "dashboard.sessions.view_all"
ROLES = ("Faculty",)


def _targets(apps):
    Role = apps.get_model("roles", "Role")
    Permission = apps.get_model("roles", "Permission")
    perm = Permission.objects.filter(key=KEY).first()
    roles = [r for name in ROLES
             if (r := Role.objects.filter(name__iexact=name).first())]
    return roles, perm


def drop(apps, schema_editor):
    roles, perm = _targets(apps)
    if perm is None:
        return
    for role in roles:
        role.permissions.remove(perm)


def restore(apps, schema_editor):
    roles, perm = _targets(apps)
    if perm is None:
        return
    for role in roles:
        role.permissions.add(perm)


class Migration(migrations.Migration):

    dependencies = [
        ("roles", "0005_faculty_hod_drop_mark_any_attendance"),
    ]

    operations = [
        migrations.RunPython(drop, restore),
    ]
