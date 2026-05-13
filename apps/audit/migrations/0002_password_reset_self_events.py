from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="authlog",
            name="event",
            field=models.CharField(
                choices=[
                    ("login_success", "Login success"),
                    ("login_failure", "Login failure"),
                    ("logout", "Logout"),
                    ("password_change", "Password change (self)"),
                    ("password_reset", "Password reset (admin)"),
                    ("password_reset_requested", "Password reset requested (self)"),
                    ("password_reset_completed", "Password reset completed (self)"),
                    ("role_create", "Role created"),
                    ("role_update", "Role updated"),
                    ("role_delete", "Role deleted"),
                    ("lockout", "Account locked out"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
