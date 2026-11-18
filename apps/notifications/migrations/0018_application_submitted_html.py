"""Load the client's HTML for `admissions.application_submitted.email`
(the former MSG91 template `application_submitted_3`) into the
NotificationTemplate row. See apps/notifications/email_html/ —
overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "admissions.application_submitted.email"
SUBJECT = "Application Received - JD Institute"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0017_lead_non_responsive_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
