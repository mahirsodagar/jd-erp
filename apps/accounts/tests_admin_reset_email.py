"""Admin password reset mails STAFF (template
`account.password_reset_by_admin.email`); student / parent portal
accounts are reset without that mail."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Student
from apps.master.models import AcademicYear, Campus, Institute, Program

User = get_user_model()
NEW_PW = "Temp#Pass2026"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    EMAIL_DEFAULT_REPLY_TO="webmaster@dkul.in",
)
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

    def test_staff_gets_the_reset_mail(self):
        r = self._reset(self.staff)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["delivered"])
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["fac1@example.com"])
        self.assertIn("no-reply@dkul.in", m.from_email)
        # Account mails have no handler → default Reply-To.
        self.assertEqual(m.reply_to, ["webmaster@dkul.in"])
        for needle in ("Ann Rao", "fac1", NEW_PW):
            self.assertIn(needle, m.body)

    def test_student_account_reset_without_mail(self):
        r = self._reset(self.stu_user)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["delivered"])
        self.assertIn("portal credentials", r.json()["delivery_error"])
        self.assertEqual(mail.outbox, [])
        self.stu_user.refresh_from_db()
        self.assertTrue(self.stu_user.check_password(NEW_PW))
