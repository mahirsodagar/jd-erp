from decimal import Decimal

from django.db import migrations, models


def zero_existing_templates(apps, schema_editor):
    """Registration fee applies FORWARD only.

    Every template that already exists has live enrollments whose
    installment schedules sum to `total_fee` with no registration line —
    and in many cases a signed fee undertaking to match. Defaulting those
    to 10,000 would carve a slice out of schedules students have already
    agreed to. So existing rows get 0; the model default of 10,000
    pre-fills new templates, and admins turn it on per academic year.
    """
    apps.get_model("master", "FeeTemplate").objects.update(
        registration_fee=Decimal("0.00"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("master", "0011_campus_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="feetemplate",
            name="registration_fee",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("10000.00"), max_digits=10,
                help_text="Mandatory yearly registration charge, CARVED OUT "
                          "of total_fee (not added on top) — it is part of "
                          "the course fee, scheduled as its own installment "
                          "and payable in full every academic year. "
                          "Concessions cannot reduce it. Set to 0 to disable "
                          "for this template.",
            ),
        ),
        migrations.RunPython(zero_existing_templates, migrations.RunPython.noop),
    ]
