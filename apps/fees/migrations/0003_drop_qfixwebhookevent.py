from django.db import migrations


class Migration(migrations.Migration):
    """Reverse 0002 — Qfix integration removed in favour of UPI/QR/bank
    fee instructions emailed from `apps.leads.send_links.send_fee_link`."""

    dependencies = [
        ("fees", "0002_qfixwebhookevent"),
    ]

    operations = [
        migrations.DeleteModel(name="QfixWebhookEvent"),
    ]
