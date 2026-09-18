"""Stop storing portal passwords in plain text.

`Student.portal_temp_password` (and `Employee.portal_temp_password`, in
employees 0007) held the last issued password so staff could read it
back. The column is dropped — a password is now shown once when issued.

Student and Employee are registered with django-auditlog, so every write
to the column also left the plaintext in `LogEntry.changes` (and in
`serialized_data` where enabled). Those copies are scrubbed here too;
an entry whose only change was the password is deleted outright.
"""

from django.db import migrations

FIELD = "portal_temp_password"


def scrub_audit_log(apps, schema_editor):
    LogEntry = apps.get_model("auditlog", "LogEntry")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content_types = ContentType.objects.filter(
        app_label__in=["admissions", "employees"],
        model__in=["student", "employee"],
    )
    entries = LogEntry.objects.filter(
        content_type__in=content_types, changes__icontains=FIELD,
    )
    for entry in entries.iterator():
        changes = entry.changes if isinstance(entry.changes, dict) else {}
        changes.pop(FIELD, None)
        if not changes:
            entry.delete()
            continue
        entry.changes = changes
        update = ["changes"]
        data = entry.serialized_data
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            data["fields"].pop(FIELD, None)
            entry.serialized_data = data
            update.append("serialized_data")
        entry.save(update_fields=update)

    # Entries without a change to the column can still carry it in a
    # full-object snapshot.
    for entry in LogEntry.objects.filter(
        content_type__in=content_types, serialized_data__icontains=FIELD,
    ).iterator():
        data = entry.serialized_data
        if isinstance(data, dict) and isinstance(data.get("fields"), dict):
            data["fields"].pop(FIELD, None)
            entry.serialized_data = data
            entry.save(update_fields=["serialized_data"])


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0010_student_aadhaar_number'),
        ('auditlog', '0015_alter_logentry_changes'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(scrub_audit_log, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='student',
            name='portal_temp_password',
        ),
    ]
