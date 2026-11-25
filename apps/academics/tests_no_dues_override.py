"""No Due Certificate (client, 2026-11-25):

- the sheet carries no certificate number (the number stays on the record);
- when Accounts issues it OVER outstanding dues (override_eligibility),
  the Account Dept. remark reads "Fee Pending - Exam Permission Granted"
  instead of "Fees cleared - no outstanding dues".
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.cert_service import (
    NO_DUES_REMARK_CLEAR, NO_DUES_REMARK_OVERRIDE,
)
from apps.academics.models import Certificate
from apps.academics.tests_transcript_pdf import _pdf_text
from apps.admissions.models import Enrollment, Student
from apps.fees.models import Installment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)


class NoDuesOverrideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        sem = Semester.objects.create(name="Sem 1", number=1, program=program)
        batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year)
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=inst, campus=campus, program=program, academic_year=year,
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, program=program, semester=sem, campus=campus,
            batch=batch, academic_year=year, status=Enrollment.Status.ACTIVE,
        )
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com")

    def _cert(self):
        return Certificate.objects.create(
            student=self.student, enrollment=self.enrollment,
            type=Certificate.Type.NO_DUES,
        )

    def _issue(self, cert, **body):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c.post(reverse("certificate-issue", args=[cert.pk]), body,
                      format="json")

    def test_clear_fees_say_fees_cleared(self):
        cert = self._cert()
        r = self._issue(cert)
        self.assertEqual(r.status_code, 200, r.content)
        cert.refresh_from_db()
        nd = cert.snapshot["no_dues"]
        self.assertFalse(nd["fee_override"])
        self.assertEqual(nd["accounts_remark"], NO_DUES_REMARK_CLEAR)

    def test_override_over_dues_says_fee_pending(self):
        Installment.objects.create(
            enrollment=self.enrollment, sequence=1, due_date=date(2026, 6, 1),
            amount=Decimal("50000"), description="Term 1",
        )
        cert = self._cert()
        # Refused without the override...
        self.assertEqual(self._issue(cert).status_code, 400)
        # ...issued with it, and the sheet says the fee is pending.
        r = self._issue(cert, override_eligibility=True)
        self.assertEqual(r.status_code, 200, r.content)
        cert.refresh_from_db()
        nd = cert.snapshot["no_dues"]
        self.assertTrue(nd["fee_override"])
        self.assertEqual(nd["accounts_remark"], NO_DUES_REMARK_OVERRIDE)

        c = APIClient()
        c.force_authenticate(self.admin)
        pdf = c.get(reverse("certificate-pdf", args=[cert.pk])).content
        text = _pdf_text(pdf)
        # The remark wraps inside the Remarks/Signature cell.
        self.assertIn("Fee Pending - Exam", text)
        self.assertIn("Permission Granted", text)
        self.assertNotIn("Fees cleared", text)

    def test_sheet_has_no_certificate_number(self):
        cert = self._cert()
        self._issue(cert)
        cert.refresh_from_db()
        self.assertTrue(cert.certificate_no)  # still on the record
        c = APIClient()
        c.force_authenticate(self.admin)
        text = _pdf_text(c.get(reverse("certificate-pdf", args=[cert.pk])).content)
        self.assertNotIn("Certificate No", text)
        self.assertNotIn(cert.certificate_no, text)
        self.assertIn("Date:", text)
