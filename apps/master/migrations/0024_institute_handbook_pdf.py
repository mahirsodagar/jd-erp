from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('master', '0023_program_id_card_affiliation'),
    ]

    operations = [
        migrations.AddField(
            model_name='institute',
            name='handbook_pdf',
            field=models.FileField(blank=True, help_text="Student handbook PDF emailed to every student after enrolment via 'Send handbook'.", null=True, upload_to='institute/handbooks/'),
        ),
    ]
