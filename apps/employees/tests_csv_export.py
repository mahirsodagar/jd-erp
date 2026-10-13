"""Employees → Download CSV ("Employee Master.csv").

Every matching employee in one file, honouring the list's filters and
campus scoping — the on-screen list is paginated, the export is not.
"""

import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.models import Permission, Role

User = get_user_model()


class EmployeeCsvExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.main = Campus.objects.create(name="Main", code="MAIN")
        north = Campus.objects.create(name="North", code="NORTH")
        cls.boss = make_employee("BOSS", institute=inst, campus=cls.main)
        make_employee(
            "ANN", institute=inst, campus=cls.main,
            reporting_manager_1=cls.boss,
        )
        make_employee("NED", institute=inst, campus=north)

        view, _ = Permission.objects.get_or_create(
            key="employees.employee.view",
            defaults={"label": "View employees", "module": "employees"},
        )
        role = Role.objects.create(name="Campus HR (test)")
        role.permissions.add(view)
        cls.hr = User.objects.create_user(
            username="hr", email="hr@example.com", password="x",
        )
        cls.hr.roles.add(role)
        cls.hr.campuses.add(cls.main)
        cls.admin = User.objects.create_superuser(
            username="admin", email="a@example.com", password="x",
        )

    def _rows(self, user, query=""):
        client = APIClient()
        client.force_authenticate(user)
        r = client.get(f"/api/employees/?output=csv{query}")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("Employee Master.csv", r["Content-Disposition"])
        text = r.content.decode("utf-8-sig")
        return list(csv.DictReader(io.StringIO(text)))

    def test_exports_every_employee_with_full_details(self):
        rows = self._rows(self.admin)
        self.assertEqual(
            sorted(r["Emp code"] for r in rows), ["ANN", "BOSS", "NED"],
        )
        ann = next(r for r in rows if r["Emp code"] == "ANN")
        self.assertEqual(ann["Reporting manager 1"], "Boss")
        self.assertEqual(ann["Current city"], "Bengaluru")
        self.assertEqual(ann["DOB"], "01-01-1990")
        self.assertEqual(ann["Status"], "Active")

    def test_respects_list_filters(self):
        rows = self._rows(self.admin, f"&campus={self.main.id}")
        self.assertEqual(sorted(r["Emp code"] for r in rows), ["ANN", "BOSS"])

    def test_scoped_to_callers_campuses(self):
        rows = self._rows(self.hr)
        self.assertEqual(sorted(r["Emp code"] for r in rows), ["ANN", "BOSS"])

    def test_needs_view_permission(self):
        nobody = User.objects.create_user(
            username="nobody", email="n@example.com", password="x",
        )
        client = APIClient()
        client.force_authenticate(nobody)
        self.assertEqual(
            client.get("/api/employees/?output=csv").status_code, 403,
        )
