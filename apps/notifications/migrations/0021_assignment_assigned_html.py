"""Load the client's HTML for `academics.assignment_assigned.email` (the
former MSG91 template `assignmentassigned`, positional VAR1..VAR5) into
the NotificationTemplate row. See apps/notifications/email_html/ —
overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "academics.assignment_assigned.email"
SUBJECT = "New Assignment: {VAR3}"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0020_student_leave_applied_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
