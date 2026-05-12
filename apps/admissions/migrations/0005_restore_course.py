from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0004_remove_enrollment_course_remove_student_course"),
        ("master", "0009_restore_course"),
    ]

    operations = [
        migrations.AddField(
            model_name="student",
            name="course",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.PROTECT,
                related_name="students",
                to="master.course",
            ),
        ),
        migrations.AddField(
            model_name="enrollment",
            name="course",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.PROTECT,
                related_name="enrollments",
                to="master.course",
            ),
        ),
    ]
