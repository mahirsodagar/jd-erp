"""Move `lead.application_link.email` to the new MSG91 template wording
(application_form_link). The row is updated only if it still holds the
old seeded subject — an admin-edited row is left alone."""

from django.db import migrations

KEY = "lead.application_link.email"
OLD_SUBJECT = "JD Student Application Link : {name}"
OLD_BODY = (
    "Greetings from JD!\nDear {name},\n\n"
    "Thank you for selecting JD, Your inquiry has been submitted.\n\n"
    "Please click the link to complete your application - {url}\n\n"
    "With Regards,\nJD"
)
NEW_SUBJECT = "JD Institute Application Form Link"
NEW_BODY = (
    "Dear {Student_Name},\n\n"
    "Thank you for your interest in {Course_Name} at JD Institute.\n\n"
    "You can now take the next step by completing your application form "
    "using the link below:\n\n{Application_Form_Link}\n\n"
    "Before you begin, please keep these ready:\n"
    "  - Academic marksheets (10th to up to latest qualification)\n"
    "  - Passport-size photograph with white background\n"
    "  - Adhaar ID proof\n\n"
    "Once you submit the form, our admissions team will review your "
    "application and contact you with the next steps.\n\n"
    "We look forward to welcoming you to JD Institute.\n\n"
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
    dependencies = [("notifications", "0006_lead_non_responsive_template")]
    operations = [migrations.RunPython(forwards, backwards)]
