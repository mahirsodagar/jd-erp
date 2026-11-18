"""Load the client's HTML for `lead.fee_link.email` (the former MSG91
template `application_fee_payment_link_3`) into the NotificationTemplate
row. See apps/notifications/email_html/ — the row is overwritten
unconditionally because that HTML is the authoritative wording."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "lead.fee_link.email"
SUBJECT = "Application Fee Payment Link"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0013_application_link_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
