"""Relieving Managers master (L1–L4 per institute) + Full-time to
Part-time application type + per-approval level label.

Seeds four rows per active institute with the legacy level titles.
L3 / L4 are pre-filled from the old RELIEVING_L3/L4_APPROVER_EMAIL
settings when those still match an active employee, so an existing
deployment keeps routing to the same Principal / HR without HR having
to re-enter them. L1 / L2 start empty — the old per-employee reporting
managers are not a per-institute value — and submission is blocked
until HR fills them in from the master page."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

LABELS = {1: "Academic Manager", 2: "Vice Principal", 3: "Principal",
          4: "Operations / HR"}


def seed_managers(apps, schema_editor):
    Institute = apps.get_model("master", "Institute")
    Employee = apps.get_model("employees", "Employee")
    RelievingManager = apps.get_model("relieving", "RelievingManager")
    RelievingApproval = apps.get_model("relieving", "RelievingApproval")

    def by_email(email):
        email = (email or "").strip()
        if not email:
            return None
        return (Employee.objects
                .filter(email_primary__iexact=email, status=0, is_deleted=False)
                .first())

    l3 = by_email(getattr(settings, "RELIEVING_L3_APPROVER_EMAIL", ""))
    l4 = by_email(getattr(settings, "RELIEVING_L4_APPROVER_EMAIL", ""))
    for inst in Institute.objects.filter(is_active=True):
        for level, label in LABELS.items():
            RelievingManager.objects.get_or_create(
                institute=inst, level=level,
                defaults={"label": label,
                          "approver": {3: l3, 4: l4}.get(level)},
            )

    # Backfill labels on historical approval rows.
    for level, label in LABELS.items():
        RelievingApproval.objects.filter(level=level, label="").update(label=label)


class Migration(migrations.Migration):

    dependencies = [
        ("relieving", "0002_experience_letter_sent_at"),
        ("master", "0023_program_id_card_affiliation"),
        ("employees", "0012_employee_aadhaar_number"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RelievingManager",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("level", models.PositiveSmallIntegerField()),
                ("label", models.CharField(
                    help_text="Shown as the level's title (e.g. 'Vice Principal').",
                    max_length=60)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approver", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="relieving_manager_levels",
                    to="employees.employee")),
                ("institute", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="relieving_managers",
                    to="master.institute")),
                ("updated_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("institute", "level"),
                "unique_together": {("institute", "level")},
            },
        ),
        migrations.AddField(
            model_name="relievingapplication",
            name="application_type",
            field=models.CharField(
                choices=[("RELIEVING", "Relieving"),
                         ("PART_TIME", "Full-time to Part-time")],
                db_index=True, default="RELIEVING", max_length=12),
        ),
        migrations.AddField(
            model_name="relievingapproval",
            name="label",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AlterField(
            model_name="relievingapproval",
            name="status",
            field=models.CharField(
                choices=[("PENDING", "Pending"), ("APPROVED", "Approved"),
                         ("REJECTED", "Rejected"), ("SKIPPED", "Skipped")],
                default="PENDING", max_length=10),
        ),
        migrations.RunPython(seed_managers, migrations.RunPython.noop),
    ]
