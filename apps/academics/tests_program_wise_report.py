"""Program Wise attendance report: one row per batch of a program with
strength, classes held / marked, overall % and the below-75% count."""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
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


class ProgramWiseReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        other = Program.objects.create(
            name="M.Des", code="MDES", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1)
        cls.b1 = Batch.objects.create(
            name="BD-1", program=cls.program, campus=campus, academic_year=year,
        )
        cls.b2 = Batch.objects.create(
            name="BD-2", program=cls.program, campus=campus, academic_year=year,
        )
        Batch.objects.create(  # other program — must not appear
            name="MD-1", program=other, campus=campus, academic_year=year,
        )
        ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=year,
        )
        subject = Subject.objects.create(name="Core", code="CORE")
        faculty = make_faculty(
            code="E1", name="Ann", campus=campus, institute=institute,
        )

        def student(i, batch):
            s = Student.objects.create(
                application_form_id=f"AF-{i}", student_name=f"S{i}",
                gender="M", dob="2000-01-01", nationality="INDIAN",
                category="GENERAL", institute=institute, campus=campus,
                program=cls.program, academic_year=year,
            )
            Enrollment.objects.create(
                student=s, program=cls.program, semester=sem,
                campus=campus, batch=batch, academic_year=year,
                status=Enrollment.Status.ACTIVE,
            )
            return s

        s1, s2 = student(1, cls.b1), student(2, cls.b1)
        student(3, cls.b2)

        # Batch 1: two slots, one marked. s1 present, s2 absent → s2 < 75%.
        slot_a, _ = create_slot(
            batch=cls.b1, subject=subject, instructor=faculty,
            classroom=None, time_slot=ts, date=date(2026, 7, 1),
        )
        create_slot(
            batch=cls.b1, subject=subject, instructor=faculty,
            classroom=None, time_slot=ts, date=date(2026, 7, 2),
        )
        Attendance.objects.create(schedule_slot=slot_a, student=s1,
                                  status="PRESENT")
        Attendance.objects.create(schedule_slot=slot_a, student=s2,
                                  status="ABSENT")

        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_rows_per_batch_with_totals(self):
        res = self.client.get(
            reverse("attendance-report-program", args=[self.program.pk]))
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertEqual(d["program_code"], "BDES")
        self.assertEqual([r["batch_name"] for r in d["rows"]], ["BD-1", "BD-2"])

        r1 = d["rows"][0]
        self.assertEqual(r1["students"], 2)
        self.assertEqual(r1["slots_held"], 2)
        self.assertEqual(r1["slots_marked"], 1)
        self.assertEqual((r1["present"], r1["marked"]), (1, 2))
        self.assertEqual(r1["pct"], 50.0)
        self.assertEqual(r1["shortage_count"], 1)

        r2 = d["rows"][1]
        self.assertEqual(r2["students"], 1)
        self.assertEqual(r2["slots_held"], 0)
        self.assertEqual(r2["pct"], 0.0)
        self.assertEqual(r2["shortage_count"], 0)

        t = d["totals"]
        self.assertEqual(t["batches"], 2)
        self.assertEqual(t["students"], 3)
        self.assertEqual((t["present"], t["marked"]), (1, 2))
        self.assertEqual(t["shortage_count"], 1)

    def test_date_range_excludes_slots(self):
        res = self.client.get(
            reverse("attendance-report-program", args=[self.program.pk]),
            {"from": "2026-07-02"},
        )
        r1 = res.json()["rows"][0]
        self.assertEqual(r1["slots_held"], 1)
        self.assertEqual(r1["marked"], 0)

    def test_unknown_program_404(self):
        res = self.client.get(reverse("attendance-report-program", args=[9999]))
        self.assertEqual(res.status_code, 404)

    def test_requires_report_permission(self):
        plain = get_user_model().objects.create_user(
            username="plain", password="x", email="p@example.com")
        self.client.force_authenticate(plain)
        res = self.client.get(
            reverse("attendance-report-program", args=[self.program.pk]))
        self.assertEqual(res.status_code, 403)
