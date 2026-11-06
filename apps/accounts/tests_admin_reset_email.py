"""Admin password reset mails STAFF via MSG91 `password_reset_by_admin`;
student / parent portal accounts are reset without that mail."""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Student
from apps.master.models import AcademicYear, Campus, Institute, Program

User = get_user_model()
MSG91_OK = (True, '{"status": "success"}')
NEW_PW = "Temp#Pass2026"


@mock.patch("apps.notifications.msg91.send_msg91_template", return_value=MSG91_OK)
class AdminResetEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="admin@example.com")
        cls.staff = User.objects.create_user(
            username="fac1", password="x", email="fac1@example.com",
            full_name="Ann Rao")
        cls.stu_user = User.objects.create_user(
            username="stu1", password="x", email="stu1@example.com")
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        prog = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        Student.objects.create(
            application_form_id="AF-1", student_name="Stu One",
            student_email="stu1@example.com", gender="M", dob="2000-01-01",
            nationality="INDIAN", category="GENERAL", institute=inst,
            campus=campus, program=prog, academic_year=year,
            user_account=cls.stu_user)

    def _reset(self, user):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c.post(reverse("user-reset-password", args=[user.pk]),
                      {"new_password": NEW_PW}, format="json")

    def test_staff_gets_msg91_template(self, msg91):
        r = self._reset(self.staff)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["delivered"])
        k = msg91.call_args.kwargs
        self.assertEqual(k["template_name"], "password_reset_by_admin")
        self.assertEqual(k["recipient_email"], "fac1@example.com")
        self.assertEqual(k["domain"], "mail.jdinstitute.com")
        v = k["variables"]
        self.assertEqual((v["name"], v["username"], v["password"]),
                         ("Ann Rao", "fac1", NEW_PW))
        self.assertIn("login_url", v)

    def test_student_account_reset_without_mail(self, msg91):
        r = self._reset(self.stu_user)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["delivered"])
        self.assertIn("portal credentials", r.json()["delivery_error"])
        msg91.assert_not_called()
        self.stu_user.refresh_from_db()
        self.assertTrue(self.stu_user.check_password(NEW_PW))
