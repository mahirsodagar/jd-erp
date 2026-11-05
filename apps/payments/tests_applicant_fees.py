"""The "Pay fees" page after the application form (every institute).

What matters: every applicant sees the whole fee structure; only the
rows the route table names a gateway for get a pay button — the
registration fee for all (Razorpay, Royalty), the course and other fee
for JDSD only (SmartGateway, Trust). A course fee paid before enrolment
is applied to the COURSE installments in order once the schedule is laid
down; an other fee becomes an OtherFee row with its receipt. No network.
"""

from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.admissions.models import Enrollment, Student
from apps.admissions.tests_required_fields import RequiredFixture, complete_payload
from apps.fees.models import FeeReceipt, Installment, OtherFee
from apps.master.models import (
    AcademicYear, Batch, Course, FeeTemplate, Institute, Program, Semester,
)
from apps.payments import services
from apps.payments.applicant_fees import (
    COURSE, OTHER, REGISTRATION, fee_amounts, fee_page_for,
    settle_applicant_payments_on_enrollment,
)
from apps.payments.models import PaymentRequest
from apps.payments.tests_razorpay import RZP_ON
from apps.payments.tests_registration_fee import MAIL
from apps.payments.tests_smartgateway import SG_ON, _order_body

#: Both gateways on — Razorpay for the registration row, SmartGateway for
#: the JDSD course/other rows.
BOTH_ON = {**SG_ON, **RZP_ON, "SMARTGATEWAY_ENABLED": True}


def _rows(page):
    return {r["kind"]: r for r in page["rows"]}


@override_settings(**BOTH_ON, **MAIL)
class ApplicantFeePageTests(RequiredFixture):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.year = AcademicYear.objects.get(code="2026-27")
        cls.jdsd = Institute.objects.create(name="JDSD", code="JDSD")
        cls.jdsd_program = Program.objects.create(
            name="M.Sc Interior Design", code="MSC-ID", institute=cls.jdsd,
        )
        cls.jdsd_program.campuses.set([cls.campus])
        # JDIFT: the fixture's program.
        FeeTemplate.objects.create(
            name="BDES-F 2026", academic_year=cls.year, campus=cls.campus,
            program=cls.program, application_fee=500, course_fee=100000,
            registration_fee=Decimal("10000.00"), other_fee=5000,
            total_fee=105000,
        )
        cls.jdsd_template = FeeTemplate.objects.create(
            name="MSC ID 2026", academic_year=cls.year, campus=cls.campus,
            program=cls.jdsd_program, application_fee=1000, course_fee=130000,
            registration_fee=Decimal("30000.00"), other_fee=8000,
            total_fee=138000,
        )

    # --- helpers -----------------------------------------------------

    def _submit(self, program=None, **over):
        program = program or self.program
        if self.lead.program_id != program.id:
            self.lead.program = program
            self.lead.save(update_fields=["program"])
        r = self.client.post(self.url, complete_payload(
            campus=self.campus, program=program, city=self.city, **over,
        ))
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()

    def _student(self) -> Student:
        return Student.objects.get(lead_origin=self.lead)

    def _request(self, student, kind) -> PaymentRequest:
        return PaymentRequest.objects.get(student=student, purpose=kind.purpose)

    def _pay_smartgateway(self, pr: PaymentRequest):
        order = services._new_order(pr)
        with self.captureOnCommitCallbacks(execute=True):
            services.apply_order_body(order, _order_body(order_id=order.order_id))
        pr.refresh_from_db()
        return pr

    def _enroll(self, student, program) -> Enrollment:
        sem = Semester.objects.create(number=1, name="Sem 1", program=program)
        batch = Batch.objects.create(
            name="B1", campus=self.campus, program=program, academic_year=self.year,
        )
        return Enrollment.objects.create(
            student=student, program=program, semester=sem,
            campus=self.campus, batch=batch, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )

    def _schedule(self, enrollment, *amounts):
        for i, amount in enumerate(amounts, start=1):
            Installment.objects.create(
                enrollment=enrollment, kind=Installment.Kind.COURSE,
                sequence=i, due_date="2026-06-01", amount=Decimal(amount),
            )

    # --- what each institute sees ------------------------------------

    def test_amounts_carve_the_registration_fee_out_of_the_course_fee(self):
        amounts = fee_amounts(self.jdsd_template)
        self.assertEqual(amounts[REGISTRATION], Decimal("30000.00"))
        self.assertEqual(amounts[COURSE], Decimal("100000.00"))
        self.assertEqual(amounts[OTHER], Decimal("8000.00"))

    def test_jdift_sees_the_structure_with_only_the_registration_fee_payable(self):
        data = self._submit()
        page = data["fee_page"]
        self.assertEqual(page["institute"], "JDIFT")
        self.assertEqual(page["total_fee"], "105000.00")
        rows = _rows(page)
        self.assertEqual(
            [r["kind"] for r in page["rows"]],
            ["APPLICATION_FEE", "REGISTRATION_FEE", "COURSE_FEE", "OTHER_FEE_APPLICANT"],
        )
        self.assertEqual(rows["APPLICATION_FEE"]["status"], "OFFLINE")
        self.assertEqual(rows["REGISTRATION_FEE"]["status"], "DUE")
        self.assertEqual(rows["REGISTRATION_FEE"]["gateway"], "razorpay")
        self.assertEqual(rows["COURSE_FEE"]["status"], "OFFLINE")
        self.assertEqual(rows["COURSE_FEE"]["amount"], "90000.00")
        self.assertEqual(rows["OTHER_FEE_APPLICANT"]["status"], "OFFLINE")
        # Only the registration request was raised.
        self.assertEqual(
            list(PaymentRequest.objects.values_list("purpose", flat=True)),
            ["REGISTRATION_FEE"],
        )
        # The older field still carries the registration row.
        self.assertEqual(data["registration_payment"]["status"], "DUE")

    def test_jdsd_sees_every_row_payable_on_its_own_gateway(self):
        data = self._submit(program=self.jdsd_program)
        rows = _rows(data["fee_page"])
        self.assertEqual(data["fee_page"]["institute"], "JDSD")

        reg = rows["REGISTRATION_FEE"]
        self.assertEqual((reg["status"], reg["gateway"], reg["amount"]),
                         ("DUE", "razorpay", "30000.00"))
        course = rows["COURSE_FEE"]
        self.assertEqual((course["status"], course["gateway"], course["amount"]),
                         ("DUE", "smartgateway", "100000.00"))
        other = rows["OTHER_FEE_APPLICANT"]
        self.assertEqual((other["status"], other["gateway"], other["amount"]),
                         ("DUE", "smartgateway", "8000.00"))
        for row in (reg, course, other):
            self.assertIn("/api/public/pay/", row["pay_url"])

        student = self._student()
        self.assertEqual(
            (self._request(student, REGISTRATION).gateway,
             self._request(student, REGISTRATION).account),
            ("razorpay", "JDIFT_ROYALTY"),
        )
        self.assertEqual(
            (self._request(student, COURSE).gateway, self._request(student, COURSE).account),
            ("smartgateway", "JDSD_TRUST"),
        )
        self.assertEqual(self._request(student, OTHER).account, "JDSD_TRUST")

        # The office acknowledgement copy carries every link.
        body = mail.outbox[0].body
        self.assertIn("Registration fee: Rs. 30,000.00", body)
        self.assertIn("Course fee: Rs. 100,000.00", body)
        self.assertIn("Other fees: Rs. 8,000.00", body)

    def test_application_fee_row_shows_as_paid_with_its_receipt(self):
        from django.utils import timezone
        self.lead.application_fee_paid_at = timezone.now()
        self.lead.application_fee_amount = Decimal("1000.00")
        self.lead.application_fee_ref = "UPI123"
        self.lead.application_fee_receipt_no = "JDBLR0001-2026"
        self.lead.save()
        data = self._submit(program=self.jdsd_program)
        row = _rows(data["fee_page"])["APPLICATION_FEE"]
        self.assertEqual(row["status"], "PAID")
        self.assertEqual(row["amount"], "1000.00")
        self.assertEqual(row["receipt_no"], "JDBLR0001-2026")
        self.assertEqual(row["reference"], "UPI123")

    @override_settings(SMARTGATEWAY_ENABLED=False)
    def test_smartgateway_off_leaves_jdsd_course_row_without_a_button(self):
        data = self._submit(program=self.jdsd_program)
        rows = _rows(data["fee_page"])
        self.assertEqual(rows["REGISTRATION_FEE"]["status"], "DUE")
        self.assertEqual(rows["COURSE_FEE"]["status"], "OFFLINE")
        self.assertEqual(rows["COURSE_FEE"]["pay_url"], "")

    def test_template_with_a_program_year_still_counts(self):
        course = Course.objects.create(
            name="Year 1", code="MSC-ID-Y1", program=self.jdsd_program,
        )
        self.jdsd_template.course = course
        self.jdsd_template.save(update_fields=["course"])
        data = self._submit(program=self.jdsd_program)
        self.assertEqual(_rows(data["fee_page"])["REGISTRATION_FEE"]["amount"], "30000.00")
        # The pre-submit fee panel publishes it too.
        prefill = self.client.get(self.url).json()
        panel = next(
            f for f in prefill["fee_structures"]
            if f["program"] == self.jdsd_program.id
        )
        self.assertEqual(panel["registration_fee"], "30000.00")

    def test_prefill_reports_the_page_without_raising_requests(self):
        self._submit(program=self.jdsd_program)
        PaymentRequest.objects.all().delete()
        prefill = self.client.get(self.url).json()
        rows = _rows(prefill["student"]["fee_page"])
        self.assertEqual(rows["COURSE_FEE"]["status"], "OFFLINE")
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_nothing_to_show_without_a_template(self):
        FeeTemplate.objects.all().delete()
        data = self._submit()
        self.assertIsNone(data["fee_page"])
        self.assertIsNone(data["registration_payment"])

    # --- paying and settling -----------------------------------------

    def test_course_fee_payment_reserves_a_number_and_mails_the_receipt(self):
        self._submit(program=self.jdsd_program)
        mail.outbox.clear()
        student = self._student()
        pr = self._pay_smartgateway(self._request(student, COURSE))

        self.assertEqual(pr.status, PaymentRequest.Status.PAID)
        self.assertTrue(pr.receipt_no.startswith("JDBLR"))
        self.assertEqual(FeeReceipt.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("course fee", mail.outbox[0].body)
        self.assertIn(pr.receipt_no, mail.outbox[0].subject)

        page = fee_page_for(student)
        self.assertEqual(_rows(page)["COURSE_FEE"]["status"], "PAID")
        self.assertEqual(_rows(page)["COURSE_FEE"]["receipt_no"], pr.receipt_no)

    def test_course_fee_is_applied_to_installments_in_order_at_enrolment(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        pr = self._pay_smartgateway(self._request(student, COURSE))   # 100,000
        enrollment = self._enroll(student, self.jdsd_program)

        # Enrolment alone has no schedule to apply it to.
        self.assertEqual(settle_applicant_payments_on_enrollment(enrollment), [])

        self._schedule(enrollment, "40000", "40000", "50000")
        receipts = settle_applicant_payments_on_enrollment(enrollment)
        self.assertEqual(
            [(r.installment.sequence, r.amount) for r in receipts],
            [(1, Decimal("40000")), (2, Decimal("40000")), (3, Decimal("20000"))],
        )
        self.assertEqual(receipts[0].receipt_no, pr.receipt_no)
        self.assertEqual(len({r.receipt_no for r in receipts}), 3)
        self.assertTrue(all(r.instrument_ref == pr.paid_order.order_id for r in receipts))

        # Idempotent.
        self.assertEqual(settle_applicant_payments_on_enrollment(enrollment), [])
        self.assertEqual(FeeReceipt.objects.count(), 3)

        from apps.fees.services.balance import enrollment_balance
        self.assertEqual(
            Decimal(enrollment_balance(enrollment)["paid_total"]), Decimal("100000"),
        )

    def test_course_fee_beyond_the_schedule_lands_on_the_last_installment(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        self._pay_smartgateway(self._request(student, COURSE))   # 100,000
        enrollment = self._enroll(student, self.jdsd_program)
        self._schedule(enrollment, "30000", "30000")
        receipts = settle_applicant_payments_on_enrollment(enrollment)
        self.assertEqual(
            [(r.installment.sequence, r.amount) for r in receipts],
            [(1, Decimal("30000")), (2, Decimal("70000"))],
        )

    def test_installment_bulk_create_settles_the_course_fee(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        self._pay_smartgateway(self._request(student, COURSE))
        enrollment = self._enroll(student, self.jdsd_program)

        admin = User.objects.create_superuser(
            username="hr", email="hr@example.com", password="x",
        )
        client = APIClient()
        client.force_authenticate(admin)
        r = client.post(reverse("installment-bulk-create"), {
            "enrollment": enrollment.id,
            "items": [
                {"sequence": 1, "due_date": "2026-06-01", "amount": "60000"},
                {"sequence": 2, "due_date": "2026-12-01", "amount": "40000"},
            ],
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(
            sorted(FeeReceipt.objects.values_list("installment__sequence", "amount")),
            [(1, Decimal("60000")), (2, Decimal("40000"))],
        )

    def test_other_fee_becomes_an_other_fee_row_with_its_receipt(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        pr = self._pay_smartgateway(self._request(student, OTHER))   # 8,000
        enrollment = self._enroll(student, self.jdsd_program)
        receipts = settle_applicant_payments_on_enrollment(enrollment)

        self.assertEqual(len(receipts), 1)
        other = OtherFee.objects.get()
        self.assertEqual(other.amount, Decimal("8000.00"))
        self.assertEqual(receipts[0].other_fee, other)
        self.assertEqual(receipts[0].receipt_no, pr.receipt_no)
        # Second run adds nothing.
        self.assertEqual(settle_applicant_payments_on_enrollment(enrollment), [])
        self.assertEqual(OtherFee.objects.count(), 1)

    def test_payment_after_enrolment_with_a_schedule_receipts_immediately(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        enrollment = self._enroll(student, self.jdsd_program)
        self._schedule(enrollment, "100000")
        self._pay_smartgateway(self._request(student, COURSE))
        receipt = FeeReceipt.objects.get()
        self.assertEqual(receipt.installment.sequence, 1)
        self.assertEqual(receipt.amount, Decimal("100000.00"))

    def test_staff_profile_carries_the_page(self):
        self._submit(program=self.jdsd_program)
        student = self._student()
        self._pay_smartgateway(self._request(student, OTHER))
        admin = User.objects.create_superuser(
            username="hr2", email="hr2@example.com", password="x",
        )
        client = APIClient()
        client.force_authenticate(admin)
        r = client.get(f"/api/admissions/students/{student.id}/")
        self.assertEqual(r.status_code, 200, r.content)
        rows = _rows(r.json()["applicant_fees"])
        self.assertEqual(rows["OTHER_FEE_APPLICANT"]["status"], "PAID")
        self.assertEqual(rows["COURSE_FEE"]["status"], "DUE")
