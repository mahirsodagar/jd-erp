"""Plain-text copy of every user's current password, shown on Admin ->
Users to holders of `accounts.user.reset_password`.

Client decision 2026-11-24 (same stance as `Student.portal_password`).
Existing users stay blank until their next reset or change: hashes
cannot be read back.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_is_available_user_unavailable_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="visible_password",
            field=models.CharField(
                blank=True, max_length=128,
                help_text="Plain-text copy of the current password, kept so "
                          "Admin -> Users can show it (client decision "
                          "2026-11-24). Written by every path that sets a "
                          "password; blank until the first reset after "
                          "this field was added.",
            ),
        ),
    ]
