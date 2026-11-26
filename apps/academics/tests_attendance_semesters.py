"""Semester → subject attendance breakdown (client, 2026-11-26), the
legacy "Advanced Student Search" layout, on the staff student report and
the student portal report."""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Attendance, ScheduleSlot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)


class SemesterBreakdownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        sem1 = Semester.objects.create(name="Semester 1", number=1, program=program)
        sem2 = Semester.objects.create(name="Semester 2", number=2, program=program)
        cls.batch = Batch.objects.create(
            name="BD-1", short_name="BD1", program=program, campus=campus,
            academic_year=year)
        other_batch = Batch.objects.create(
            name="BD-9", program=program, campus=campus, academic_year=year)
        ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0))
        ts2 = TimeSlot.objects.create(
            label="Slot 2", start_time=time(10, 0), end_time=time(11, 0))
        s1 = Subject.objects.create(name="Drawing", code="DRW", program=program, semester=sem1)
        s2 = Subject.objects.create(name="History", code="HIS", program=program, semester=sem1)
        s3 = Subject.objects.create(name="Draping", code="DRP", program=program, semester=sem2)
        s0 = Subject.objects.create(name="Orientation", code="ORI", program=program)
        faculty = make_faculty(code="E1", name="Ann", campus=campus, institute=institute)
        cls.user = get_user_model().objects.create_user(
            username="stu", password="x", email="s@example.com")
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year, user_account=cls.user,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=sem1,
            campus=campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

        def slot(subject, day, batch=None, status=ScheduleSlot.Status.SCHEDULED, t=ts):
            return ScheduleSlot.objects.create(
                batch=batch or cls.batch, subject=subject, instructor=faculty,
                time_slot=t, date=day, status=status)

        def mark(subject, day, status, t=ts):
            Attendance.objects.create(
                schedule_slot=slot(subject, day, t=t), student=cls.student, status=status)

        # Drawing (sem 1): P, A, L, + one held but unmarked class.
        mark(s1, date(2026, 7, 1), "PRESENT")
        mark(s1, date(2026, 7, 2), "ABSENT")
        mark(s1, date(2026, 7, 3), "LATE")
        slot(s1, date(2026, 7, 4))
        # A cancelled Drawing class must not count as held.
        slot(s1, date(2026, 7, 5), status=ScheduleSlot.Status.CANCELLED)
        # History (sem 1): A, A.
        mark(s2, date(2026, 7, 1), "ABSENT", t=ts2)
        mark(s2, date(2026, 7, 8), "ABSENT", t=ts2)
        # Draping (sem 2): P.
        mark(s3, date(2026, 9, 1), "PRESENT")
        # Orientation has no semester: P.
        mark(s0, date(2026, 6, 15), "PRESENT")
        # Another batch's class — never counted for this student.
        Attendance.objects.create(
            schedule_slot=slot(s1, date(2026, 7, 20), batch=other_batch),
            student=cls.student, status="ABSENT")

        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com")

    def _report(self, user, **params):
        c = APIClient()
        c.force_authenticate(user)
        r = c.get(reverse("attendance-student-report", args=[self.student.pk]), params)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_grouped_by_subject_semester_with_unassigned_last(self):
        sems = self._report(self.admin)["semesters"]
        self.assertEqual([g["semester_name"] for g in sems],
                         ["Semester 1", "Semester 2", "Unassigned semester"])
        sem1 = sems[0]
        self.assertEqual([r["subject_code"] for r in sem1["subjects"]], ["DRW", "HIS"])
        drawing = sem1["subjects"][0]
        self.assertEqual(
            {k: drawing[k] for k in ("held", "marked", "present", "absent", "late", "unmarked")},
            {"held": 4, "marked": 3, "present": 1, "absent": 1, "late": 1, "unmarked": 1})
        # Late counts as present: (1 + 1) / 3.
        self.assertEqual(drawing["percentage"], 66.7)
        self.assertEqual(drawing["absent_dates"], ["2026-07-02"])
        self.assertEqual(drawing["late_dates"], ["2026-07-03"])
        self.assertEqual(sem1["totals"]["marked"], 5)
        self.assertEqual(sem1["totals"]["percentage"], 40.0)
        self.assertEqual(sems[1]["subjects"][0]["subject_code"], "DRP")

    def test_other_batch_rows_are_excluded(self):
        sems = self._report(self.admin)["semesters"]
        drawing = sems[0]["subjects"][0]
        self.assertNotIn("2026-07-20", drawing["absent_dates"])

    def test_date_range_narrows_the_tables(self):
        sems = self._report(self.admin, **{"from": "2026-09-01"})["semesters"]
        self.assertEqual([g["semester_name"] for g in sems], ["Semester 2"])

    def test_portal_report_carries_the_same_breakdown(self):
        c = APIClient()
        c.force_authenticate(self.user)
        r = c.get("/api/portal/attendance/report/")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual([g["semester_name"] for g in body["semesters"]],
                         ["Semester 1", "Semester 2", "Unassigned semester"])
        # Flat subject list + totals kept for the dashboard tiles.
        self.assertEqual([s["subject_code"] for s in body["subjects"]],
                         ["DRP", "DRW", "HIS", "ORI"])
        self.assertEqual(body["totals"]["total"], 7)
        self.assertEqual(body["totals"]["percentage"], 57.1)
