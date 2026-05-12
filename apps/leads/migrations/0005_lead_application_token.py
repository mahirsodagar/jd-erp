from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0004_leadfollowup_outcome_category_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="application_token",
            field=models.UUIDField(
                blank=True, db_index=True, null=True, unique=True,
                help_text="One-shot token used by the public application form.",
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_token_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
