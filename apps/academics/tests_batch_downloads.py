"""Batch photo ZIP (Batch Report) + Shortage of Attendance letter
(Attendance Report → Batch-Wise)."""

import io
import shutil
import tempfile
import zipfile
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Attendance
from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA)
class BatchDownloadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JD School of Design",
                                             code="JDSD")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year,
        )
        ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=year,
        )
        subject = Subject.objects.create(name="Core", code="CORE")
        faculty = make_faculty(
            code="E1", name="Ann", campus=campus, institute=institute,
        )

        def student(app_id, name):
            s = Student.objects.create(
                application_form_id=app_id, student_name=name, gender="F",
                dob="2000-01-01", nationality="INDIAN", category="GENERAL",
                institute=institute, campus=campus, program=program,
                academic_year=year, father_name=f"{name} Sr",
                current_address="12 MG Road", current_pincode="560001",
            )
            Enrollment.objects.create(
                student=s, program=program, semester=sem, campus=campus,
                batch=cls.batch, academic_year=year,
                status=Enrollment.Status.ACTIVE,
            )
            return s

        cls.good = student("JD-1", "Asha Rao")
        cls.short = student("JD-2", "Ravi Kumar")
        # 4 classes: Asha attends all, Ravi 2/4 = 50%.
        for day in range(1, 5):
            slot, _ = create_slot(
                batch=cls.batch, subject=subject, instructor=faculty,
                classroom=None, time_slot=ts, date=date(2026, 7, day),
            )
            Attendance.objects.create(schedule_slot=slot, student=cls.good,
                                      status="PRESENT")
            Attendance.objects.create(
                schedule_slot=slot, student=cls.short,
                status="PRESENT" if day <= 2 else "ABSENT",
            )
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _letter(self, **params):
        return self.client.get(
            reverse("attendance-report-shortage-letter",
                    args=[self.batch.pk]), params)

    def test_letter_for_shortage_student(self):
        res = self._letter(student=self.short.pk)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertTrue(res.content.startswith(b"%PDF"))
        self.assertIn("JD-2", res["Content-Disposition"])

    def test_no_letter_above_threshold(self):
        self.assertEqual(self._letter(student=self.good.pk).status_code, 400)

    def test_bulk_letters(self):
        res = self._letter()
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b"%PDF"))

    def test_photos_zip_names_and_missing_list(self):
        self.good.photo.save("x.jpg", ContentFile(b"\xff\xd8fakejpeg"))
        res = self.client.get(reverse("batch-report-photos",
                                      args=[self.batch.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/zip")
        zf = zipfile.ZipFile(io.BytesIO(res.content))
        names = sorted(zf.namelist())
        self.assertEqual(names, ["JD-1_Asha_Rao.jpg", "missing.txt"])
        self.assertIn("Ravi Kumar", zf.read("missing.txt").decode())

    def test_photos_need_roster_permission(self):
        staff = get_user_model().objects.create_user(
            username="s", email="s@example.com", password="x")
        self.client.force_authenticate(staff)
        res = self.client.get(reverse("batch-report-photos",
                                      args=[self.batch.pk]))
        self.assertEqual(res.status_code, 403)
