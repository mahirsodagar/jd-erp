"""Seed the `academics.assignment_assigned.email` template row
(get_or_create — never overwrites an admin-edited row)."""

from django.db import migrations

KEY = "academics.assignment_assigned.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "New Assignment: {VAR3}",
            "body_template": (
                "Dear {VAR1},\n\n"
                "This is to inform you that a new assignment has been "
                "assigned to you.\n\n"
                "Subject: {VAR2}\n\n"
                "Assignment Details:\n"
                "  Assignment Title    : {VAR3}\n"
                "  Submission Deadline : {VAR4}\n"
                "  Submission Mode     : {VAR5}\n\n"
                "Instructions:\n"
                "Please ensure that you complete and submit the assignment "
                "on or before the specified deadline. Late submissions may "
                "not be accepted.\n\n"
                "For any queries or assistance, please contact your "
                "respective faculty.\n\n"
                "Thanks & Regards,\nJD Institute of Fashion Technology"
            ),
            "description": "New assignment to student (MSG91 assignmentassigned)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0009_application_submitted_template")]
    operations = [migrations.RunPython(forwards, backwards)]
