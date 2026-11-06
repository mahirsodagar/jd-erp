import django.db.models.deletion
from django.db import migrations, models


def backfill_campus_from_batch(apps, schema_editor):
    """Rows targeted at one batch already imply a campus; stamp it so
    the campus filters see them. Program-wide rows stay null (every
    campus), as they always behaved."""
    Assignment = apps.get_model("academics", "Assignment")
    for a in Assignment.objects.filter(campus__isnull=True,
                                       batch__isnull=False).select_related("batch"):
        a.campus_id = a.batch.campus_id
        a.save(update_fields=["campus"])


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0014_assignment_semester"),
        ("master", "0022_institute_letterhead_placement_institute_signature"),
    ]

    operations = [
        migrations.AddField(
            model_name="assignment",
            name="campus",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignments", to="master.campus",
            ),
        ),
        migrations.RunPython(backfill_campus_from_batch,
                             migrations.RunPython.noop),
    ]
