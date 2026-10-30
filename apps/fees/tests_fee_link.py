"""Staff "Send fee link": the right installment, the right link, and
the static fallback when the fee has no online route."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.fees.models import FeeReceipt, Installment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.models import NotificationTemplate as T
from apps.payments.models import PaymentRequest
from apps.portal.tests_fees import SG_ON

STATIC = {"JDIFT": "https://short.test/jdift", "JDSD": "https://short.test/jdsd"}


@override_settings(
    **SG_ON, FEE_LINK_URLS=STATIC,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class SendFeeLinkTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        T.objects.create(
            key="fees.fee_link.email", channel="EMAIL",
            subject_template="{institute} — Fee payment link",
            body_template="Dear {name}, pay {amount}: {url}",
        )
        cls.jdsd = Institute.objects.create(name="JD School of Design", code="JDSD")
        cls.jdift = Institute.objects.create(name="JD Institute of Fashion Technology", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="BLR")
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(number=1, name="Sem 1")
        cls.staff = get_user_model().objects.create_superuser(
            username="accounts", email="acc@example.com", password="x",
        )

    def _enroll(self, institute, email="asha@example.com"):
        program = Program.objects.create(
            name=f"P-{institute.code}", code=f"P{institute.code}", institute=institute,
        )
        batch = Batch.objects.create(
            name=f"B-{institute.code}", campus=self.campus, program=program,
            academic_year=self.year,
        )
        student = Student.objects.create(
            student_name="Asha Rao", gender="F", dob=date(2006, 1, 1),
            nationality="INDIAN", institute=institute, campus=self.campus,
            program=program, academic_year=self.year,
            student_mobile="9000000000", student_email=email,
        )
        enrollment = Enrollment.objects.create(
            student=student, program=program, semester=self.sem,
            campus=self.campus, batch=batch, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )
        i1 = Installment.objects.create(
            enrollment=enrollment, sequence=1, due_date=date(2026, 7, 1),
            amount=Decimal("50000"),
        )
        i2 = Installment.objects.create(
            enrollment=enrollment, sequence=2, due_date=date(2026, 12, 1),
            amount=Decimal("50000"),
        )
        return enrollment, i1, i2

    def _send(self, enrollment):
        client = APIClient()
        client.force_authenticate(user=self.staff)
        return client.post(reverse("enrollment-send-fee-link", args=[enrollment.id]))

    def test_sends_gateway_link_for_outstanding_part_of_next_installment(self):
        enrollment, i1, _ = self._enroll(self.jdsd)
        FeeReceipt.objects.create(
            receipt_no="R-1", enrollment=enrollment, installment=i1,
            basic_fee=Decimal("20000"), amount=Decimal("20000"),
            payment_mode=FeeReceipt.PaymentMode.CASH, received_date=date(2026, 7, 1),
        )
        r = self._send(enrollment)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["email_sent"], body)
        self.assertEqual(body["installment_id"], i1.id)
        self.assertEqual(Decimal(body["amount"]), Decimal("30000"))
        self.assertEqual(body["gateway"], "smartgateway")

        pr = PaymentRequest.objects.get(pk=body["payment_request_id"])
        self.assertEqual(pr.installment_id, i1.id)
        self.assertIn(str(pr.token), body["url"])

        log = NotificationDispatchLog.objects.get(template_key="fees.fee_link.email")
        self.assertEqual(log.recipient, "asha@example.com")
        self.assertIn(body["url"], log.body)

    def test_resend_reuses_the_same_pay_link(self):
        enrollment, *_ = self._enroll(self.jdsd)
        first = self._send(enrollment).json()["url"]
        self.assertEqual(self._send(enrollment).json()["url"], first)

    def test_no_online_route_falls_back_to_static_link(self):
        enrollment, *_ = self._enroll(self.jdift)  # JDIFT course installment
        body = self._send(enrollment).json()
        self.assertEqual(body["gateway"], "manual")
        self.assertEqual(body["url"], STATIC["JDIFT"])
        self.assertFalse(PaymentRequest.objects.exists())

    def test_everything_paid_is_rejected(self):
        enrollment, i1, i2 = self._enroll(self.jdsd)
        for n, inst in enumerate((i1, i2)):
            FeeReceipt.objects.create(
                receipt_no=f"R-{n}", enrollment=enrollment, installment=inst,
                basic_fee=inst.amount, amount=inst.amount,
                payment_mode=FeeReceipt.PaymentMode.CASH,
                received_date=date(2026, 7, 1),
            )
        r = self._send(enrollment)
        self.assertEqual(r.status_code, 400)
        self.assertIn("already paid", r.json()["detail"])

    def test_requires_permission(self):
        enrollment, *_ = self._enroll(self.jdsd)
        clerk = get_user_model().objects.create_user(
            username="clerk", email="clerk@example.com", password="x",
        )
        client = APIClient()
        client.force_authenticate(user=clerk)
        r = client.post(reverse("enrollment-send-fee-link", args=[enrollment.id]))
        self.assertEqual(r.status_code, 403)
