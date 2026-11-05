"""Seed the `lead.non_responsive.email` template row (get_or_create —
never overwrites an admin-edited row)."""

from django.db import migrations

KEY = "lead.non_responsive.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "JD Institute | Course Inquiry Follow-up",
            "body_template": (
                "Dear {First_Name},\n\n"
                "We've tried reaching you a few times and haven't been able "
                "to connect. We understand you may be busy.\n\n"
                "Could you let us know a convenient time to talk to further "
                "address your queries regarding your Design course interest "
                "{Course_Name}? If you are no longer interested, please let "
                "us know as well.\n\n"
                "We look forward to your response.\n\n"
                "Warm regards,\nAdmissions Team\n"
                "JD School of Design | JD Institute of Fashion Technology"
            ),
            "description": "Lead marked Non Responsive (MSG91 non_responsive)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0005_lead_inactive_template")]
    operations = [migrations.RunPython(forwards, backwards)]
