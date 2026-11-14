"""Attendance keeps only Present / Absent / Late (2026-11-14).

Existing rows are remapped so no percentage moves: ON_DUTY already
counted as present-like → PRESENT; EXCUSED never did → ABSENT. The
original status is kept in the note so it can be seen later.
"""

from django.db import migrations, models


def remap(apps, schema_editor):
    Attendance = apps.get_model("academics", "Attendance")
    for old, new in (("ON_DUTY", "PRESENT"), ("EXCUSED", "ABSENT")):
        for row in Attendance.objects.filter(status=old).iterator():
            tag = f"[was {old.replace('_', ' ').title()}]"
            note = (row.note or "").strip()
            row.note = (f"{tag} {note}".strip())[:200]
            row.status = new
            row.save(update_fields=["status", "note"])


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0016_certificate_noc_type"),
    ]

    operations = [
        migrations.RunPython(remap, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[("PRESENT", "Present"), ("ABSENT", "Absent"),
                         ("LATE", "Late")],
                max_length=10,
            ),
        ),
    ]
