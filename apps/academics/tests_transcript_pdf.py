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


def _pdf_text(pdf: bytes) -> str:
    """Inflate every content stream and return the raw text operators,
    enough to assert on the words a page carries."""
    import re
    import zlib
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except zlib.error:
            pass
    return "\n".join(out)


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
        # 4 of 5 classes present in CORE -> 80% attendance (shown, not
        # scored: marks are IA + EA only since 2026-11-24).
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

        marks(cls.core, cls.sem1, D(30), D(32))     # 62 / 80 = 77.5 -> 78
        marks(cls.draw, cls.sem2, D(40), D(40))     # 80 / 80 = 100
        marks(cls.noatt, cls.sem1, D(20), D(20))    # 40 / 80 = 50, no attendance
        marks(cls.core, cls.sem2, None, D(10), published=True)  # EA only -> NA
        marks(cls.draw, cls.sem1, D(10), D(10), published=False)  # draft

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
        # Marks only: 62/80 -> 78 -> C. Attendance rides alongside as a %.
        self.assertEqual(sem1["CORE"]["score"], 78)
        self.assertEqual(sem1["CORE"]["grade"], "C")
        self.assertEqual(sem1["CORE"]["attendance_pct"], 80)
        # No attendance on file no longer blocks the grade.
        self.assertEqual(sem1["THEO"]["score"], 50)
        self.assertEqual(sem1["THEO"]["grade"], "E")
        self.assertIsNone(sem1["THEO"]["attendance_pct"])
        self.assertNotIn("DRAW", sem1)  # the draft row is excluded
        sem2 = {r["subject_code"]: r for r in doc["semesters"][1]["rows"]}
        self.assertEqual(sem2["DRAW"]["grade"], "A")
        self.assertEqual(sem2["DRAW"]["attendance_pct"], 100)
        # A missing IA still grades NA — that is missing marks, not
        # missing attendance.
        self.assertIsNone(sem2["CORE"]["score"])
        self.assertEqual(sem2["CORE"]["grade"], "NA")

    def test_marks_card_document_is_flat_with_attendance(self):
        doc = marks_card_document(self.student)
        self.assertEqual(doc["batch_name"], "BD1")
        self.assertEqual(doc["academic_year"], "26-27")
        rows = {(r["subject_code"], r["grade"]) for r in doc["rows"]}
        self.assertEqual(rows, {("CORE", "A"), ("THEO", "C"), ("DRAW", "A+"),
                                ("CORE", "NA")})
        # Overall: 4/5 in CORE (counted once although CORE has two rows)
        # + 1/1 in DRAW, THEO contributes nothing -> 5/6 = 83%
        self.assertEqual(doc["attendance_pct"], 83)

    def test_attendance_prints_as_percentage_not_marks(self):
        for pdf in (render_transcript_pdf(self.student),
                    render_marks_card_pdf(self.student)):
            text = _pdf_text(pdf)
            self.assertIn("Attendance", text)
            self.assertIn("80%", text)
            self.assertIn("100%", text)

    def test_pdfs_render(self):
        for pdf in (render_transcript_pdf(self.student),
                    render_marks_card_pdf(self.student)):
            self.assertTrue(pdf.startswith(b"%PDF"))

    def test_transcript_uses_the_framed_template(self):
        """234 x 321 mm sheet, one page for two semesters, and the
        template's title / signature block text present."""
        pdf = render_transcript_pdf(self.student)
        # fpdf2 writes the MediaBox in points: 234mm = 663.31pt, 321mm = 909.92pt.
        self.assertIn(b"/MediaBox [0 0 663.31 909.92]", pdf)
        self.assertEqual(pdf.count(b"/Type /Page\n"), 1)
        text = _pdf_text(pdf)
        for needle in ("ACADEMIC ASSESSMENT RECORD", "B.DES", "SEMESTER 1",
                       "SEMESTER 2", "GRADE SYSTEM", "Scrutinised by",
                       "Principal", "Bangalore"):
            self.assertIn(needle, text, needle)

    def test_transcript_overflows_onto_a_second_page(self):
        """Many semesters push the tables past the fixed bottom block,
        which then moves to a continuation page."""
        for n in range(3, 12):
            sem = Semester.objects.create(name=f"Sem {n}", number=n,
                                          program=self.core.program)
            for k in range(4):
                subj = Subject.objects.create(
                    name=f"S{n}-{k}", code=f"S{n}{k}", program=self.core.program)
                MarksEntry.objects.create(
                    student=self.student, subject=subj, batch=self.batch,
                    semester=sem, ia_marks=D(30), ea_marks=D(30),
                    ia_max=D(40), ea_max=D(40), published=True)
        pdf = render_transcript_pdf(self.student)
        self.assertGreaterEqual(pdf.count(b"/Type /Page\n"), 2)
        text = _pdf_text(pdf)
        self.assertIn("SEMESTER 11", text)
        self.assertIn("GRADE SYSTEM", text)

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
