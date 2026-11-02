"""Application fee receipt (lead) + the per-request receipt resolver.

Every fee a person pays must come back as a downloadable receipt, so
these cover the ones that are not FeeReceipt rows: the lead's
application fee, and the public result-page download that hands the
payer their own copy by pay-link token.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.fees.services.application_receipt import (
    ensure_application_fee_receipt_no, render_application_fee_receipt,
)
from apps.leads.models import Lead
from apps.master.models import AcademicYear, Campus, Institute, LeadSource, Program
from apps.payments.models import PaymentOrder, PaymentRequest
from apps.payments.receipts import receipt_pdf_for_request

User = get_user_model()


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="a", email="a@e.com", password="x",
        )
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BNG")
        cls.prog = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
        )
        cls.prog.campuses.add(cls.campus)
        AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )

    def _lead(self, **kw):
        return Lead.objects.create(
            name="Asha", email="asha@example.com", phone="9900112233",
            phone_normalized="9900112233", city="Bengaluru", state="Karnataka",
            campus=self.campus, program=self.prog, source=self.source, **kw,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)


class ApplicationFeeReceiptTests(_Base):

    def test_number_reserved_once_and_pdf_renders(self):
        lead = self._lead(
            application_fee_paid_at=timezone.now(),
            application_fee_amount=Decimal("1000"),
            application_fee_mode="UPI", application_fee_ref="UPI123",
        )
        no = ensure_application_fee_receipt_no(lead)
        self.assertTrue(no.startswith("JDBNG"), no)
        self.assertEqual(ensure_application_fee_receipt_no(lead), no)
        out = render_application_fee_receipt(lead)
        self.assertTrue(out.startswith(b"%PDF"))

    def test_unpaid_lead_has_no_receipt(self):
        lead = self._lead()
        with self.assertRaises(ValueError):
            ensure_application_fee_receipt_no(lead)
        r = self.client.get(f"/api/leads/{lead.id}/application-fee/receipt/pdf/")
        self.assertEqual(r.status_code, 404)

    def test_mark_paid_reserves_number_and_download_works(self):
        lead = self._lead()
        r = self.client.post(
            f"/api/leads/{lead.id}/mark-fee-paid/",
            {"amount": "1000", "mode": "cash"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        lead.refresh_from_db()
        self.assertTrue(lead.application_fee_receipt_no)
        self.assertEqual(r.json()["application_fee_receipt_no"],
                         lead.application_fee_receipt_no)

        r = self.client.get(f"/api/leads/{lead.id}/application-fee/receipt/pdf/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn(lead.application_fee_receipt_no, r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_legacy_paid_lead_gets_number_on_first_download(self):
        lead = self._lead(application_fee_paid_at=timezone.now(),
                          application_fee_amount=Decimal("500"))
        self.assertEqual(lead.application_fee_receipt_no, "")
        r = self.client.get(f"/api/leads/{lead.id}/application-fee/receipt/pdf/")
        self.assertEqual(r.status_code, 200)
        lead.refresh_from_db()
        self.assertTrue(lead.application_fee_receipt_no)


class PaymentRequestReceiptTests(_Base):

    def _paid_request(self, lead):
        pr = PaymentRequest.objects.create(
            purpose=PaymentRequest.Purpose.APPLICATION_FEE, lead=lead,
            amount=Decimal("1000"), gateway="smartgateway", account="JDSD_TRUST",
        )
        order = PaymentOrder.objects.create(
            request=pr, order_id=f"ORD{pr.id}", amount=pr.amount,
            status="CHARGED", charged_at=timezone.now(),
        )
        pr.status = PaymentRequest.Status.PAID
        pr.paid_order = order
        pr.paid_at = order.charged_at
        pr.save()
        return pr

    def test_unsettled_request_has_no_receipt(self):
        lead = self._lead()
        pr = PaymentRequest.objects.create(
            purpose=PaymentRequest.Purpose.APPLICATION_FEE, lead=lead,
            amount=Decimal("1000"),
        )
        self.assertIsNone(receipt_pdf_for_request(pr))
        r = self.client.get(f"/api/payments/requests/{pr.id}/receipt/pdf/")
        self.assertEqual(r.status_code, 404)
        r = APIClient().get(f"/api/public/pay/{pr.token}/receipt/")
        self.assertEqual(r.status_code, 404)

    def test_staff_and_public_download_for_paid_application_fee(self):
        lead = self._lead(application_fee_paid_at=timezone.now(),
                          application_fee_amount=Decimal("1000"),
                          application_fee_mode="ONLINE")
        pr = self._paid_request(lead)

        r = self.client.get(f"/api/payments/requests/{pr.id}/receipt/pdf/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.content.startswith(b"%PDF"))

        # The payer, with no login, by the pay-link token.
        r = APIClient().get(f"/api/public/pay/{pr.token}/receipt/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r["Content-Type"], "application/pdf")
        lead.refresh_from_db()
        self.assertIn(lead.application_fee_receipt_no, r["Content-Disposition"])

    def test_staff_download_needs_a_lead_or_fee_role(self):
        lead = self._lead(application_fee_paid_at=timezone.now(),
                          application_fee_amount=Decimal("1000"))
        pr = self._paid_request(lead)
        nobody = User.objects.create_user(username="n", email="n@e.com", password="x")
        c = APIClient()
        c.force_authenticate(nobody)
        self.assertEqual(
            c.get(f"/api/payments/requests/{pr.id}/receipt/pdf/").status_code, 403,
        )
