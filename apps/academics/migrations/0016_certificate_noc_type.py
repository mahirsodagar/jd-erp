from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0015_assignment_campus"),
    ]

    operations = [
        migrations.AlterField(
            model_name="certificate",
            name="type",
            field=models.CharField(
                choices=[
                    ("COMPLETION", "Course Completion"),
                    ("PROVISIONAL", "Provisional"),
                    ("BONAFIDE", "Bonafide"),
                    ("TRANSFER", "Transfer"),
                    ("CHARACTER", "Character"),
                    ("NO_DUES", "No Dues"),
                    ("NOC", "No Objection Certificate"),
                ],
                max_length=20,
            ),
        ),
    ]
