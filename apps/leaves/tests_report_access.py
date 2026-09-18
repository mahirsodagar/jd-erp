"""An ordinary employee (Faculty role) can use their own leaves but not
the campus-wide leave report."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.seed import (
    FACULTY_PERMISSION_KEYS, seed_faculty_role, seed_permissions,
)

User = get_user_model()

REPORT = "/api/leaves/reports/summary/?start_date=2026-06-01&end_date=2027-05-31"


class FacultyLeaveReportAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        faculty = seed_faculty_role()
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.user = User.objects.create_user(
            username="asha", email="asha@e.com", password="x",
        )
        cls.user.roles.add(faculty)
        cls.user.campuses.add(campus)
        make_employee("ASHA", institute=institute, campus=campus,
                      user_account=cls.user)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_baseline_does_not_include_the_report(self):
        self.assertNotIn("leaves.report.view", FACULTY_PERMISSION_KEYS)

    def test_faculty_cannot_open_the_report(self):
        self.assertEqual(self.client.get(REPORT).status_code, 403)

    def test_faculty_still_has_self_service_leaves(self):
        for url in ("/api/leaves/applications/dashboard/",
                    "/api/leaves/applications/balances/"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, (url, r.content))
