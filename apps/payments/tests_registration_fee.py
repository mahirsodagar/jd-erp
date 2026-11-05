"""Registration fee paid straight after the application form.

What matters: the step appears for an applicant whose fee template
carries a registration fee and whose gateway is on — every institute
since 2026-11-03, restrictable per environment — and is hidden, not
swapped for a manual page, otherwise. Paying it reserves a
receipt number, mails the receipt, and later settles against the
registration installment at enrolment under that same number. No
network — the Razorpay client is never reached.
"""

from datetime import date
from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admissions.models import Enrollment, Student
from apps.admissions.tests_required_fields import RequiredFixture, complete_payload
from apps.fees.models import FeeReceipt, Installment
from apps.fees.services.receipt_no import generate_receipt_no
from apps.master.models import (
    AcademicYear, Batch, FeeTemplate, Institute, Program, Semester,
)
from apps.payments import razorpay, services
from apps.payments.models import PaymentRequest
from apps.payments.registration_fee import (
    registration_payment_summary, settle_registration_payment_on_enrollment,
)
from apps.payments.tests_razorpay import PAID_UPI, RZP_ON, _link

MAIL = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
    EMAIL_SMTP_BY_DOMAIN={},
    # The office copy of the application acknowledgement (campus inbox)
    # is the mail that carries the fee pay links; the student copy goes
    # via MSG91 without them.
    APPLICATION_ACK_CAMPUS_INBOXES={"BLR": "ack.blr@jdinstitute.edu.in"},
    FEE_RECEIPT_CAMPUS_INBOXES={"BLR": "receipts.blr@jdinstitute.edu.in"},
    OPERATIONS_INBOX="", ACCOUNTS_INBOX="",
)


@override_settings(**RZP_ON, **MAIL)
class RegistrationFeeAtApplicationTests(RequiredFixture):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.year = AcademicYear.objects.get(code="2026-27")
        cls.template = FeeTemplate.objects.create(
            name="DFD 2026", academic_year=cls.year, campus=cls.campus,
            program=cls.program, application_fee=500, course_fee=90000,
            registration_fee=Decimal("10000.00"), total_fee=100000,
        )

    # --- helpers -----------------------------------------------------

    def _submit(self, **over):
        r = self.client.post(self.url, self.payload(**over))
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _student(self) -> Student:
        return Student.objects.get(lead_origin=self.lead)

    def _request(self, student) -> PaymentRequest:
        return PaymentRequest.objects.get(
            student=student, purpose=PaymentRequest.Purpose.REGISTRATION_FEE,
        )

    def _pay(self, pr: PaymentRequest):
        """Settle the request the way the Razorpay webhook / callback
        does, with on_commit hooks (the receipt mail) executed."""
        order = services._new_order(pr)
        body = razorpay.normalise_link(
            _link("paid", ref=order.order_id, payments=PAID_UPI),
        )
        with self.captureOnCommitCallbacks(execute=True):
            services.apply_order_body(order, body)
        pr.refresh_from_db()
        return pr

    def _enroll(self, student) -> Enrollment:
        sem = Semester.objects.create(number=1, name="Sem 1", program=self.program)
        batch = Batch.objects.create(
            name="B1", campus=self.campus, program=self.program,
            academic_year=self.year,
        )
        return Enrollment.objects.create(
            student=student, program=self.program, semester=sem,
            campus=self.campus, batch=batch, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )

    # --- the step appears for JDIFT only, and only when payable ----

    def test_jdift_submit_offers_the_registration_fee_on_razorpay(self):
        data = self._submit()
        rp = data["registration_payment"]
        self.assertEqual(rp["status"], "DUE")
        self.assertEqual(rp["amount"], "10000.00")
        self.assertEqual(rp["gateway"], "razorpay")
        self.assertIn("/api/public/pay/", rp["pay_url"])

        pr = self._request(self._student())
        self.assertEqual((pr.gateway, pr.account), ("razorpay", "JDIFT_ROYALTY"))
        self.assertEqual(pr.amount, Decimal("10000.00"))
        self.assertIn(str(pr.token), rp["pay_url"])

        # The office acknowledgement copy carries the link.
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(rp["pay_url"], mail.outbox[0].body)
        self.assertIn("Registration fee: Rs. 10,000.00", mail.outbox[0].body)

    def _jdsd_submit(self):
        jdsd = Institute.objects.create(name="JDSD", code="JDSD")
        program = Program.objects.create(
            name="B.Des Interior", code="BDES-I", institute=jdsd,
        )
        program.campuses.set([self.campus])
        FeeTemplate.objects.create(
            name="BDES 2026", academic_year=self.year, campus=self.campus,
            program=program, registration_fee=10000, total_fee=100000,
        )
        self.lead.program = program
        self.lead.save(update_fields=["program"])

        r = self.client.post(self.url, complete_payload(
            campus=self.campus, program=program, city=self.city,
        ))
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def test_jdsd_applicants_are_offered_it_on_razorpay_too(self):
        data = self._jdsd_submit()
        rp = data["registration_payment"]
        self.assertEqual((rp["status"], rp["gateway"]), ("DUE", "razorpay"))
        pr = PaymentRequest.objects.get()
        self.assertEqual((pr.gateway, pr.account), ("razorpay", "JDIFT_ROYALTY"))
        self.assertIn("Registration fee", mail.outbox[0].body)

    @override_settings(REGISTRATION_FEE_AT_APPLICATION_INSTITUTES=["JDIFT"])
    def test_the_setting_can_still_restrict_it_to_an_institute(self):
        data = self._jdsd_submit()
        self.assertIsNone(data["registration_payment"])
        self.assertEqual(PaymentRequest.objects.count(), 0)
        self.assertNotIn("Registration fee", mail.outbox[0].body)

    @override_settings(RAZORPAY_ENABLED=False)
    def test_gateway_off_hides_the_step_entirely(self):
        data = self._submit()
        self.assertIsNone(data["registration_payment"])
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_zero_registration_fee_hides_the_step(self):
        self.template.registration_fee = 0
        self.template.save(update_fields=["registration_fee"])
        data = self._submit()
        self.assertIsNone(data["registration_payment"])
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_no_fee_template_hides_the_step(self):
        self.template.delete()
        data = self._submit()
        self.assertIsNone(data["registration_payment"])

    def test_resubmit_reuses_the_open_request(self):
        first = self._submit()["registration_payment"]
        again = self._submit(father_occupation="Doctor")["registration_payment"]
        self.assertEqual(first["pay_url"], again["pay_url"])
        self.assertEqual(PaymentRequest.objects.count(), 1)

    def test_changed_amount_cancels_the_stale_request(self):
        self._submit()
        self.template.registration_fee = Decimal("12000.00")
        self.template.save(update_fields=["registration_fee"])
        data = self._submit(father_occupation="Doctor")
        self.assertEqual(data["registration_payment"]["amount"], "12000.00")
        statuses = sorted(PaymentRequest.objects.values_list("status", flat=True))
        self.assertEqual(statuses, ["CANCELLED", "PENDING"])

    def test_prefill_reports_the_step_without_raising_one(self):
        self._submit()
        PaymentRequest.objects.all().delete()
        prefill = self.client.get(self.url).json()
        self.assertIsNone(prefill["student"]["registration_payment"])
        self.assertEqual(PaymentRequest.objects.count(), 0)

    # --- paying ------------------------------------------------------

    def test_payment_reserves_a_receipt_number_and_mails_the_receipt(self):
        self._submit()
        mail.outbox.clear()
        student = self._student()
        pr = self._pay(self._request(student))

        self.assertEqual(pr.status, PaymentRequest.Status.PAID)
        self.assertEqual(pr.receipt_no, "JDBLR0001-%d" % date.today().year)
        # Nothing to receipt against yet — that waits for enrolment.
        self.assertEqual(FeeReceipt.objects.count(), 0)

        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["asha@example.com"])
        self.assertEqual(m.cc, ["receipts.blr@jdinstitute.edu.in"])
        self.assertIn(pr.receipt_no, m.subject)
        self.assertIn("registration fee", m.body)
        name, content, mimetype = m.attachments[0]
        self.assertEqual(name, f"{pr.receipt_no}.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        # The form and the staff profile both now say paid.
        prefill = self.client.get(self.url).json()
        rp = prefill["student"]["registration_payment"]
        self.assertEqual(rp["status"], "PAID")
        self.assertEqual(rp["receipt_no"], pr.receipt_no)
        self.assertEqual(rp["reference"], "pay_ABC")
        self.assertEqual(rp["pay_url"], "")

    def test_reserved_number_is_skipped_by_the_counter_series(self):
        self._submit()
        pr = self._pay(self._request(self._student()))
        self.assertEqual(
            generate_receipt_no(campus_code="BLR"),
            pr.receipt_no.replace("0001", "0002"),
        )

    def test_enrolment_settles_it_against_the_registration_installment(self):
        self._submit()
        student = self._student()
        pr = self._pay(self._request(student))
        mail.outbox.clear()

        enrollment = self._enroll(student)
        receipt = settle_registration_payment_on_enrollment(enrollment)

        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.receipt_no, pr.receipt_no)
        self.assertEqual(receipt.enrollment, enrollment)
        self.assertEqual(receipt.installment.kind, Installment.Kind.REGISTRATION)
        self.assertEqual(receipt.installment.amount, Decimal("10000.00"))
        self.assertEqual(receipt.amount, Decimal("10000.00"))
        self.assertEqual(receipt.payment_mode, "UPI")
        self.assertEqual(receipt.instrument_ref, pr.paid_order.order_id)
        # The student already holds this receipt — no second mail.
        self.assertEqual(len(mail.outbox), 0)

        # Idempotent: enrolling twice (or a replayed webhook) can't
        # double-post.
        self.assertIsNone(settle_registration_payment_on_enrollment(enrollment))
        self.assertEqual(FeeReceipt.objects.count(), 1)

        # And the portal's balance maths sees the registration row paid.
        from apps.portal.fee_views import _pay_state
        installments, paid_map, next_payable = _pay_state(enrollment)
        reg = next(i for i in installments if i.kind == Installment.Kind.REGISTRATION)
        self.assertEqual(paid_map[reg.id], Decimal("10000.00"))
        self.assertIsNone(next_payable)

    def test_enrolment_endpoint_runs_the_settlement(self):
        self._submit()
        student = self._student()
        self._pay(self._request(student))

        sem = Semester.objects.create(number=1, name="Sem 1", program=self.program)
        batch = Batch.objects.create(
            name="B1", campus=self.campus, program=self.program,
            academic_year=self.year,
        )
        admin = User.objects.create_superuser(
            username="hr", email="hr@example.com", password="x",
        )
        client = APIClient()
        client.force_authenticate(admin)
        r = client.post(reverse("enrollment-list-create"), {
            "student": student.id, "program": self.program.id,
            "semester": sem.id, "campus": self.campus.id,
            "batch": batch.id, "academic_year": self.year.id,
        })
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(FeeReceipt.objects.count(), 1)
        self.assertEqual(
            FeeReceipt.objects.get().installment.kind,
            Installment.Kind.REGISTRATION,
        )

    def test_payment_after_enrolment_receipts_immediately(self):
        self._submit()
        student = self._student()
        pr = self._request(student)
        enrollment = self._enroll(student)
        self._pay(pr)

        receipt = FeeReceipt.objects.get()
        self.assertEqual(receipt.enrollment, enrollment)
        self.assertEqual(receipt.installment.kind, Installment.Kind.REGISTRATION)
        pr.refresh_from_db()
        self.assertEqual(receipt.receipt_no, pr.receipt_no)

    def test_paid_student_is_not_asked_again(self):
        self._submit()
        student = self._student()
        self._pay(self._request(student))
        data = self._submit(father_occupation="Doctor")
        self.assertEqual(data["registration_payment"]["status"], "PAID")
        self.assertEqual(PaymentRequest.objects.count(), 1)

    def test_summary_is_none_for_a_student_with_nothing(self):
        self._submit()
        PaymentRequest.objects.all().delete()
        self.assertIsNone(registration_payment_summary(self._student()))
