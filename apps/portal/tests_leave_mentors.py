"""Student-portal leave form: the mentor mail-ID dropdown (port of the
legacy student/leaves.php "Select Batch Mentor" list)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)
from apps.roles.models import Role


class LeaveMentorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES",
                                         institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1, program=program)
        # Seeded as system roles by a migration; never re-created.
        faculty_role, _ = Role.objects.get_or_create(name="Faculty")
        hod_role, _ = Role.objects.get_or_create(name="HOD")

        def staff(code, name, email, role=None, active=True):
            e = make_faculty(code=code, name=name, campus=campus,
                             institute=institute)
            u = User.objects.create_user(username=code, email=email,
                                         password="x")
            e.email_primary = email
            e.user_account = u
            if not active:
                e.status = e.Status.INACTIVE
            e.save()
            if role:
                role.users.add(u)
            return e

        cls.fac = staff("F1", "Anita", "anita@jd.edu", faculty_role)
        cls.hod = staff("H1", "Bala", "bala@jd.edu", hod_role)
        cls.hr = staff("R1", "Chitra", "chitra@jd.edu")           # no role
        cls.gone = staff("F2", "Dev", "dev@jd.edu", faculty_role,
                         active=False)
        cls.batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus,
            academic_year=year, mentor=cls.hod,
        )

        cls.user = User.objects.create_user(username="stu", email="s@x.com",
                                            password="x")
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year, user_account=cls.user,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=sem,
            campus=campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_lists_active_faculty_and_hod_with_batch_mentor_default(self):
        r = self.client.get(reverse("portal-leave-mentors"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            [(m["name"], m["email"]) for m in r.data["mentors"]],
            [("Anita", "anita@jd.edu"), ("Bala", "bala@jd.edu")],
        )
        self.assertEqual(r.data["batch_mentor_email"], "bala@jd.edu")

    def test_falls_back_to_every_active_login_when_no_roles_assigned(self):
        for role in Role.objects.filter(name__in=("Faculty", "HOD")):
            role.users.clear()
        r = self.client.get(reverse("portal-leave-mentors"))
        self.assertEqual(
            sorted(m["email"] for m in r.data["mentors"]),
            ["anita@jd.edu", "bala@jd.edu", "chitra@jd.edu"],
        )

    def test_staff_cannot_use_it(self):
        c = APIClient()
        c.force_authenticate(self.hr.user_account)
        self.assertEqual(c.get(reverse("portal-leave-mentors")).status_code, 403)
