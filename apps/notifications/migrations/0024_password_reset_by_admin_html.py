"""Load the client's HTML for `account.password_reset_by_admin.email`
(the former MSG91 template `password_reset_by_admin`) into the
NotificationTemplate row. See apps/notifications/email_html/ —
overwritten unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "account.password_reset_by_admin.email"
SUBJECT = "Your JD ERP password has been reset"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0023_portal_credentials_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
