"""Seed the two credential-mail template rows that previously existed only
via `seed_notification_templates`, so a fresh DB (or a prod that never
ran the seeder) can send them. get_or_create — existing rows untouched.

  account.password_reset_by_admin.email → MSG91 password_reset_by_admin
  student.portal_credentials.email      → MSG91 student_portal_credentials
"""

from django.db import migrations

ROWS = {
    "account.password_reset_by_admin.email": (
        "Your JD ERP password has been reset",
        "Hi {name},\n\n"
        "An administrator has reset your JD ERP password.\n\n"
        "You can log in using the credentials below:\n\n"
        "  Username : {username}\n"
        "  Password : {password}\n\n"
        "Please change your password after logging in.\n\n"
        "Sign in at: {login_url}\n\n"
        "If you didn't expect this, contact the admin team.\n\n"
        "— JD Admin",
    ),
    "student.portal_credentials.email": (
        "Your student portal login",
        "Hi {name},\n\n"
        "Welcome to {institute}. Your student portal account is ready.\n\n"
        "You can log in using the credentials below:\n\n"
        "  Login email : {email}\n"
        "  Username    : {username}\n"
        "  Password    : {password}\n\n"
        "Please change your password after the first login.\n\n"
        "Sign in at: {login_url}\n\n"
        "If you didn't request this, contact your admissions office.\n\n"
        "— JD Admissions",
    ),
}


def forwards(apps, schema_editor):
    T = apps.get_model("notifications", "NotificationTemplate")
    for key, (subject, body) in ROWS.items():
        T.objects.get_or_create(key=key, defaults={
            "channel": "EMAIL", "subject_template": subject,
            "body_template": body,
        })


class Migration(migrations.Migration):
    dependencies = [("notifications", "0011_assignment_submitted_template")]
    # No-op reverse: these rows may predate this migration (seeder).
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
