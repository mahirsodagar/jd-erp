"""Slot-level attendance remarks ("Remarks if any (syllabus completed)").

Ports the legacy mark-attendance textarea: required the first time the
register is taken, optional when editing, stored on the slot
(timetable_pub.remarks → ScheduleSlot.notes) — academics/aget.php:2396.
"""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)


class AttendanceRemarksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1)
        batch = Batch.objects.create(
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
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=sem,
            campus=campus, batch=batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )
        cls.slot, _ = create_slot(
            batch=batch, subject=subject, instructor=faculty,
            classroom=None, time_slot=ts, date=date(2026, 7, 1),
        )
        # Superuser holds edit_frozen, so the 15-minute window is moot.
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = reverse("attendance-roster", args=[self.slot.pk])

    def _post(self, **extra):
        return self.client.post(self.url, {
            "marks": [{"student": self.student.id, "status": "PRESENT"}],
            **extra,
        }, format="json")

    def test_first_marking_requires_remarks(self):
        res = self._post()
        self.assertEqual(res.status_code, 400)
        self.assertIn("remarks", res.data)
        res = self._post(remarks="   ")
        self.assertEqual(res.status_code, 400)

    def test_remarks_saved_on_slot_and_returned(self):
        res = self._post(remarks="  Unit 1 done  ")
        self.assertEqual(res.status_code, 200, res.data)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.notes, "Unit 1 done")
        self.assertEqual(self.client.get(self.url).data["remarks"],
                         "Unit 1 done")

    def test_edit_keeps_or_updates_remarks(self):
        self._post(remarks="Unit 1 done")
        # Remarks optional once the register exists; omitted = unchanged.
        self.assertEqual(self._post().status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.notes, "Unit 1 done")
        self.assertEqual(self._post(remarks="Unit 2").status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.notes, "Unit 2")
