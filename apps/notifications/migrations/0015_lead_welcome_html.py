"""Load the client's HTML for `lead.welcome.email` (the former MSG91
template `lead_welcome`) into the NotificationTemplate row. See
apps/notifications/email_html/ — overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "lead.welcome.email"
SUBJECT = "Welcome Note for New Students and Parents"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0014_fee_link_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
