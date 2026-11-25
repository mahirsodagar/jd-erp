"""System e-mail templates now live in `SystemEmailTemplate` (admin
editable, Communication → System Emails) and fall back to the code
defaults in `apps.notifications.registry`.

The EMAIL rows in `NotificationTemplate` are no longer read for mail:
the registry carries the same client HTML and wording as the code
default, and those rows were never editable from the product (the
notifications app registers nothing in Django admin), so there is no
hand customisation to carry across. They stay in place for the SMS /
WhatsApp channels and for old dispatch-log rows.

Seeds the blank global layout row so the Layout tab has something to
edit on first open.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Layout = apps.get_model("notifications", "EmailLayout")
    if not Layout.objects.filter(institute__isnull=True).exists():
        Layout.objects.create(institute=None, header_html="", footer_html="", is_enabled=True)


class Migration(migrations.Migration):
    dependencies = [("notifications", "0026_system_email_templates")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
