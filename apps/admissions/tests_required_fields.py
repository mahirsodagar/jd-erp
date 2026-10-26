"""Required fields on the public self-fill application form.

The endpoint refuses a submit with anything required left blank, so a
student can't skip a field by getting past the browser's own checks.
Uploads already stored by an earlier submit count as present — the form
has no way to re-send a file it never downloaded.
"""

import json
import shutil
import tempfile
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.admissions.models import Student
from apps.leads.models import Lead
from apps.master.models import (
    AcademicYear, Campus, City, Institute, LeadSource, Program, State,
)

# Smallest valid GIF — enough for an ImageField to store.
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04"
    b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def complete_payload(*, campus, program, city, **over) -> dict:
    """Multipart body with every required field filled in, the way the
    form sends it. `over` replaces or (with None) drops a key."""
    body = {
        "campus": campus.id,
        "program": program.id,
        "student_name": "Asha Rao",
        "dob": "2004-03-11",
        "gender": "F",
        "category": "GEN",
        "study_medium": "E",
        "nationality": "INDIAN",
        "aadhaar_number": "234567890123",
        "blood_group": "O+",
        "father_name": "Ravi Rao",
        "mother_name": "Meena Rao",
        "father_mobile": "9000000001",
        "father_email": "ravi@example.com",
        "father_occupation": "Engineer",
        "mother_occupation": "Teacher",
        "student_mobile": "9900112233",
        "student_email": "asha@example.com",
        "current_address": "12 MG Road",
        "current_state": city.state_id,
        "current_city": city.id,
        "current_pincode": "560001",
        "permanent_address": "12 MG Road",
        "permanent_state": city.state_id,
        "permanent_city": city.id,
        "permanent_pincode": "560001",
        "declaration_accepted": "true",
        "rules_accepted": "true",
        "documents": json.dumps([{
            "header": "PUC",
            "regno_yearpassing": "2022",
            "school_college": "Govt PU College",
            "university_board": "KSEEB",
            "certificate_no": "",
            "percent_obtained": "82.5",
        }]),
        "photo": SimpleUploadedFile("photo.gif", GIF, content_type="image/gif"),
        "document_file_0": SimpleUploadedFile(
            "puc.pdf", b"%PDF-1.4", content_type="application/pdf",
        ),
    }
    for k, v in over.items():
        if v is None:
            body.pop(k, None)
        else:
            body[k] = v
    return body


class RequiredFixture(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.program = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=institute,
        )
        cls.program.campuses.set([cls.campus])
        AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        state = State.objects.create(name="Karnataka", code="KA")
        cls.city = City.objects.create(name="Bengaluru", state=state)

    def setUp(self):
        self.lead = Lead.objects.create(
            name="Asha", email="asha@example.com", phone="+919900112233",
            campus=self.campus, program=self.program, source=self.source,
            application_token=uuid.uuid4(),
        )
        self.url = f"/api/public/application/{self.lead.application_token}/"

    def payload(self, **over):
        return complete_payload(
            campus=self.campus, program=self.program, city=self.city, **over,
        )


class RequiredFieldTests(RequiredFixture):

    def test_complete_form_is_accepted(self):
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)

    def test_blank_required_field_is_refused_and_named(self):
        r = self.client.post(self.url, self.payload(father_name="  "))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Father's name", r.json()["detail"])
        self.assertFalse(Student.objects.filter(lead_origin=self.lead).exists())

    def test_mothers_contact_stays_optional(self):
        r = self.client.post(
            self.url, self.payload(mother_mobile=None, mother_email=None),
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_aadhaar_required_only_for_indian_nationals(self):
        r = self.client.post(self.url, self.payload(aadhaar_number=None))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Aadhaar", r.json()["detail"])

        r = self.client.post(
            self.url, self.payload(aadhaar_number=None, nationality="OTHERS"),
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_photo_and_education_are_required(self):
        r = self.client.post(
            self.url, self.payload(photo=None, documents="[]"),
        )
        detail = r.json()["detail"]
        self.assertIn("Photo", detail)
        self.assertIn("Education history", detail)

    def test_education_row_needs_its_certificate(self):
        r = self.client.post(self.url, self.payload(document_file_0=None))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Education row 1: Document", r.json()["detail"])

    def test_resubmit_does_not_demand_stored_uploads_again(self):
        self.assertEqual(
            self.client.post(self.url, self.payload()).status_code, 201,
        )
        r = self.client.post(
            self.url, self.payload(photo=None, document_file_0=None),
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_prefill_reports_stored_uploads(self):
        self.client.post(self.url, self.payload())
        student = self.client.get(self.url).json()["student"]
        self.assertTrue(student["has_photo"])
        self.assertTrue(student["documents"][0]["has_file"])

    def test_prefill_carries_fathers_contact_from_the_lead(self):
        self.lead.father_mobile = "+919811122233"
        self.lead.father_email = "ravi@example.com"
        self.lead.save(update_fields=["father_mobile", "father_email"])
        data = self.client.get(self.url).json()
        self.assertEqual(data["father_mobile"], "+919811122233")
        self.assertEqual(data["father_email"], "ravi@example.com")

    def test_closed_form_still_answers_403(self):
        self.lead.application_locked_for_student = True
        self.lead.save(update_fields=["application_locked_for_student"])
        r = self.client.post(self.url, {"documents": "[]"})
        self.assertEqual(r.status_code, 403)
