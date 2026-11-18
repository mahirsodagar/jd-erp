"""Load the client's HTML for `lead.inactive.email` (the former MSG91
template `inactive_lead`) into the NotificationTemplate row. See
apps/notifications/email_html/ — overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "lead.inactive.email"
SUBJECT = "We'd love to stay in touch | JD Institute"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0015_lead_welcome_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
