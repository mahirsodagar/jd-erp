"""Deactivating / activating an employee keeps the reason, the time and
who did it — it used to be validated and then thrown away."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee

User = get_user_model()


class EmployeeStatusReasonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.emp = make_employee("ASHA", institute=institute, campus=campus)
        cls.admin = User.objects.create_superuser(
            username="hr", email="hr@e.com", password="x", full_name="HR Head",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _post(self, action, **body):
        return self.client.post(
            f"/api/employees/{self.emp.id}/{action}/", body, format="json",
        )

    def test_deactivation_reason_is_saved_and_returned(self):
        r = self._post("deactivate", reason="Contract ended in August")
        self.assertEqual(r.status_code, 200, r.content)

        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.INACTIVE)
        self.assertEqual(self.emp.status_reason, "Contract ended in August")
        self.assertEqual(self.emp.status_changed_by, self.admin)
        self.assertIsNotNone(self.emp.status_changed_at)

        body = r.json()
        self.assertEqual(body["status_reason"], "Contract ended in August")
        self.assertEqual(body["status_changed_by_name"], "HR Head")

    def test_deactivation_still_requires_a_reason(self):
        r = self._post("deactivate")
        self.assertEqual(r.status_code, 400)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.ACTIVE)
        self.assertEqual(self.emp.status_reason, "")

    def test_reactivation_replaces_the_old_reason(self):
        self._post("deactivate", reason="Contract ended in August")
        r = self._post("activate")
        self.assertEqual(r.status_code, 200, r.content)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.ACTIVE)
        self.assertEqual(self.emp.status_reason, "")
