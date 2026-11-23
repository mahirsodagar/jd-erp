"""Time slots stop being per academic year.

Client request 2026-11-23: one set of slots shared by every year, so
nobody re-creates "Lecture 1" each session, and the Publish Timetable
page offers every active slot whatever year is picked.

Before the column goes, slots that exist once per year under the same
label are merged into the oldest row: every ScheduleSlot pointing at a
later duplicate is re-pointed, then the duplicate is deleted. (On prod
this is "Lecture 1" for 2026 and 2027, the 2027 copy unused.)

Reversing re-adds the column as nullable; the merged rows are gone.
"""

from django.db import migrations, models


def merge_duplicate_labels(apps, schema_editor):
    TimeSlot = apps.get_model("master", "TimeSlot")
    ScheduleSlot = apps.get_model("academics", "ScheduleSlot")
    seen: dict[str, int] = {}
    for ts in TimeSlot.objects.order_by("id"):
        key = ts.label.strip().lower()
        keep_id = seen.get(key)
        if keep_id is None:
            seen[key] = ts.id
            continue
        ScheduleSlot.objects.filter(time_slot_id=ts.id).update(time_slot_id=keep_id)
        ts.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("master", "0027_program_degree_type_help_text"),
        ("academics", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_labels, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="timeslot", unique_together=set()),
        migrations.RemoveField(model_name="timeslot", name="academic_year"),
        migrations.AlterField(
            model_name="timeslot",
            name="label",
            field=models.CharField(
                help_text="e.g. Slot 1, Forenoon", max_length=40, unique=True,
            ),
        ),
        migrations.AlterModelOptions(
            name="timeslot",
            options={"ordering": ("sort_order", "start_time")},
        ),
    ]
