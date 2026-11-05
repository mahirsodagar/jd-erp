"""Move `lead.fee_link.email` to the new MSG91 template wording
(application_fee_payment_link_3). The row is updated only if it still
holds the old seeded subject — an admin-edited row is left alone."""

from django.db import migrations

KEY = "lead.fee_link.email"
OLD_SUBJECT = "{institute} — Application fee payment link"
OLD_BODY = (
    "Dear {name},\n\n"
    "Thank you for choosing {institute} for your Design/Art/Media "
    "course.\n\n"
    "Click the link below to pay your fees and complete the "
    "admission process:\n\n{url}\n\n"
    "Best Regards,\nJD Admissions Team"
)
NEW_SUBJECT = "Application Fee Payment Link"
NEW_BODY = (
    "Dear {Student_Name},\n\n"
    "Thank you for your interest in {Course_Name} at JD Institute.\n\n"
    "To begin your application, please pay the application fee using "
    "the secure link below:\n\n{Payment_Link}\n\n"
    "Please note: the application form link will be shared with you as "
    "soon as your payment is confirmed.\n\n"
    "Warm regards,\nAdmissions Team\n"
    "JD School of Design | JD Institute of Fashion Technology"
)


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    row = T.objects.filter(key=KEY).first()
    if row is None:
        T.objects.create(key=KEY, channel="EMAIL",
                         subject_template=NEW_SUBJECT, body_template=NEW_BODY)
    elif row.subject_template == OLD_SUBJECT:
        row.subject_template, row.body_template = NEW_SUBJECT, NEW_BODY
        row.save(update_fields=["subject_template", "body_template"])


def backwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.filter(key=KEY, subject_template=NEW_SUBJECT).update(
        subject_template=OLD_SUBJECT, body_template=OLD_BODY,
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0007_application_link_template_v2")]
    operations = [migrations.RunPython(forwards, backwards)]
