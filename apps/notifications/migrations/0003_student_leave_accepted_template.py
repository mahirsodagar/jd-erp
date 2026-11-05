"""Seed the `student_leaves.accepted.email` template row so the trigger
works on deploy without a manual `seed_notification_templates` run.
get_or_create — never overwrites an admin-edited row."""

from django.db import migrations

KEY = "student_leaves.accepted.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "Leave Application Accepted",
            "body_template": (
                "Hi {Student_Name},\n\n"
                "Your leave application has been accepted.\n\n"
                "  Leave Start Date : {Leave_Start_Date}\n"
                "  Leave End Date   : {Leave_End_Date}\n"
                "  Leave Count      : {Leave_Count}\n"
                "  Reason           : {Reason}\n\n"
                "Regards,\nJDSD / JDINST\n\n"
                "Note: This is an auto-generated email. "
                "Please do not reply to this email."
            ),
            "description": "Student leave approved (MSG91 student_leave_accepted)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0002_inapp_notification")]
    operations = [migrations.RunPython(forwards, backwards)]
