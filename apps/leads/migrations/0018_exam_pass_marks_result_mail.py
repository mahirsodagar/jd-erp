from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0017_counsellor_rotation_per_campus"),
    ]

    operations = [
        migrations.AddField(
            model_name="entranceexam",
            name="pass_marks",
            field=models.DecimalField(
                blank=True, decimal_places=1, max_digits=5, null=True,
                help_text="Minimum total_score that clears the exam. The result "
                          "mail goes only to candidates at or above it; blank "
                          "means every graded candidate gets it.",
            ),
        ),
        migrations.AddField(
            model_name="entranceexamattempt",
            name="result_mailed_at",
            field=models.DateTimeField(
                blank=True, null=True,
                help_text="When the Entrance Exam Result mail went out (once).",
            ),
        ),
    ]
