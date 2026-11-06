"""Seed the `academics.assignment_submitted.email` template row
(get_or_create — never overwrites an admin-edited row)."""

from django.db import migrations

KEY = "academics.assignment_submitted.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": (
                "Assignment submitted: {Assignment_Title} — {Student_Name}"
            ),
            "body_template": (
                "Dear {Faculty_Name},\n\n"
                "This is to inform you that the assigned assessment for "
                "{Subject_Name} has been successfully submitted by the "
                "student.\n\n"
                "  Student Name      : {Student_Name}\n"
                "  Subject           : {Subject_Name}\n"
                "  Assignment Title  : {Assignment_Title}\n"
                "  Submission Status : Successfully Submitted\n\n"
                "Thank you.\n\n"
                "Regards,\n{Student_Name}\nJD Institute of Fashion Technology"
            ),
            "description": "Assignment submitted, to faculty (MSG91 assignment_submitted)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0010_assignment_assigned_template")]
    operations = [migrations.RunPython(forwards, backwards)]
