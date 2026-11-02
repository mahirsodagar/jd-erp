from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0014_batch_transfer"),
        ("payments", "0004_razorpay_statuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentrequest",
            name="student",
            field=models.ForeignKey(
                blank=True,
                help_text="Set for REGISTRATION_FEE requests — raised the moment the application form is submitted, before the student has an enrollment to hang an installment off.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="payment_requests",
                to="admissions.student",
            ),
        ),
        migrations.AddField(
            model_name="paymentrequest",
            name="receipt_no",
            field=models.CharField(blank=True, db_index=True, max_length=40),
        ),
        migrations.AlterField(
            model_name="paymentrequest",
            name="purpose",
            field=models.CharField(
                choices=[
                    ("APPLICATION_FEE", "Application fee (lead)"),
                    ("FEE_INSTALLMENT", "Fee installment (student)"),
                    ("REGISTRATION_FEE", "Registration fee (applicant)"),
                ],
                db_index=True,
                default="APPLICATION_FEE",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="paymentrequest",
            index=models.Index(
                fields=["student", "status"],
                name="payments_pa_student_2e09d0_idx",
            ),
        ),
    ]
