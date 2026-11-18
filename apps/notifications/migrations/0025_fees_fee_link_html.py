"""Load the client's HTML for `fees.fee_link.email` (course installment /
registration / other-fee payment links sent from a student's Fees tab)
into the NotificationTemplate row. Vars Student_Name, Course_Name,
Fee_type, Payment_Link — built by `apps.fees.services.fee_link.
fee_link_context`. See apps/notifications/email_html/ — overwritten
unconditionally."""

from django.db import migrations

from apps.notifications.email_html import load_html

KEY = "fees.fee_link.email"
SUBJECT = "{institute} — Fee payment link ({installment})"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.update_or_create(
        key=KEY,
        defaults={"channel": "EMAIL", "subject_template": SUBJECT,
                  "body_template": load_html(KEY)},
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0024_password_reset_by_admin_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
