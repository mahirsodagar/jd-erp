"""Load the client's HTML for `academics.assignment_submitted.email`
(the former MSG91 template `assignment_submitted`) into the
NotificationTemplate row. The client's `{Faculty Name}`-style
placeholders were renamed to the underscored names the notifier passes
(Faculty_Name, Student_Name, Subject_Name, Assignment_Title); nothing
else changed. See apps/notifications/email_html/ — overwritten
unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "academics.assignment_submitted.email"
SUBJECT = "Assignment submitted: {Assignment_Title} — {Student_Name}"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0021_assignment_assigned_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
