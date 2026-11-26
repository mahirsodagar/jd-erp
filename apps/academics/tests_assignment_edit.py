"""Edit / delete an assignment (2026-11-26): the author with
`academics.assignment.create`, or anyone with the *_any keys."""

from datetime import date, datetime, timezone as dt_tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Assignment, AssignmentSubmission
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
)
from apps.roles.models import Permission, Role

User = get_user_model()


class AssignmentEditDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        cls.sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(name="BD-1", program=cls.program,
                                         campus=cls.campus, academic_year=year)
        cls.subject = Subject.objects.create(name="Pattern Making", code="PM")
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=inst, campus=cls.campus, program=cls.program,
            academic_year=year,
        )
        Enrollment.objects.create(
            student=cls.student, program=cls.program, semester=cls.sem,
            campus=cls.campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE)

        def faculty(name):
            u = User.objects.create_user(username=name, email=f"{name}@x.com", password="x")
            role = Role.objects.create(name=f"role-{name}")
            perm, _ = Permission.objects.get_or_create(
                key="academics.assignment.create",
                defaults={"module": "academics", "label": "create"})
            role.permissions.add(perm)
            u.roles.add(role)
            u.campuses.add(cls.campus)
            return u

        cls.author = faculty("author")
        cls.other = faculty("other")

    def setUp(self):
        self.a = Assignment.objects.create(
            subject=self.subject, program=self.program, campus=self.campus,
            batch=self.batch, semester=self.sem, title="Bodice block",
            max_marks=10, created_by=self.author,
            due_date=datetime(2026, 11, 20, 12, 30, tzinfo=dt_tz.utc))
        self.url = reverse("assignment-detail", args=[self.a.pk])

    def _as(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_author_edits_and_clears_batch(self):
        res = self._as(self.author).patch(
            self.url, {"title": "Bodice block v2", "batch": None}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.a.refresh_from_db()
        self.assertEqual(self.a.title, "Bodice block v2")
        self.assertIsNone(self.a.batch)          # now program-wide
        self.assertEqual(self.a.campus, self.campus)

    def test_multipart_empty_batch_clears_it_too(self):
        res = self._as(self.author).patch(
            self.url, {"batch": "", "title": "T"}, format="multipart")
        self.assertEqual(res.status_code, 200, res.data)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.batch)

    def test_other_faculty_cannot_edit_or_delete(self):
        c = self._as(self.other)
        self.assertEqual(c.patch(self.url, {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(c.delete(self.url).status_code, 403)

    def test_author_delete_cascades_submissions(self):
        AssignmentSubmission.objects.create(assignment=self.a, student=self.student)
        res = self._as(self.author).delete(self.url)
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Assignment.objects.filter(pk=self.a.pk).exists())
        self.assertFalse(AssignmentSubmission.objects.filter(assignment_id=self.a.pk).exists())
