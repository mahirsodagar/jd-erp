"""Load the client's HTML for `student_leaves.applied.email` (the former
MSG91 template `student_leave_application_`) into the
NotificationTemplate row. See apps/notifications/email_html/ —
overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "student_leaves.applied.email"
SUBJECT = "Student Leave Application Submitted"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0019_student_leave_accepted_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
