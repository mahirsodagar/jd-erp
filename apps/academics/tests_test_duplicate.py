"""Duplicate an online Test (with its questions) as a new DRAFT so the
same paper can be published and mapped to another batch."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Test, TestAttempt, TestQuestion
from apps.admissions.models import Student
from apps.master.models import (
    AcademicYear, Campus, Institute, Program, Subject,
)


class DuplicateTestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(name="B.Des", code="BDES",
                                             institute=inst)
        cls.program2 = Program.objects.create(name="M.Des", code="MDES",
                                              institute=inst)
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31))
        cls.year2 = AcademicYear.objects.create(
            code="27-28", start_date=date(2027, 6, 1),
            end_date=date(2028, 5, 31))
        cls.subject = Subject.objects.create(name="Pattern Making", code="PM")

        User = get_user_model()
        cls.owner = User.objects.create_user(
            username="owner", email="o@example.com", password="x")
        cls.other = User.objects.create_user(
            username="other", email="x@example.com", password="x")
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com")

        cls.src = Test.objects.create(
            name="Unit 1 MCQ", instructions="No calculators",
            duration_min=45, subject=cls.subject, program=cls.program,
            academic_year=cls.year, status=Test.Status.PUBLISHED,
            created_by=cls.owner,
        )
        TestQuestion.objects.create(
            test=cls.src, description="2+2?", type="MCQ",
            options=["3", "4"], answer_key="1", marks=Decimal("2"),
            sort_order=20)
        TestQuestion.objects.create(
            test=cls.src, description="Define a dart.", type="SHORT",
            answer_key="A fold", marks=Decimal("3"), sort_order=10)
        cls.src.total_marks = Decimal("5")
        cls.src.save()

        student = Student.objects.create(
            application_form_id="AF-1", student_name="Student 1",
            student_email="s1@example.com", gender="M", dob="2000-01-01",
            nationality="INDIAN", category="GENERAL", institute=inst,
            campus=campus, program=cls.program, academic_year=cls.year,
        )
        now = timezone.now()
        TestAttempt.objects.create(
            test=cls.src, student=student, start_dt=now,
            end_dt=now + timedelta(days=1))

    def setUp(self):
        self.client = APIClient()

    def _dup(self, user, **body):
        self.client.force_authenticate(user)
        return self.client.post(
            reverse("test-duplicate", args=[self.src.pk]), body,
            format="json")

    def test_owner_clones_questions_into_new_draft(self):
        r = self._dup(self.owner)
        self.assertEqual(r.status_code, 201, r.data)
        copy = Test.objects.get(pk=r.data["id"])
        self.assertNotEqual(copy.pk, self.src.pk)
        self.assertEqual(copy.name, "Unit 1 MCQ (copy)")
        self.assertEqual(copy.status, Test.Status.DRAFT)
        self.assertEqual(copy.instructions, "No calculators")
        self.assertEqual(copy.duration_min, 45)
        self.assertEqual(copy.subject_id, self.subject.pk)
        self.assertEqual(copy.program_id, self.program.pk)
        self.assertEqual(copy.academic_year_id, self.year.pk)
        self.assertEqual(copy.total_marks, Decimal("5"))
        self.assertEqual(copy.created_by_id, self.owner.pk)

        qs = list(copy.questions.order_by("sort_order"))
        self.assertEqual([q.description for q in qs],
                         ["Define a dart.", "2+2?"])
        self.assertEqual(qs[1].options, ["3", "4"])
        self.assertEqual(qs[1].answer_key, "1")
        self.assertEqual(qs[1].marks, Decimal("2"))
        self.assertEqual(r.data["question_count"], 2)

        # Attempts stay with the original; the copy starts clean.
        self.assertEqual(copy.attempts.count(), 0)
        self.src.refresh_from_db()
        self.assertEqual(self.src.attempts.count(), 1)
        self.assertEqual(self.src.status, Test.Status.PUBLISHED)
        self.assertEqual(self.src.questions.count(), 2)

    def test_overrides_name_program_and_year(self):
        r = self._dup(self.owner, name="Unit 1 MCQ – BD-2",
                      program=self.program2.pk, academic_year=self.year2.pk)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["name"], "Unit 1 MCQ – BD-2")
        self.assertEqual(r.data["program"], self.program2.pk)
        self.assertEqual(r.data["academic_year"], self.year2.pk)

    def test_blank_name_falls_back_to_copy_suffix(self):
        r = self._dup(self.owner, name="   ")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["name"], "Unit 1 MCQ (copy)")

    def test_null_clears_program_and_year(self):
        r = self._dup(self.owner, program=None, academic_year=None)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertIsNone(r.data["program"])
        self.assertIsNone(r.data["academic_year"])

    def test_any_status_can_be_duplicated(self):
        for st in (Test.Status.DRAFT, Test.Status.CLOSED):
            Test.objects.filter(pk=self.src.pk).update(status=st)
            r = self._dup(self.owner)
            self.assertEqual(r.status_code, 201, (st, r.data))

    def test_non_owner_without_publish_perm_is_forbidden(self):
        r = self._dup(self.other)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Test.objects.count(), 1)

    def test_superuser_copy_is_owned_by_clicker(self):
        r = self._dup(self.admin)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["created_by"], self.admin.pk)

    def test_unknown_test_404(self):
        self.client.force_authenticate(self.owner)
        r = self.client.post(reverse("test-duplicate", args=[999999]), {},
                             format="json")
        self.assertEqual(r.status_code, 404)
