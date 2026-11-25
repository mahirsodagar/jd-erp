"""Attendance % counts the CURRENT batch only.

Client rule (2026-11-25): a student shifted to another batch or program
— by in-place transfer or by promotion — starts their attendance afresh.
Classes marked in the earlier batch stay on record but never enter a
student-level percentage: the staff student summary, the Student Wise
report, the portal dashboard tile and the portal per-subject report.
Batch-level reports were already scoped to their own batch.
"""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.attendance_reports import student_wise_report
from apps.academics.attendance_service import (
    current_batch, student_attendance_summary,
)
from apps.academics.models import Attendance, ScheduleSlot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.admissions.services import transfer_enrollment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)


class CurrentBatchAttendanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        cls.sem = Semester.objects.create(name="Sem 1", number=1, program=program)
        cls.old_batch = Batch.objects.create(
            name="BD-1", short_name="BD1", program=program, campus=campus,
            academic_year=year)
        cls.new_batch = Batch.objects.create(
            name="BD-2", short_name="BD2", program=program, campus=campus,
            academic_year=year)
        ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0))
        subject = Subject.objects.create(name="Core", code="CORE", program=program)
        faculty = make_faculty(code="E1", name="Ann", campus=campus,
                               institute=institute)
        cls.user = get_user_model().objects.create_user(
            username="stu", password="x", email="s@example.com")
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year, user_account=cls.user,
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, program=program, semester=cls.sem,
            campus=campus, batch=cls.old_batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

        def mark(batch, day, status):
            slot = ScheduleSlot.objects.create(
                batch=batch, subject=subject, instructor=faculty,
                time_slot=ts, date=day,
            )
            Attendance.objects.create(schedule_slot=slot, student=cls.student,
                                      status=status)

        # Old batch: 1 of 4 present (25%).
        for i, st in enumerate(["PRESENT", "ABSENT", "ABSENT", "ABSENT"]):
            mark(cls.old_batch, date(2026, 7, 1 + i), st)
        # New batch: 2 of 2 present (100%).
        for i in range(2):
            mark(cls.new_batch, date(2026, 8, 1 + i), "PRESENT")

        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com")

    def _transfer(self):
        transfer_enrollment(
            enrollment=self.enrollment, target_batch=self.new_batch,
            target_semester=self.sem,
            target_academic_year=self.enrollment.academic_year,
            remarks="Shifted on request", actor=self.admin,
        )

    def test_before_transfer_only_the_old_batch_counts(self):
        self.assertEqual(current_batch(self.student), self.old_batch)
        s = student_attendance_summary(student=self.student)
        self.assertEqual((s["marked"], s["PRESENT"]), (4, 1))
        self.assertEqual(s["present_pct"], 25.0)
        self.assertEqual(s["batch_name"], "BD1")

    def test_after_transfer_old_batch_is_dropped_from_every_percentage(self):
        self._transfer()
        self.assertEqual(current_batch(self.student), self.new_batch)

        s = student_attendance_summary(student=self.student)
        self.assertEqual((s["marked"], s["PRESENT"]), (2, 2))
        self.assertEqual(s["present_pct"], 100.0)
        self.assertEqual(s["batch_name"], "BD2")
        self.assertEqual({x["batch"] for x in s["sessions"]}, {"BD2"})

        w = student_wise_report(student=self.student)
        self.assertEqual(w["totals"], {"present": 2, "total": 2, "pct": 100.0})
        self.assertEqual(w["batch_name"], "BD2")

        c = APIClient()
        c.force_authenticate(self.user)
        r = c.get(reverse("portal-dashboard"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["attendance_percent"], 100)
        r = c.get(reverse("portal-attendance-report"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["totals"]["total"], 2)
        self.assertEqual(r.data["totals"]["percentage"], 100.0)

    def test_promotion_style_new_enrollment_also_resets(self):
        """A new ACTIVE enrolment row in the new batch, old row PROMOTED."""
        self.enrollment.status = Enrollment.Status.PROMOTED
        self.enrollment.save(update_fields=["status"])
        Enrollment.objects.create(
            student=self.student, program=self.enrollment.program,
            semester=self.sem, campus=self.enrollment.campus,
            batch=self.new_batch, academic_year=self.enrollment.academic_year,
            status=Enrollment.Status.ACTIVE,
        )
        s = student_attendance_summary(student=self.student)
        self.assertEqual(s["present_pct"], 100.0)

    def test_old_batch_rows_are_kept_for_batch_reports(self):
        """The rule hides old rows from the student's %, it does not
        delete them — the old batch's own register is intact."""
        self._transfer()
        self.assertEqual(
            Attendance.objects.filter(schedule_slot__batch=self.old_batch,
                                      student=self.student).count(), 4)
