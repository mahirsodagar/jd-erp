"""Aadhaar capture on the application form.

The number is optional (overseas applicants have none, and it often
arrives after the rest of the form) but must be stored unformatted, so a
search matches however the student typed it.
"""

import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.admissions.models import Student
from apps.admissions.services import submit_application_from_lead
from apps.admissions.services_application_pdf import _fmt_aadhaar
from apps.leads.models import Lead
from apps.master.models import AcademicYear, Campus, Institute, LeadSource, Program


class AadhaarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.program = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
        )
        cls.program.campuses.set([cls.campus])
        AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")

    def _lead(self):
        return Lead.objects.create(
            name="Asha", email="asha@example.com", phone="+919900112233",
            campus=self.campus, program=self.program, source=self.source,
            application_token=uuid.uuid4(),
        )

    def _payload(self, **over):
        base = {
            "dob": "2004-03-11",
            "gender": "F",
            "current_address": "12 MG Road",
            "student_mobile": "+919900112233",
            "student_email": "asha@example.com",
        }
        base.update(over)
        return base

    def test_saved_on_first_submit(self):
        student, _ = submit_application_from_lead(
            lead=self._lead(),
            payload=self._payload(aadhaar_number="234567890123"),
        )
        self.assertEqual(student.aadhaar_number, "234567890123")

    def test_optional(self):
        student, _ = submit_application_from_lead(
            lead=self._lead(), payload=self._payload(),
        )
        self.assertEqual(student.aadhaar_number, "")

    def test_spacing_is_stripped_by_the_public_endpoint(self):
        """Students paste it off the card as '1234 5678 9012'."""
        lead = self._lead()
        r = self.client.post(
            f"/api/public/application/{lead.application_token}/",
            data={**self._payload(), "aadhaar_number": "2345 6789-0123"},
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(
            Student.objects.get(lead_origin=lead).aadhaar_number,
            "234567890123",
        )

    def test_resubmit_without_it_keeps_the_saved_number(self):
        """Empty values never overwrite — students fill incrementally."""
        lead = self._lead()
        submit_application_from_lead(
            lead=lead, payload=self._payload(aadhaar_number="234567890123"),
        )
        submit_application_from_lead(
            lead=lead, payload=self._payload(father_name="Ravi"),
        )
        student = Student.objects.get(lead_origin=lead)
        self.assertEqual(student.aadhaar_number, "234567890123")

    def test_model_validator_rejects_bad_numbers(self):
        for bad in ("12345678901", "1234567890123", "034567890123", "abcd"):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Student(aadhaar_number=bad).full_clean()

    def test_pdf_prints_it_grouped(self):
        self.assertEqual(_fmt_aadhaar("234567890123"), "2345 6789 0123")
        # Anything not a full 12 digits is printed as-is, never mis-grouped.
        self.assertEqual(_fmt_aadhaar(""), "")
        self.assertEqual(_fmt_aadhaar("12345"), "12345")
