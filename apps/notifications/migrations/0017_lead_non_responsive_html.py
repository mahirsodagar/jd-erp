"""Load the client's HTML for `lead.non_responsive.email` (the former
MSG91 template `non_responsive`) into the NotificationTemplate row. See
apps/notifications/email_html/ — overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "lead.non_responsive.email"
SUBJECT = "JD Institute | Course Inquiry Follow-up"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0016_lead_inactive_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
