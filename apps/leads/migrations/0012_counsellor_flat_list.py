"""Replace the per-category counsellor pools with one flat counsellor list.

Counsellors are now Employees rather than bare Users, so existing pool
members carry over only where their User is linked to an Employee record
(`Employee.user_account`). Anyone else is dropped — the migration prints
their usernames so they can be re-added by hand from the Counsellors
page once their employee record is linked.
"""

import django.db.models.deletion
from django.db import migrations, models


def pools_to_counsellors(apps, schema_editor):
    Membership = apps.get_model("leads", "CounsellorPoolMembership")
    Employee = apps.get_model("employees", "Employee")
    Counsellor = apps.get_model("leads", "Counsellor")
    Rotation = apps.get_model("leads", "CounsellorRotation")

    Rotation.objects.get_or_create(pk=1, defaults={"pointer": 0})

    # A user could sit in several pools; collapse to one row, keeping the
    # keenest sort_order and treating them as active if any membership was.
    collapsed = {}
    for m in Membership.objects.all():
        prev = collapsed.get(m.user_id)
        if prev is None:
            collapsed[m.user_id] = {"sort_order": m.sort_order, "is_active": m.is_active}
        else:
            prev["sort_order"] = min(prev["sort_order"], m.sort_order)
            prev["is_active"] = prev["is_active"] or m.is_active

    if not collapsed:
        return

    employees = {
        e.user_account_id: e
        for e in Employee.objects.filter(
            user_account_id__in=collapsed, is_deleted=False,
        )
    }

    orphans = []
    for user_id, vals in collapsed.items():
        employee = employees.get(user_id)
        if employee is None:
            orphans.append(user_id)
            continue
        Counsellor.objects.get_or_create(
            employee_id=employee.id,
            defaults={"sort_order": vals["sort_order"], "is_active": vals["is_active"]},
        )

    if orphans:
        User = apps.get_model("accounts", "User")
        names = list(
            User.objects.filter(id__in=orphans).values_list("username", flat=True)
        )
        print(
            "\n  Skipped %d pool member(s) with no employee record: %s"
            % (len(names), ", ".join(names))
        )


def noop_reverse(apps, schema_editor):
    """Pools are gone; there is nothing faithful to restore into them."""


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0006_employee_employment_category"),
        ("leads", "0011_lead_fee_link_sent_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Counsellor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("sort_order", models.PositiveSmallIntegerField(
                    default=100,
                    help_text="Stable rotation order — counsellors with a lower "
                              "sort_order get leads first.")),
                ("is_active", models.BooleanField(
                    default=True,
                    help_text="Paused counsellors are skipped by the round-robin "
                              "but keep the leads they already hold.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("employee", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="counsellor", to="employees.employee")),
            ],
            options={"ordering": ("sort_order", "id")},
        ),
        migrations.CreateModel(
            name="CounsellorRotation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("pointer", models.PositiveIntegerField(
                    default=0,
                    help_text="Round-robin offset; advanced after each assignment.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(pools_to_counsellors, noop_reverse),
        migrations.DeleteModel(name="CounsellorPoolMembership"),
        migrations.DeleteModel(name="CounsellorPool"),
    ]
