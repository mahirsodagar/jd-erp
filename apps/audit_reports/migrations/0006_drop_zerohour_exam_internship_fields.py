from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('audit_reports', '0005_zerohourreport'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='zerohourreport',
            name='months_to_exams',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='exam_preparations',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='exam_preparation_details',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='months_to_portfolios',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='months_to_internships',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='internship_preparations',
        ),
        migrations.RemoveField(
            model_name='zerohourreport',
            name='months_to_passout',
        ),
    ]
