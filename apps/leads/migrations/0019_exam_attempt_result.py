"""Entrance exam grading (client, 2026-11-26): staff decide Pass / Fail
on the grading page after entering every mark; the result (and who
decided it, when) is stored on the attempt."""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0018_exam_pass_marks_result_mail"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="entranceexamattempt",
            name="result",
            field=models.CharField(
                blank=True, choices=[("PASS", "Pass"), ("FAIL", "Fail")],
                default="", max_length=4,
            ),
        ),
        migrations.AddField(
            model_name="entranceexamattempt",
            name="result_decided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="entranceexamattempt",
            name="result_decided_by",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="exam_results_decided",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="entranceexamattempt",
            name="result_mailed_at",
            field=models.DateTimeField(
                blank=True, null=True,
                help_text="When the Entrance Exam Result mail (pass or fail) went out (once).",
            ),
        ),
    ]
