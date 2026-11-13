import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0016_website_webhook'),
        ('master', '0024_institute_handbook_pdf'),
    ]

    operations = [
        migrations.AddField(
            model_name='counsellorrotation',
            name='campus',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='counsellor_rotation', to='master.campus'),
        ),
    ]
