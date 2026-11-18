from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0015_student_portal_password"),
    ]

    operations = [
        migrations.AlterField(
            model_name="student",
            name="portal_password",
            field=models.CharField(
                blank=True,
                help_text="Current portal password (shown to staff as-is).",
                max_length=128,
            ),
        ),
    ]
