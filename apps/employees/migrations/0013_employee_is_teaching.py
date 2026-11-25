# Teaching-staff flag (client, 2026-11-25): pickers list employees HR
# marks as teaching, whatever their designation, so an HOD who also
# teaches appears. Backfill: on for every employee whose designation is
# in TIMETABLE_FACULTY_DESIGNATIONS (default "Faculty"), off otherwise —
# nothing changes in the pickers on the day of deploy.

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def backfill(apps, schema_editor):
    Employee = apps.get_model("employees", "Employee")
    names = [
        n.strip() for n in
        (getattr(settings, "TIMETABLE_FACULTY_DESIGNATIONS", None) or ["Faculty"])
        if n and n.strip()
    ]
    match = Q()
    for n in names:
        match |= Q(designation__name__iexact=n)
    if names:
        Employee.objects.filter(match).update(is_teaching=True)


class Migration(migrations.Migration):

    dependencies = [
        ("employees", "0012_employee_aadhaar_number"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="is_teaching",
            field=models.BooleanField(
                default=False,
                help_text="Teaching staff: listed in timetable, mentor and "
                          "instructor pickers whatever the designation.",
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
