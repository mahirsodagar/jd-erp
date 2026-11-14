from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admissions', '0014_batch_transfer'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='portal_password',
            field=models.CharField(
                blank=True, max_length=64,
                help_text='Current portal password (shown to staff as-is).',
            ),
        ),
    ]
