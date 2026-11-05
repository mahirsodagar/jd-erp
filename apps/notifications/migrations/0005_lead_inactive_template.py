"""Seed the `lead.inactive.email` template row (get_or_create — never
overwrites an admin-edited row)."""

from django.db import migrations

KEY = "lead.inactive.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "We'd love to stay in touch | JD Institute",
            "body_template": (
                "Dear {First_Name},\n\n"
                "It's been a while since we last connected. If your plans "
                "have changed, no problem at all.\n\n"
                "If you'd like to revisit your options, just let us know "
                "and we'll pick up where we left off.\n\n"
                "Warm regards,\nAdmissions Team\n"
                "JD School of Design | JD Institute of Fashion Technology"
            ),
            "description": "Lead marked Inactive (MSG91 inactive_lead)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_student_leave_applied_template")]
    operations = [migrations.RunPython(forwards, backwards)]
