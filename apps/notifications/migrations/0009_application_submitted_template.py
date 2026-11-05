"""Seed the `admissions.application_submitted.email` template row
(get_or_create — never overwrites an admin-edited row)."""

from django.db import migrations

KEY = "admissions.application_submitted.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "Application Received - JD Institute",
            "body_template": (
                "Dear {Student_Name},\n\n"
                "Thank you for submitting your application for {Course_Name} "
                "at JD Institute. We're pleased to confirm that your "
                "application has been received.\n\n"
                "Your application details\n"
                "  Application ID     : {Application_ID}\n"
                "  Course applied for : {Course_Name}\n"
                "  Date of submission : {Submission_Date}\n\n"
                "What happens next\n"
                "  1. Our admissions team will review your application.\n"
                "  2. Pay your College Registration Fee to reserve the seat.\n\n"
                "Warm regards,\nAdmissions Team\n"
                "JD School of Design | JD Institute of Fashion Technology"
            ),
            "description": "Application received, student copy (MSG91 application_submitted_3)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0008_fee_link_template_v2")]
    operations = [migrations.RunPython(forwards, backwards)]
