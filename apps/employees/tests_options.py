"""`/api/employees/options/` — staff directory for dropdowns.

A plain Faculty login (no `employees.employee.view`) must still be able
to pick a mentor / HOD / reviewer, so this endpoint needs only a login.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.tests_electives import make_faculty
from apps.employees.models import Employee
from apps.master.models import Campus, Institute


class EmployeeOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.ann = make_faculty(
            code="E1", name="Ann", campus=campus, institute=institute,
        )
        cls.ann.family_name = "Lee"
        cls.ann.save(update_fields=["family_name"])
        cls.bob = make_faculty(
            code="E2", name="Bob", campus=campus, institute=institute,
        )
        cls.gone = make_faculty(
            code="E3", name="Zed", campus=campus, institute=institute,
        )
        cls.gone.status = Employee.Status.INACTIVE
        cls.gone.save(update_fields=["status"])
        cls.faculty_user = get_user_model().objects.create_user(
            username="fac", password="x", email="f@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.faculty_user)
        self.url = reverse("employee-options")

    def test_faculty_without_hr_perm_sees_active_staff(self):
        # The HR list is closed to this user…
        self.assertEqual(
            self.client.get(reverse("employee-list-create")).status_code, 403,
        )
        # …but the picker is not.
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["emp_code"] for r in res.data], ["E1", "E2"])
        self.assertEqual(res.data[0]["full_name"], "Ann Lee")
        self.assertNotIn("mobile_primary", res.data[0])

    def test_all_flag_includes_inactive(self):
        res = self.client.get(self.url, {"all": "1"})
        self.assertEqual([r["emp_code"] for r in res.data], ["E1", "E2", "E3"])

    def test_anonymous_denied(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
