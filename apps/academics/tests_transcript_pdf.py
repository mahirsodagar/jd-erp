"""Academic Transcript + Marks Card (port of legacy aget.php grading)."""

from datetime import date, time
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Attendance, MarksEntry, ScheduleSlot
from apps.academics.tests_electives import make_faculty
from apps.academics.transcript_pdf import (
    MARKS_CARD_SCALE, TRANSCRIPT_SCALE, grade_for, marks_card_document,
    render_marks_card_pdf, render_transcript_pdf, transcript_document,
)
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)


class TranscriptPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN", city="Bangalore")
        program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem1 = Semester.objects.create(name="Sem 1", number=1, program=program)
        cls.sem2 = Semester.objects.create(name="Sem 2", number=2, program=program)
        cls.batch = Batch.objects.create(
            name="BD-1", short_name="BD1", program=program, campus=campus,
            academic_year=year,
        )
        ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=year,
        )
        cls.core = Subject.objects.create(name="Core", code="CORE", program=program)
        cls.draw = Subject.objects.create(name="Drawing", code="DRAW", program=program)
        cls.noatt = Subject.objects.create(name="Theory", code="THEO", program=program)
        faculty = make_faculty(code="E1", name="Ann", campus=campus,
                               institute=institute)
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=cls.sem1,
            campus=campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )
        # 4 of 5 classes present in CORE -> 16 of the 20 attendance marks.
        for i, st in enumerate(["PRESENT", "PRESENT", "PRESENT", "LATE", "ABSENT"]):
            slot = ScheduleSlot.objects.create(
                batch=cls.batch, subject=cls.core, instructor=faculty,
                time_slot=ts, date=date(2026, 7, 1 + i),
            )
            Attendance.objects.create(schedule_slot=slot, student=cls.student,
                                      status=st)
        # DRAW: 1 of 1 present.
        slot = ScheduleSlot.objects.create(
            batch=cls.batch, subject=cls.draw, instructor=faculty,
            time_slot=ts, date=date(2026, 7, 10),
        )
        Attendance.objects.create(schedule_slot=slot, student=cls.student,
                                  status="PRESENT")

        def marks(subject, sem, ia, ea, published=True):
            return MarksEntry.objects.create(
                student=cls.student, subject=subject, batch=cls.batch,
                semester=sem, ia_marks=ia, ea_marks=ea,
                ia_max=D(40), ea_max=D(40), published=published,
            )

        marks(cls.core, cls.sem1, D(30), D(32))     # 30 + 32 + 16 = 78
        marks(cls.draw, cls.sem2, D(40), D(40))     # 40 + 40 + 20 = 100
        marks(cls.noatt, cls.sem1, D(20), D(20))    # no attendance -> NA
        marks(cls.core, cls.sem2, D(10), D(10), published=False)  # draft

        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )
        cls.outsider = get_user_model().objects.create_user(
            username="nobody", password="x", email="n@example.com",
        )

    # --- grading ---------------------------------------------------------

    def test_grade_bands_match_legacy(self):
        self.assertEqual(grade_for(78, TRANSCRIPT_SCALE), "C")
        self.assertEqual(grade_for(78, MARKS_CARD_SCALE), "A")
        self.assertEqual(grade_for(100, TRANSCRIPT_SCALE), "A")
        self.assertEqual(grade_for(49, TRANSCRIPT_SCALE), "F")
        self.assertEqual(grade_for(44, MARKS_CARD_SCALE), "F")
        self.assertEqual(grade_for(None, MARKS_CARD_SCALE), "NA")

    def test_transcript_document_groups_by_semester_published_only(self):
        doc = transcript_document(self.student)
        self.assertEqual(doc["program_name"], "B.Des")
        self.assertEqual(doc["campus_name"], "Bangalore")
        self.assertEqual(doc["registration_no"], "AF-1")
        self.assertEqual([s["semester_number"] for s in doc["semesters"]], [1, 2])
        sem1 = {r["subject_code"]: r for r in doc["semesters"][0]["rows"]}
        self.assertEqual(sem1["CORE"]["score"], 78)
        self.assertEqual(sem1["CORE"]["grade"], "C")
        self.assertIsNone(sem1["THEO"]["score"])
        self.assertEqual(sem1["THEO"]["grade"], "NA")
        sem2 = doc["semesters"][1]["rows"]
        self.assertEqual([(r["subject_code"], r["grade"]) for r in sem2],
                         [("DRAW", "A")])  # the draft CORE row is excluded

    def test_marks_card_document_is_flat_with_attendance(self):
        doc = marks_card_document(self.student)
        self.assertEqual(doc["batch_name"], "BD1")
        self.assertEqual(doc["academic_year"], "26-27")
        grades = {r["subject_code"]: r["grade"] for r in doc["rows"]}
        self.assertEqual(grades, {"CORE": "A", "THEO": "NA", "DRAW": "A+"})
        # 4/5 in CORE + 1/1 in DRAW, THEO counts nothing -> 5/6 = 83%
        self.assertEqual(doc["attendance_pct"], 83)

    def test_pdfs_render(self):
        for pdf in (render_transcript_pdf(self.student),
                    render_marks_card_pdf(self.student)):
            self.assertTrue(pdf.startswith(b"%PDF"))

    # --- endpoints -------------------------------------------------------

    def test_endpoints_serve_pdf_to_staff_and_hide_from_outsiders(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        for name in ("transcript-student-pdf", "marks-card-student-pdf"):
            r = c.get(reverse(name, args=[self.student.pk]))
            self.assertEqual(r.status_code, 200, name)
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF"))
        c.force_authenticate(self.outsider)
        r = c.get(reverse("transcript-student-pdf", args=[self.student.pk]))
        self.assertEqual(r.status_code, 404)

    def test_me_endpoints_need_a_linked_student(self):
        c = APIClient()
        c.force_authenticate(self.outsider)
        self.assertEqual(c.get(reverse("transcript-me-pdf")).status_code, 400)
        self.student.user_account = self.outsider
        self.student.save(update_fields=["user_account"])
        r = c.get(reverse("marks-card-me-pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))
