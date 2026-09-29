"""Batch transfer — one student's live enrolment moved into another batch."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.admissions.models import BatchTransfer, Enrollment, Student, StudentRemark
from apps.admissions.services import transfer_enrollment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)


class BatchTransferTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD", code="JD")
        cls.main = Campus.objects.create(name="Main", code="MAIN")
        cls.north = Campus.objects.create(name="North", code="NORTH")
        cls.bdes = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.mdes = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.bdes_s1 = Semester.objects.create(program=cls.bdes, number=1, name="Sem 1")
        cls.bdes_s2 = Semester.objects.create(program=cls.bdes, number=2, name="Sem 2")
        cls.mdes_s1 = Semester.objects.create(program=cls.mdes, number=1, name="Sem 1")
        cls.a = Batch.objects.create(
            name="A", campus=cls.main, program=cls.bdes, academic_year=cls.year,
        )
        cls.b = Batch.objects.create(
            name="B", campus=cls.main, program=cls.bdes, academic_year=cls.year,
        )
        cls.m = Batch.objects.create(
            name="M", campus=cls.north, program=cls.mdes, academic_year=cls.year,
        )
        cls.student = Student.objects.create(
            student_name="Asha", gender="F", dob=date(2006, 1, 1),
            nationality="Indian", institute=cls.institute,
            campus=cls.main, program=cls.bdes, academic_year=cls.year,
            student_mobile="9000000000", student_email="asha@example.com",
        )

    def setUp(self):
        self.enr = Enrollment.objects.create(
            student=self.student, program=self.bdes, semester=self.bdes_s1,
            campus=self.main, batch=self.a, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )

    def _transfer(self, **kw):
        args = {
            "enrollment": self.enr, "target_batch": self.b,
            "target_semester": self.bdes_s1,
            "target_academic_year": self.year, "remarks": "Timing clash",
        }
        args.update(kw)
        return transfer_enrollment(**args)

    def test_updates_enrollment_in_place_and_logs(self):
        t = self._transfer()
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.batch, self.b)
        # No new enrolment row — the same admission continues.
        self.assertEqual(Enrollment.objects.filter(student=self.student).count(), 1)
        self.assertEqual(t.from_batch, self.a)
        self.assertEqual(t.to_batch, self.b)
        self.assertEqual(t.remarks, "Timing clash")
        self.assertTrue(StudentRemark.objects.filter(
            student=self.student, note__contains="A → B",
        ).exists())

    def test_cross_program_takes_program_and_campus_from_batch(self):
        self._transfer(target_batch=self.m, target_semester=self.mdes_s1)
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.program, self.mdes)
        self.assertEqual(self.enr.campus, self.north)
        self.student.refresh_from_db()
        self.assertEqual(self.student.program, self.mdes)
        self.assertEqual(self.student.campus, self.north)

    def test_rejects_semester_of_another_program(self):
        with self.assertRaisesMessage(ValueError, "Semester does not belong"):
            self._transfer(target_batch=self.m, target_semester=self.bdes_s1)

    def test_rejects_same_batch(self):
        with self.assertRaisesMessage(ValueError, "already in this batch"):
            self._transfer(target_batch=self.a)

    def test_rejects_non_live_enrollment(self):
        self.enr.status = Enrollment.Status.PROMOTED
        self.enr.save()
        with self.assertRaisesMessage(ValueError, "active or pending"):
            self._transfer()

    def test_requires_remarks(self):
        with self.assertRaisesMessage(ValueError, "Remarks are required"):
            self._transfer(remarks="  ")
        self.assertFalse(BatchTransfer.objects.exists())

    def test_api_round_trip(self):
        admin = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="x",
        )
        c = APIClient()
        c.force_authenticate(admin)
        r = c.post("/api/admissions/batch-transfer/", {
            "enrollment": self.enr.id, "target_batch": self.b.id,
            "target_semester": self.bdes_s2.id,
            "target_academic_year": self.year.id, "remarks": "Moved",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["to_batch_name"], "B")
        self.assertEqual(r.data["to_semester_name"], "Sem 2")

        r = c.get("/api/admissions/batch-transfer/", {"student": self.student.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
