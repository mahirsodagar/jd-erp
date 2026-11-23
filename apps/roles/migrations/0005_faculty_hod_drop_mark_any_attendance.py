"""Take `academics.attendance.mark` off the Faculty and HOD roles.

Client rule (2026-11-21): when a class is scheduled, only the faculty
member assigned to it may mark its attendance. The assigned instructor is
always allowed by `_can_mark_attendance` without any key; the key is the
admin override for marking ANY slot. Holding it on a faculty-type role
let every faculty member mark every class, so it is removed from the two
system roles faculty are given. Admin and custom admin roles keep it.

Reversing re-adds the key to both roles.
"""

from django.db import migrations

KEY = "academics.attendance.mark"
ROLES = ("Faculty", "HOD")


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
        ("roles", "0004_permanent_system_roles"),
    ]

    operations = [
        migrations.RunPython(drop, restore),
    ]
