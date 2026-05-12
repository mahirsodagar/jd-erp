from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("master", "0008_remove_feetemplate_course_remove_subject_courses_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Course",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("code", models.CharField(max_length=30, unique=True)),
                ("duration_months", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "program",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="courses",
                        to="master.program",
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
                "unique_together": {("name", "program")},
            },
        ),
        migrations.AddField(
            model_name="feetemplate",
            name="course",
            field=models.ForeignKey(
                blank=True, null=True,
                help_text="Optional — leave blank for program-wide fee.",
                on_delete=models.deletion.PROTECT,
                related_name="fee_templates",
                to="master.course",
            ),
        ),
    ]
