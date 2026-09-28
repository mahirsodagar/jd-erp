"""Student Drop Out / Re-activate (legacy Student Search → Drop Out)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student, StudentStatusChange
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)

User = get_user_model()
S = Enrollment.Status


class DropoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem1 = Semester.objects.create(name="Sem 1", number=1)
        cls.sem2 = Semester.objects.create(name="Sem 2", number=2)
        cls.batch = Batch.objects.create(
            name="BD-1", program=cls.program, campus=cls.campus,
            academic_year=cls.year,
        )
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=cls.campus, program=cls.program,
            academic_year=cls.year,
        )
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.old = self._enroll(self.sem1, S.PROMOTED)
        self.live = self._enroll(self.sem2, S.ACTIVE)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _enroll(self, sem, status):
        return Enrollment.objects.create(
            student=self.student, program=self.program, semester=sem,
            campus=self.campus, batch=self.batch, academic_year=self.year,
            status=status,
        )

    def _post(self, name, remarks):
        return self.client.post(
            reverse(name, args=[self.student.pk]),
            {"remarks": remarks}, format="json",
        )

    def _statuses(self):
        self.old.refresh_from_db()
        self.live.refresh_from_db()
        return self.old.status, self.live.status

    def test_remarks_required(self):
        res = self._post("student-dropout", "  ")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._statuses(), (S.PROMOTED, S.ACTIVE))

    def test_dropout_drops_only_live_enrollments_and_logs(self):
        res = self._post("student-dropout", "Moved abroad")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self._statuses(), (S.PROMOTED, S.DROPPED))
        change = StudentStatusChange.objects.get()
        self.assertEqual(change.remarks, "Moved abroad")
        self.assertEqual(change.created_by, self.admin)

        detail = self.client.get(
            reverse("student-detail", args=[self.student.pk]))
        self.assertTrue(detail.data["is_dropout"])
        rows = self.client.get(reverse("student-list"),
                               {"status": "dropout"}).data
        self.assertEqual([r["id"] for r in rows], [self.student.pk])
        self.assertEqual(
            self.client.get(reverse("student-list"),
                            {"status": "active"}).data, [])

    def test_cannot_drop_twice(self):
        self._post("student-dropout", "Moved abroad")
        self.assertEqual(self._post("student-dropout", "Again").status_code,
                         400)

    def test_reactivate_restores_previous_status(self):
        self.live.status = S.PENDING
        self.live.save()
        self._post("student-dropout", "Fees issue")
        res = self._post("student-reactivate", "Fees cleared")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self._statuses(), (S.PROMOTED, S.PENDING))
        history = self.client.get(
            reverse("student-status-history", args=[self.student.pk])).data
        self.assertEqual([h["action"] for h in history],
                         ["REACTIVATE", "DROPOUT"])

    def test_reactivate_after_manual_drop(self):
        """Dropped from Edit Enrollment (no dropout record)."""
        self.live.status = S.DROPPED
        self.live.save()
        res = self._post("student-reactivate", "Back")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self._statuses(), (S.PROMOTED, S.ACTIVE))

    def test_reactivate_requires_dropout(self):
        self.assertEqual(self._post("student-reactivate", "x").status_code,
                         400)

    def test_permission_needed(self):
        staff = User.objects.create_user(
            username="staff", email="s@example.com", password="x")
        self.client.force_authenticate(staff)
        self.assertEqual(self._post("student-dropout", "x").status_code, 403)
