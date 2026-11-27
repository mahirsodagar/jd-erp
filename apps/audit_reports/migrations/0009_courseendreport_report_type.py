"""Module End Report gets a Type: Mid Module / End Module / Emergency Stop
(client, 2026-11-27). Existing rows default to End Module, and the
one-report-per-(instructor, subject, batch) rule becomes per type too so a
mid-module report does not block the end-module one.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("audit_reports", "0008_dailyreportaccess"),
    ]

    operations = [
        migrations.AddField(
            model_name="courseendreport",
            name="report_type",
            field=models.CharField(
                choices=[
                    ("MID_MODULE", "Mid Module"),
                    ("END_MODULE", "End Module"),
                    ("EMERGENCY_STOP", "Emergency Stop"),
                ],
                default="END_MODULE",
                max_length=20,
            ),
        ),
        migrations.AlterUniqueTogether(
            name="courseendreport",
            unique_together={("instructor", "subject", "batch", "report_type")},
        ),
    ]
