from django.db import migrations


def backfill_program(apps, schema_editor):
    """Existing assignments were all batch-scoped; give each its batch's
    program so program-based visibility keeps working for them."""
    Assignment = apps.get_model("academics", "Assignment")
    for a in Assignment.objects.filter(
        program__isnull=True, batch__isnull=False,
    ).select_related("batch"):
        a.program_id = a.batch.program_id
        a.save(update_fields=["program"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0008_assignment_program_alter_assignment_batch"),
    ]

    operations = [
        migrations.RunPython(backfill_program, noop),
    ]
