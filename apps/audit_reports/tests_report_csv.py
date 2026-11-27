"""`?output=csv` on the Student Feedback and Faculty Feedback (self-
appraisal) lists — the same rows the page shows, as a download."""

import csv
import io
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Student
from apps.audit_reports.models import (
    CourseEndReport, FacultySelfAppraisal, StudentFeedback, ZeroHourReport,
)
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject,
)


def _rows(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


class ReportCsvTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        batch = Batch.objects.create(name="BD-1", program=program, campus=campus,
                                     academic_year=year)
        subject = Subject.objects.create(name="Drawing", code="DRAW", program=program)
        cls.fac1 = make_faculty(code="E1", name="Ann", campus=campus, institute=inst)
        cls.fac2 = make_faculty(code="E2", name="Bob", campus=campus, institute=inst)

        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com")
        cls.stu_user = User.objects.create_user(
            username="stu", password="x", email="s@example.com")
        cls.s1 = Student.objects.create(
            application_form_id="AF-1", student_name="Riya", gender="F",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=inst, campus=campus, program=program, academic_year=year,
            user_account=cls.stu_user)
        s2 = Student.objects.create(
            application_form_id="AF-2", student_name="Zed", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=inst, campus=campus, program=program, academic_year=year)
        for s, fac, overall, worked in ((cls.s1, cls.fac1, 5, "Clear, well paced"),
                                        (s2, cls.fac2, 3, "")):
            StudentFeedback.objects.create(
                student=s, subject=subject, instructor=fac, batch=batch,
                type="MIDWAY", rating_overall=overall, rating_clarity=4,
                rating_engagement=4, rating_responsiveness=4, what_worked=worked)

        FacultySelfAppraisal.objects.create(
            faculty=cls.fac1, year=2026, quarter=2, achievements="Ran a workshop",
            green_flags="Mentoring", red_flags="")
        FacultySelfAppraisal.objects.create(
            faculty=cls.fac2, year=2025, quarter=4, achievements="Old")

        cls.batch = batch
        CourseEndReport.objects.create(
            instructor=cls.fac1, subject=subject, batch=batch,
            completed_on=date(2026, 10, 30), summary="Module wrapped up",
            learning_outcomes="Sketching", avg_attendance_pct="88.50",
            hod_status="APPROVED", hod_remarks="Good")
        CourseEndReport.objects.create(
            instructor=cls.fac2, subject=subject, batch=batch,
            completed_on=date(2026, 9, 1), summary="Earlier module")

        ZeroHourReport.objects.create(
            report_date=date(2026, 11, 3), batch=batch, mentor=cls.fac1,
            batch_strength=30, zero_hour_attendance=27,
            avg_attendance_first_half="90.00", agenda="Portfolio review",
            submitted_by=cls.admin)
        ZeroHourReport.objects.create(
            report_date=date(2026, 10, 6), batch=batch, mentor=cls.fac2,
            batch_strength=30, zero_hour_attendance=20, agenda="Intro",
            submitted_by=cls.admin)

    def test_student_feedback_csv_for_auditor(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.get(reverse("student-feedback-list-create"), {"output": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn('filename="Student_Feedback.csv"', r["Content-Disposition"])
        rows = _rows(r)
        self.assertEqual(rows[0][:4], ["Date", "Type", "Student", "Form No"])
        self.assertEqual(len(rows), 3)
        by_student = {row[2]: row for row in rows[1:]}
        self.assertEqual(by_student["Riya"][1], "Mid-course")
        self.assertEqual(by_student["Riya"][4:6], ["Ann", "E1"])
        self.assertEqual(by_student["Riya"][6:9], ["Drawing (DRAW)", "BD-1", "5"])
        self.assertEqual(by_student["Riya"][12], "Clear, well paced")
        # Filters apply to the download as they do to the list.
        r = c.get(reverse("student-feedback-list-create"),
                  {"output": "csv", "instructor": self.fac2.pk})
        self.assertEqual([row[2] for row in _rows(r)[1:]], ["Zed"])

    def test_student_feedback_csv_is_own_rows_for_a_student(self):
        c = APIClient()
        c.force_authenticate(self.stu_user)
        rows = _rows(c.get(reverse("student-feedback-list-create"), {"output": "csv"}))
        self.assertEqual([row[2] for row in rows[1:]], ["Riya"])

    def test_course_end_csv(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.get(reverse("course-end-list-create"), {"output": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="Module_End_Reports.csv"', r["Content-Disposition"])
        rows = _rows(r)
        self.assertEqual(rows[0][:6],
                         ["Completed on", "Program", "Batch", "Subject", "Type",
                          "Instructor"])
        self.assertEqual([row[5] for row in rows[1:]], ["Ann", "Bob"])  # newest first
        self.assertEqual(rows[1][:5],
                         ["30-10-2026", "B.Des", "BD-1", "Drawing (DRAW)", "End Module"])
        self.assertEqual(rows[1][7:10], ["88.50", "", "Module wrapped up"])
        self.assertEqual(rows[1][13:15], ["Approved", "Good"])
        r = c.get(reverse("course-end-list-create"),
                  {"output": "csv", "hod_status": "PENDING"})
        self.assertEqual([row[5] for row in _rows(r)[1:]], ["Bob"])

    def test_zero_hour_csv_is_every_row_not_one_page(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.get(reverse("zero-hour-list-create"), {"output": "csv", "page_size": 1})
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="0-Hour_Reports.csv"', r["Content-Disposition"])
        rows = _rows(r)
        self.assertEqual(rows[0][:5], ["Date", "Campus", "Program", "Class / Batch", "Mentor"])
        self.assertEqual(len(rows), 3)  # page_size ignored for the download
        self.assertEqual(rows[1][:7],
                         ["03-11-2026", "Main", "B.Des", "BD-1", "Ann", "30", "27"])
        self.assertEqual(rows[1][7:10], ["90.00", "", "Portfolio review"])
        r = c.get(reverse("zero-hour-list-create"),
                  {"output": "csv", "from": "2026-11-01"})
        self.assertEqual([row[4] for row in _rows(r)[1:]], ["Ann"])

    def test_faculty_feedback_csv(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.get(reverse("self-appraisal-list-create"), {"output": "csv"})
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="Faculty_Feedback.csv"', r["Content-Disposition"])
        rows = _rows(r)
        self.assertEqual(rows[0][:4], ["Emp Code", "Faculty", "Year", "Quarter"])
        self.assertEqual([row[0] for row in rows[1:]], ["E1", "E2"])  # newest year first
        self.assertEqual(rows[1][2:5], ["2026", "Q2 (Jul-Sep)", "Ran a workshop"])
        self.assertEqual(rows[1][7], "Mentoring")
        r = c.get(reverse("self-appraisal-list-create"), {"output": "csv", "year": 2025})
        self.assertEqual([row[0] for row in _rows(r)[1:]], ["E2"])
