"""Per-centre address and phones printed on student and staff ID cards.

Client, 2026-11-24: every centre's card was printing the Bengaluru head
office address. Blank values keep printing that block, so existing cards
are unchanged until HR fills the centre in.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("master", "0028_timeslot_drop_academic_year"),
    ]

    operations = [
        migrations.AddField(
            model_name="campus",
            name="address",
            field=models.TextField(
                blank=True,
                help_text="Centre address as printed on ID cards, one line per "
                          "row (2-3 short lines). Blank prints the head-office "
                          "address.",
            ),
        ),
        migrations.AddField(
            model_name="campus",
            name="phone",
            field=models.CharField(
                blank=True, max_length=40,
                help_text="Centre contact number printed on ID cards.",
            ),
        ),
        migrations.AddField(
            model_name="campus",
            name="phone_alt",
            field=models.CharField(
                blank=True, max_length=40,
                help_text="Second contact number (staff cards print both).",
            ),
        ),
    ]
