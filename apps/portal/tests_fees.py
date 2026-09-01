"""Student-portal fee module: the schedule, the sequence rule, and the
SmartGateway hand-off.

The things worth pinning down are the ones that would cost money to get
wrong: a student paying installment #3 while #1 is still open, a stale
pay link still charging yesterday's amount, and a settled order writing
two receipts because the webhook was redelivered.

No network — `create_session` / `fetch_order` are patched.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.fees.models import FeeReceipt, Installment
from apps.master.models import (
    AcademicYear, Batch, Campus, FeeTemplate, Institute, Program, Semester,
)
from apps.payments import services
from apps.payments.models import PaymentOrder, PaymentRequest

SG_ON = dict(
    SMARTGATEWAY_ENABLED=True,
    SMARTGATEWAY_SANDBOX=True,
    SMARTGATEWAY_API_KEY="sg_test_key",
    SMARTGATEWAY_MERCHANT_ID="testhdfc1",
    SMARTGATEWAY_CLIENT_ID="hdfcmaster",
    SMARTGATEWAY_PUBLIC_BASE_URL="https://api.jd.test",
)


@override_settings(**SG_ON)
class PortalFeeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD", code="JD")
        cls.campus = Campus.objects.create(
            name="Main", code="MAIN",
        )
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(number=1, name="Sem 1")
        cls.batch = Batch.objects.create(
            name="B1", campus=cls.campus, program=cls.program,
            academic_year=cls.year,
        )
        FeeTemplate.objects.create(
            name="BDes 2026-27", academic_year=cls.year, campus=cls.campus,
            program=cls.program, total_fee=Decimal("200000"),
            registration_fee=Decimal("10000"),
            application_fee=Decimal("1000"),
        )

        cls.user = get_user_model().objects.create_user(
            username="asha", email="asha@example.com", password="pw-not-used-here",
        )
        cls.student = Student.objects.create(
            student_name="Asha Rao", gender="F", dob=date(2006, 1, 1),
            nationality="INDIAN", institute=cls.institute,
            campus=cls.campus, program=cls.program, academic_year=cls.year,
            student_mobile="9000000000", student_email="asha@example.com",
            user_account=cls.user,
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, program=cls.program, semester=cls.sem,
            campus=cls.campus, batch=cls.batch, academic_year=cls.year,
            status=Enrollment.Status.ACTIVE,
        )
        cls.i1 = Installment.objects.create(
            enrollment=cls.enrollment, sequence=1,
            due_date=date(2026, 7, 1), amount=Decimal("50000"),
            description="First installment",
        )
        cls.i2 = Installment.objects.create(
            enrollment=cls.enrollment, sequence=2,
            due_date=date(2026, 12, 1), amount=Decimal("50000"),
            description="Second installment",
        )

    def setUp(self):
        # JWT-only DRF config, so a session login would 401 — authenticate
        # the request object directly instead.
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _pay(self, installment):
        return self.client.post(
            reverse("portal-fee-installment-pay", args=[installment.id]),
        )

    # --- the schedule -------------------------------------------------

    def test_summary_lists_schedule_and_marks_the_next_row_payable(self):
        r = self.client.get(reverse("portal-fees"))
        self.assertEqual(r.status_code, 200)
        body = r.json()

        self.assertEqual(body["next_installment_id"], self.i1.id)
        rows = {i["sequence"]: i for i in body["installments"]}
        self.assertTrue(rows[1]["is_payable"])
        self.assertFalse(rows[2]["is_payable"])
        self.assertEqual(rows[1]["state"], "DUE")
        self.assertEqual(Decimal(rows[1]["balance"]), Decimal("50000"))

    def test_cancelled_receipts_do_not_count_as_paid(self):
        FeeReceipt.objects.create(
            receipt_no="RCP-CANCELLED-1", enrollment=self.enrollment,
            installment=self.i1, basic_fee=Decimal("50000"),
            amount=Decimal("50000"), payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 1),
            status=FeeReceipt.Status.CANCELLED,
        )
        rows = {
            i["sequence"]: i
            for i in self.client.get(reverse("portal-fees")).json()["installments"]
        }
        self.assertEqual(Decimal(rows[1]["paid"]), Decimal("0"))
        self.assertTrue(rows[1]["is_payable"])

    # --- the sequence rule --------------------------------------------

    def test_cannot_pay_out_of_order(self):
        r = self._pay(self.i2)
        self.assertEqual(r.status_code, 409)
        self.assertIn("in order", r.json()["detail"])
        self.assertFalse(PaymentRequest.objects.exists())

    def test_second_installment_unlocks_once_the_first_clears(self):
        FeeReceipt.objects.create(
            receipt_no="RCP-COUNTER-1", enrollment=self.enrollment,
            installment=self.i1, basic_fee=Decimal("50000"),
            amount=Decimal("50000"), payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 1),
        )
        body = self.client.get(reverse("portal-fees")).json()
        self.assertEqual(body["next_installment_id"], self.i2.id)
        self.assertEqual(self._pay(self.i2).status_code, 200)

    def test_a_paid_installment_cannot_be_paid_again(self):
        FeeReceipt.objects.create(
            receipt_no="RCP-COUNTER-2", enrollment=self.enrollment,
            installment=self.i1, basic_fee=Decimal("50000"),
            amount=Decimal("50000"), payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 1),
        )
        r = self._pay(self.i1)
        self.assertEqual(r.status_code, 409)
        self.assertIn("already fully paid", r.json()["detail"])

    def test_another_students_installment_is_not_visible(self):
        other_student = Student.objects.create(
            # Explicit id: the generator lives in admissions.services, so a
            # bare create() leaves the column blank and two of them collide.
            application_form_id="JD-2026-0002",
            student_name="Ravi", gender="M", dob=date(2005, 2, 2),
            nationality="INDIAN", institute=self.institute,
            campus=self.campus, program=self.program, academic_year=self.year,
            student_mobile="9000000001", student_email="ravi@example.com",
        )
        other_enrollment = Enrollment.objects.create(
            student=other_student, program=self.program, semester=self.sem,
            campus=self.campus, batch=self.batch, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )
        theirs = Installment.objects.create(
            enrollment=other_enrollment, sequence=1,
            due_date=date(2026, 7, 1), amount=Decimal("50000"),
        )
        self.assertEqual(self._pay(theirs).status_code, 404)

    # --- amounts -------------------------------------------------------

    def test_pay_asks_for_the_outstanding_balance_not_the_face_value(self):
        FeeReceipt.objects.create(
            receipt_no="RCP-PART-1", enrollment=self.enrollment,
            installment=self.i1, basic_fee=Decimal("20000"),
            amount=Decimal("20000"), payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 1),
        )
        r = self._pay(self.i1)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(r.json()["amount"]), Decimal("30000"))

    def test_a_stale_request_is_cancelled_when_the_balance_changes(self):
        first = self._pay(self.i1).json()["payment_request_id"]
        FeeReceipt.objects.create(
            receipt_no="RCP-PART-2", enrollment=self.enrollment,
            installment=self.i1, basic_fee=Decimal("20000"),
            amount=Decimal("20000"), payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 1),
        )
        second = self._pay(self.i1).json()["payment_request_id"]

        self.assertNotEqual(first, second)
        self.assertEqual(
            PaymentRequest.objects.get(pk=first).status,
            PaymentRequest.Status.CANCELLED,
        )
        self.assertEqual(
            PaymentRequest.objects.get(pk=second).amount, Decimal("30000"),
        )

    def test_reopening_an_unchanged_request_reuses_the_same_token(self):
        first = self._pay(self.i1).json()
        second = self._pay(self.i1).json()
        self.assertEqual(first["payment_request_id"], second["payment_request_id"])
        self.assertEqual(first["pay_url"], second["pay_url"])

    def test_pay_url_points_at_our_api_not_the_bank(self):
        url = self._pay(self.i1).json()["pay_url"]
        token = PaymentRequest.objects.get().token
        self.assertEqual(url, f"https://api.jd.test/api/public/pay/{token}/")

    # --- settlement ----------------------------------------------------

    def _charge(self, payment_request) -> PaymentOrder:
        """Take a request all the way to CHARGED, without a network."""
        session = {
            "id": "ordeh_test", "status": "NEW",
            "payment_links": {"web": "https://sandbox.bank.test/pay/abc"},
        }
        with patch.object(services, "create_session", return_value=session):
            order = services.start_or_resume_order(payment_request)
        return services.apply_order_body(order, {
            "order_id": order.order_id,
            "status": "CHARGED",
            "txn_id": "txn-123",
            "payment_method": "VISA",
            "payment_method_type": "CARD",
        })

    def test_a_charged_order_writes_a_receipt_against_the_installment(self):
        pr = PaymentRequest.objects.get(
            pk=self._pay(self.i1).json()["payment_request_id"],
        )
        order = self._charge(pr)

        receipt = FeeReceipt.objects.get(installment=self.i1)
        self.assertEqual(receipt.amount, Decimal("50000"))
        self.assertEqual(receipt.enrollment, self.enrollment)
        self.assertEqual(receipt.payment_mode, FeeReceipt.PaymentMode.ONLINE)
        self.assertEqual(receipt.instrument_ref, order.order_id)
        self.assertTrue(receipt.receipt_no.startswith("RCP-MAIN-"))
        # No human received it.
        self.assertIsNone(receipt.received_by)

        pr.refresh_from_db()
        self.assertEqual(pr.status, PaymentRequest.Status.PAID)

    def test_a_upi_payment_is_recorded_as_upi(self):
        pr = PaymentRequest.objects.get(
            pk=self._pay(self.i1).json()["payment_request_id"],
        )
        session = {
            "id": "ordeh_test", "status": "NEW",
            "payment_links": {"web": "https://sandbox.bank.test/pay/abc"},
        }
        with patch.object(services, "create_session", return_value=session):
            order = services.start_or_resume_order(pr)
        services.apply_order_body(order, {
            "order_id": order.order_id, "status": "CHARGED",
            "payment_method": "UPI", "payment_method_type": "UPI",
        })
        self.assertEqual(
            FeeReceipt.objects.get(installment=self.i1).payment_mode,
            FeeReceipt.PaymentMode.UPI,
        )

    def test_replaying_a_settled_order_does_not_double_post(self):
        pr = PaymentRequest.objects.get(
            pk=self._pay(self.i1).json()["payment_request_id"],
        )
        order = self._charge(pr)
        # A redelivered webhook re-applies the same body.
        services.apply_order_body(order, {
            "order_id": order.order_id, "status": "CHARGED",
        })
        self.assertEqual(FeeReceipt.objects.filter(installment=self.i1).count(), 1)

    def test_settling_online_clears_the_row_and_unlocks_the_next(self):
        pr = PaymentRequest.objects.get(
            pk=self._pay(self.i1).json()["payment_request_id"],
        )
        self._charge(pr)

        body = self.client.get(reverse("portal-fees")).json()
        rows = {i["sequence"]: i for i in body["installments"]}
        self.assertEqual(rows[1]["state"], "PAID")
        self.assertEqual(Decimal(rows[1]["balance"]), Decimal("0"))
        self.assertEqual(body["next_installment_id"], self.i2.id)
        self.assertEqual(Decimal(body["summary"]["paid_total"]), Decimal("50000"))

    def test_installment_order_ids_are_distinct_from_application_fee_ids(self):
        pr = PaymentRequest.objects.get(
            pk=self._pay(self.i1).json()["payment_request_id"],
        )
        order = self._charge(pr)
        self.assertTrue(order.order_id.startswith("FI"))
        self.assertLessEqual(len(order.order_id), 20)

    # --- gateway off ---------------------------------------------------

    @override_settings(SMARTGATEWAY_ENABLED=False)
    def test_pay_is_refused_when_the_gateway_is_off(self):
        r = self._pay(self.i1)
        self.assertEqual(r.status_code, 503)
        self.assertFalse(self.client.get(reverse("portal-fees")).json()[
            "online_payment_enabled"
        ])


@override_settings(**SG_ON)
class PortalApplicationViewTests(TestCase):
    """The read-only playback of the submitted application form."""

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD", code="JD")
        cls.campus = Campus.objects.create(
            name="Main", code="MAIN",
        )
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.user = get_user_model().objects.create_user(
            username="asha2", email="asha2@example.com", password="pw-not-used-here",
        )
        cls.student = Student.objects.create(
            student_name="Asha Rao", gender="F", dob=date(2006, 1, 1),
            nationality="INDIAN", category="OBC", institute=cls.institute,
            campus=cls.campus, program=cls.program, academic_year=cls.year,
            student_mobile="9000000000", student_email="asha@example.com",
            user_account=cls.user,
        )

    def setUp(self):
        # JWT-only DRF config, so a session login would 401 — authenticate
        # the request object directly instead.
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_returns_the_students_own_form_with_readable_labels(self):
        r = self.client.get(reverse("portal-application"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["personal"]["student_name"], "Asha Rao")
        self.assertEqual(body["personal"]["gender_display"], "Female")
        self.assertEqual(body["personal"]["category_display"], "OBC")
        self.assertEqual(body["placement"]["campus_name"], "Main")
        self.assertEqual(body["application_form_id"], self.student.application_form_id)

    def test_is_read_only(self):
        r = self.client.post(reverse("portal-application"), {})
        self.assertEqual(r.status_code, 405)

    def test_a_non_student_account_is_refused(self):
        outsider = get_user_model().objects.create_user(
            username="staffer", email="staffer@example.com", password="pw-not-used-here",
        )
        self.client.force_authenticate(user=outsider)
        self.assertEqual(
            self.client.get(reverse("portal-application")).status_code, 403,
        )
