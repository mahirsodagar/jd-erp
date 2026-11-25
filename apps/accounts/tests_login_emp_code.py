"""Staff can log in with their employee ID (emp_code) as well as the
portal username / email — including right after a password reset."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.employees.services import provision_portal_user
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee

User = get_user_model()


class LoginWithEmpCodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        # Username derives from first_name ("asha"), emp_code is separate.
        cls.emp = make_employee("BLR-2024-0012", institute=institute, campus=campus)
        cls.emp.first_name = "Asha"
        cls.emp.save(update_fields=["first_name"])
        cls.user, cls.temp_pw = provision_portal_user(employee=cls.emp)
        cls.admin = User.objects.create_superuser(
            username="admin", email="a@e.com", password="Admin#Pass1",
        )

    def _login(self, identifier, password):
        return APIClient().post(
            "/api/auth/login/",
            {"identifier": identifier, "password": password},
            format="json",
        )

    def test_username_still_works(self):
        r = self._login(self.user.username, self.temp_pw)
        self.assertEqual(r.status_code, 200, r.content)

    def test_emp_code_logs_in(self):
        self.assertNotEqual(self.user.username.lower(), self.emp.emp_code.lower())
        r = self._login(self.emp.emp_code, self.temp_pw)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["user"]["id"], self.user.id)

    def test_emp_code_is_case_insensitive(self):
        r = self._login(self.emp.emp_code.lower(), self.temp_pw)
        self.assertEqual(r.status_code, 200, r.content)

    def test_emp_code_after_admin_reset(self):
        admin = APIClient()
        admin.force_authenticate(self.admin)
        r = admin.post(
            f"/api/users/{self.user.id}/reset-password/",
            {"new_password": "Fresh#Pass9"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._login(self.emp.emp_code, self.temp_pw).status_code, 401)
        self.assertEqual(self._login(self.emp.emp_code, "Fresh#Pass9").status_code, 200)

    def test_wrong_password_is_rejected(self):
        r = self._login(self.emp.emp_code, "nope")
        self.assertEqual(r.status_code, 401)

    def test_unlinked_emp_code_is_rejected(self):
        self.emp.user_account = None
        self.emp.save(update_fields=["user_account"])
        r = self._login(self.emp.emp_code, self.temp_pw)
        self.assertEqual(r.status_code, 401)
