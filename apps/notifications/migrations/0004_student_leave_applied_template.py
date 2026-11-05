"""Seed the `student_leaves.applied.email` template row (get_or_create —
never overwrites an admin-edited row)."""

from django.db import migrations

KEY = "student_leaves.applied.email"


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    T.objects.get_or_create(
        key=KEY,
        defaults={
            "channel": "EMAIL",
            "subject_template": "Student Leave Application Submitted",
            "body_template": (
                "Student Leave Application Submitted\n\n"
                "A new leave application has been recorded with the "
                "following details:\n\n"
                "  Student Name     : {Student_Name}\n"
                "  Leave Start Date : {Leave_Start_Date}\n"
                "  Leave End Date   : {Leave_End_Date}\n"
                "  Total Leave Days : {Leave_Count}\n"
                "  Reason           : {Reason}\n\n"
                "Regards,\nJDSD / JDINST\n\n"
                "Note: This is an auto-generated email. "
                "Please do not reply to this email."
            ),
            "description": "Student leave submitted (MSG91 student_leave_application_)",
        },
    )


def backwards(apps, schema_editor):
    apps.get_model("notifications", "NotificationTemplate").objects.filter(
        key=KEY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_student_leave_accepted_template")]
    operations = [migrations.RunPython(forwards, backwards)]
