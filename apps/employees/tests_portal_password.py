"""Portal passwords are shown once when issued and never stored or
returned by the API afterwards."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.employees.services import provision_portal_user
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee

User = get_user_model()


class PortalPasswordNotStoredTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.emp = make_employee("ASHA", institute=institute, campus=campus)
        cls.admin = User.objects.create_superuser(
            username="admin", email="a@e.com", password="x",
        )

    def test_issued_password_works_but_is_not_kept(self):
        user, password = provision_portal_user(employee=self.emp)
        self.assertTrue(user.check_password(password))
        self.assertNotIn(
            "portal_temp_password",
            {f.name for f in Employee._meta.get_fields()},
        )

    def test_detail_api_never_returns_a_password(self):
        _, password = provision_portal_user(employee=self.emp)
        client = APIClient()
        client.force_authenticate(user=self.admin)
        r = client.get(f"/api/employees/{self.emp.id}/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("portal_temp_password", r.json())
        self.assertNotIn(password, r.content.decode())
