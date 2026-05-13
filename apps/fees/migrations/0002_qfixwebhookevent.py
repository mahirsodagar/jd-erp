from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="QfixWebhookEvent",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transaction_id", models.CharField(max_length=120, unique=True)),
                ("raw_payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("RECEIVED", "Received"),
                            ("PROCESSED", "Processed (receipt created)"),
                            ("SKIPPED", "Skipped (not a success event)"),
                            ("ERROR", "Error"),
                        ],
                        default="RECEIVED",
                        max_length=12,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "receipt",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name="qfix_events",
                        to="fees.feereceipt",
                    ),
                ),
            ],
            options={"ordering": ("-received_at",)},
        ),
    ]
