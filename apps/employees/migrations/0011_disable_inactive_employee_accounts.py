"""Disable the portal account of every employee already marked Inactive.

Until now deactivating an employee only changed the HR status; the
linked user stayed active and could still log in. `set_status` now
disables the account going forward; this catches the ones done before.
"""

from django.db import migrations


def disable_accounts(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    User = apps.get_model("accounts", "User")
    INACTIVE = 1
    ids = Employee.objects.filter(
        status=INACTIVE, user_account__isnull=False,
    ).values_list("user_account_id", flat=True)
    User.objects.filter(pk__in=list(ids), is_active=True).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0010_holiday_permissions"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(disable_accounts, migrations.RunPython.noop),
    ]
