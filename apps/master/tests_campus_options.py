"""`/api/master/campuses/options/` — every active campus for pickers,
open to any signed-in staff user (no `master.campus` key needed)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from datetime import date

from apps.admissions.models import Student
from apps.master.models import AcademicYear, Campus, Institute, Program


class CampusOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Campus.objects.create(name="Goa", code="GOA")
        Campus.objects.create(name="Bangalore", code="BLR")
        Campus.objects.create(name="Old", code="OLD", is_active=False)
        User = get_user_model()
        cls.staff = User.objects.create_user(
            username="staff", email="s@example.com", password="x")
        cls.student_user = User.objects.create_user(
            username="stu", email="st@example.com", password="x")
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=inst, campus=Campus.objects.get(code="GOA"),
            program=program, academic_year=year,
            user_account=cls.student_user,
        )

    def test_staff_without_master_key_get_active_campuses(self):
        c = APIClient()
        c.force_authenticate(self.staff)
        r = c.get(reverse("campus-options"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["code"] for x in r.json()], ["BLR", "GOA"])
        self.assertEqual(set(r.json()[0]), {"id", "name", "code"})

    def test_program_and_batch_lists_are_open_to_staff_without_keys(self):
        """The Closing / Module End Report pickers (2026-11-26): a faculty
        login with no master keys reads programs and batches; writing a
        program still needs `master.program.add`."""
        c = APIClient()
        c.force_authenticate(self.staff)
        r = c.get(reverse("program-list-create"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([p["code"] for p in r.json()], ["BDES"])
        self.assertEqual(c.get(reverse("batch-list-create")).status_code, 200)
        r = c.post(reverse("program-list-create"),
                   {"name": "X", "code": "X"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_students_and_anonymous_are_refused(self):
        c = APIClient()
        self.assertIn(c.get(reverse("campus-options")).status_code, (401, 403))
        c.force_authenticate(self.student_user)
        self.assertEqual(c.get(reverse("campus-options")).status_code, 403)
