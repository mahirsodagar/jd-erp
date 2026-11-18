"""Load the client's HTML for `student.portal_credentials.email` (the
former MSG91 template `student_portal_credentials`) into the
NotificationTemplate row. See apps/notifications/email_html/ —
overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "student.portal_credentials.email"
SUBJECT = "Your student portal login"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0022_assignment_submitted_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
