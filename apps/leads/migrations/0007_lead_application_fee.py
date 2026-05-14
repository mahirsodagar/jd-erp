from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0006_lead_application_locked_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="application_fee_paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_fee_amount",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_fee_mode",
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_fee_ref",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_fee_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="application_fee_recorded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="application_fees_recorded",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
