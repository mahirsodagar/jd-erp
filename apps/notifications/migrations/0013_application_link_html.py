"""Load the client's HTML for `lead.application_link.email` (the former
MSG91 template `application_form_link`) into the NotificationTemplate
row. The HTML lives in apps/notifications/email_html/ and is the
authoritative wording, so the row is overwritten regardless of what it
held (the interim plain text from 0007 or an admin edit)."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "lead.application_link.email"
SUBJECT = "JD Institute Application Form Link"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0012_account_and_portal_credential_templates"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
