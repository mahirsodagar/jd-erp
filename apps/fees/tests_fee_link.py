"""Staff "Send fee link": the right installment, the right link, and
the manual-payment page fallback when the fee has no online route."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.fees.models import FeeReceipt, Installment, OtherFee
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)
from apps.notifications.models import NotificationDispatchLog
from apps.notifications.models import NotificationTemplate as T
from apps.payments.models import PaymentOrder, PaymentRequest
from apps.portal.tests_fees import SG_ON

@override_settings(
    **SG_ON,
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

    def test_no_online_route_falls_back_to_manual_page(self):
        enrollment, *_ = self._enroll(self.jdift)  # JDIFT course installment
        body = self._send(enrollment).json()
        self.assertEqual(body["gateway"], "manual")
        self.assertTrue(
            body["url"].startswith("https://api.jd.test/api/public/pay/manual/JDIFT/"),
            body["url"],
        )
        self.assertIn("amount=50000", body["url"])
        self.assertIn("Installment", body["url"])
        self.assertFalse(PaymentRequest.objects.exists())

    @override_settings(SMARTGATEWAY_PUBLIC_BASE_URL="")
    def test_manual_page_needs_the_public_origin(self):
        enrollment, *_ = self._enroll(self.jdift)
        r = self._send(enrollment)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("SMARTGATEWAY_PUBLIC_BASE_URL", r.json()["detail"])

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


@override_settings(
    **SG_ON,
    RAZORPAY_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_shared",
    RAZORPAY_KEY_SECRET="rzp_shared_secret",
    RAZORPAY_ACCOUNTS={"JDIFT_ROYALTY": {"live": True}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RowSendFeeLinkTests(SendFeeLinkTests):
    """Per-row "Send link" (student details → Fees): any unpaid row.
    Every JDSD row on SmartGateway (registration included, user rule
    2026-11-06); for JDIFT only the registration row, on Razorpay."""

    def _client(self):
        client = APIClient()
        client.force_authenticate(user=self.staff)
        return client

    def test_any_unpaid_installment_can_be_sent_not_only_the_next(self):
        enrollment, i1, i2 = self._enroll(self.jdsd)
        r = self._client().post(reverse("installment-send-fee-link", args=[i2.id]))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["installment_id"], i2.id)
        self.assertEqual(body["gateway"], "smartgateway")
        self.assertTrue(body["email_sent"], body)
        pr = PaymentRequest.objects.get(pk=body["payment_request_id"])
        self.assertEqual((pr.installment_id, pr.account), (i2.id, "JDSD_TRUST"))

    def _registration_row(self, institute):
        enrollment, *_ = self._enroll(institute)
        return Installment.objects.create(
            enrollment=enrollment, kind=Installment.Kind.REGISTRATION,
            sequence=0, due_date=date(2026, 6, 1), amount=Decimal("11800"),
        )

    def test_jdift_registration_row_goes_to_razorpay(self):
        reg = self._registration_row(self.jdift)
        r = self._client().post(reverse("installment-send-fee-link", args=[reg.id]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["gateway"], "razorpay")
        self.assertEqual(r.json()["installment"], "Registration fee")
        pr = PaymentRequest.objects.get(pk=r.json()["payment_request_id"])
        self.assertEqual(pr.account, "JDIFT_ROYALTY")

    def test_jdsd_registration_row_goes_to_smartgateway_trust(self):
        reg = self._registration_row(self.jdsd)
        r = self._client().post(reverse("installment-send-fee-link", args=[reg.id]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["gateway"], "smartgateway")
        pr = PaymentRequest.objects.get(pk=r.json()["payment_request_id"])
        self.assertEqual(pr.account, "JDSD_TRUST")

    def test_paid_row_is_refused(self):
        enrollment, i1, _ = self._enroll(self.jdsd)
        FeeReceipt.objects.create(
            receipt_no="R-1", enrollment=enrollment, installment=i1,
            basic_fee=i1.amount, amount=i1.amount,
            payment_mode=FeeReceipt.PaymentMode.CASH, received_date=date(2026, 7, 1),
        )
        r = self._client().post(reverse("installment-send-fee-link", args=[i1.id]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("already paid", r.json()["detail"])

    def test_jdift_row_is_not_sendable_and_flagged_in_the_list(self):
        enrollment, i1, _ = self._enroll(self.jdift)
        r = self._client().post(reverse("installment-send-fee-link", args=[i1.id]))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("paid at the college", r.json()["detail"])
        self.assertFalse(PaymentRequest.objects.exists())

        rows = self._client().get(
            reverse("installment-list-create"), {"enrollment": enrollment.id},
        ).json()
        self.assertEqual({row["online_payable"] for row in rows}, {False})

    def test_jdsd_rows_are_flagged_online_payable(self):
        enrollment, *_ = self._enroll(self.jdsd)
        rows = self._client().get(
            reverse("installment-list-create"), {"enrollment": enrollment.id},
        ).json()
        self.assertEqual({row["online_payable"] for row in rows}, {True})

    def test_other_fee_link_and_settlement_write_a_receipt(self):
        from apps.payments import services

        enrollment, *_ = self._enroll(self.jdsd)
        fee = OtherFee.objects.create(
            enrollment=enrollment, name="Exam re-attempt", amount=Decimal("1500"),
        )
        r = self._client().post(reverse("other-fee-send-fee-link", args=[fee.id]))
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["other_fee_id"], fee.id)
        self.assertEqual(body["installment"], "Exam re-attempt")
        self.assertEqual(body["gateway"], "smartgateway")
        pr = PaymentRequest.objects.get(pk=body["payment_request_id"])
        self.assertEqual(pr.purpose, PaymentRequest.Purpose.OTHER_FEE)
        self.assertEqual(pr.other_fee_id, fee.id)

        order = PaymentOrder.objects.create(
            request=pr, order_id=f"OF{pr.pk}N01", amount=pr.amount,
        )
        services.apply_order_body(order, {"status": "CHARGED"})
        receipt = FeeReceipt.objects.get(instrument_ref=order.order_id)
        self.assertEqual(receipt.other_fee_id, fee.id)
        self.assertEqual(receipt.enrollment_id, enrollment.id)
        self.assertEqual(receipt.amount, Decimal("1500"))
        # Fully paid now: the list says so and a resend is refused.
        row = self._client().get(
            reverse("other-fee-list-create"), {"enrollment": enrollment.id},
        ).json()[0]
        self.assertEqual(Decimal(row["balance"]), Decimal("0"))
        r = self._client().post(reverse("other-fee-send-fee-link", args=[fee.id]))
        self.assertEqual(r.status_code, 400)

    def test_jdift_other_fee_is_paid_at_the_college(self):
        enrollment, *_ = self._enroll(self.jdift)
        fee = OtherFee.objects.create(
            enrollment=enrollment, name="Kit", amount=Decimal("500"),
        )
        r = self._client().post(reverse("other-fee-send-fee-link", args=[fee.id]))
        self.assertEqual(r.status_code, 400)
        row = self._client().get(
            reverse("other-fee-list-create"), {"enrollment": enrollment.id},
        ).json()[0]
        self.assertFalse(row["online_payable"])
