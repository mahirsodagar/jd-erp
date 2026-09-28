"""Batch-wise IA/EA marks sheet (port of legacy academics/marksentry.php)."""

from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.academics.marks_service import (
    build_transcript, marks_sheet, save_marks_sheet,
    set_marks_sheet_published,
)
from apps.academics.models import MarksEntry
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
)


class MarksSheetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.other_program = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(name="Sem 1", number=1,
                                          program=cls.program)
        cls.batch = Batch.objects.create(
            name="BD-1", program=cls.program, campus=cls.campus,
            academic_year=cls.year,
        )
        cls.core = Subject.objects.create(name="Core", code="CORE",
                                          program=cls.program)
        cls.elective = Subject.objects.create(
            name="Textiles", code="ELEA", is_elective=True, program=cls.program,
        )
        cls.foreign = Subject.objects.create(name="Other", code="OTH",
                                             program=cls.other_program)

        def student(name, electives="", status=Enrollment.Status.ACTIVE):
            s = Student.objects.create(
                application_form_id=f"AF-{name}", student_name=name,
                gender="M", dob="2000-01-01", nationality="INDIAN",
                category="GENERAL", institute=cls.institute,
                campus=cls.campus, program=cls.program,
                academic_year=cls.year,
            )
            Enrollment.objects.create(
                student=s, program=cls.program, semester=cls.sem,
                campus=cls.campus, batch=cls.batch, academic_year=cls.year,
                status=status, elective_subjects=electives,
            )
            return s

        cls.ann = student("Ann", str(cls.elective.id))
        cls.bob = student("Bob")
        cls.gone = student("Gone", status=Enrollment.Status.DROPPED)
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def _save(self, rows, **kw):
        return save_marks_sheet(
            batch=self.batch, semester=self.sem,
            subject=kw.pop("subject", self.core),
            ia_max=D(20), ea_max=D(80), rows=rows, entered_by=self.admin,
            can_edit_published=kw.pop("can_edit_published", False),
            publish=kw.pop("publish", False),
        )

    def test_roster_is_active_students_and_electives_narrow(self):
        names = [r["name"] for r in marks_sheet(
            batch=self.batch, semester=self.sem, subject=self.core)["rows"]]
        self.assertEqual(names, ["Ann", "Bob"])
        names = [r["name"] for r in marks_sheet(
            batch=self.batch, semester=self.sem, subject=self.elective)["rows"]]
        self.assertEqual(names, ["Ann"])

    def test_new_sheet_defaults_to_legacy_40_40(self):
        sh = marks_sheet(batch=self.batch, semester=self.sem, subject=self.core)
        self.assertEqual((sh["ia_max"], sh["ea_max"]), ("40", "40"))

    def test_save_whole_batch_and_blank_rows_create_nothing(self):
        out = self._save([
            {"student": self.ann.id, "ia_marks": D(15), "ea_marks": D(60)},
            {"student": self.bob.id, "ia_marks": None, "ea_marks": None},
        ])
        self.assertEqual(out["saved"], 1)
        m = MarksEntry.objects.get(student=self.ann)
        self.assertEqual((m.ia_marks, m.ea_marks, m.batch_id),
                         (D(15), D(60), self.batch.id))
        self.assertFalse(MarksEntry.objects.filter(student=self.bob).exists())

    def test_out_of_range_saves_nothing(self):
        with self.assertRaises(ValueError) as cm:
            self._save([
                {"student": self.ann.id, "ia_marks": D(15), "ea_marks": D(60)},
                {"student": self.bob.id, "ia_marks": D(21), "ea_marks": None},
            ])
        self.assertIn(self.bob.id, cm.exception.args[0])
        self.assertFalse(MarksEntry.objects.exists())

    def test_student_outside_roster_is_skipped(self):
        out = self._save([{"student": self.gone.id, "ia_marks": D(5)}])
        self.assertEqual(out["saved"], 0)
        self.assertEqual(out["skipped"][0]["reason"], "not in batch roster")

    def test_publish_gates_transcript_and_locks_rows(self):
        self._save([{"student": self.ann.id, "ia_marks": D(15),
                     "ea_marks": D(60)}], publish=True)
        self.assertEqual(len(build_transcript(student=self.ann)["semesters"]), 1)

        out = self._save([{"student": self.ann.id, "ia_marks": D(1),
                           "ea_marks": D(1)}])
        self.assertEqual(out["skipped"][0]["reason"], "published")
        self.assertEqual(MarksEntry.objects.get(student=self.ann).ia_marks, D(15))

        set_marks_sheet_published(batch=self.batch, semester=self.sem,
                                  subject=self.core, publish=False,
                                  by_user=self.admin)
        self.assertEqual(build_transcript(student=self.ann)["semesters"], [])

    def test_api_rejects_subject_from_another_program(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.get("/api/academics/marks/sheet/", {
            "batch": self.batch.id, "semester": self.sem.id,
            "subject": self.foreign.id,
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("subject", r.data)

    def test_api_round_trip(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        r = c.post("/api/academics/marks/sheet/", {
            "batch": self.batch.id, "semester": self.sem.id,
            "subject": self.core.id, "ia_max": "20", "ea_max": "80",
            "rows": [{"student": self.bob.id, "ia_marks": "99",
                      "ea_marks": None}],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn(str(self.bob.id), r.data["row_errors"])

        r = c.post("/api/academics/marks/sheet/", {
            "batch": self.batch.id, "semester": self.sem.id,
            "subject": self.core.id, "ia_max": "20", "ea_max": "80",
            "rows": [{"student": self.bob.id, "ia_marks": "12.5",
                      "ea_marks": "70"}],
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = c.get("/api/academics/marks/sheet/", {
            "batch": self.batch.id, "semester": self.sem.id,
            "subject": self.core.id,
        })
        bob = next(x for x in r.data["rows"] if x["student_id"] == self.bob.id)
        self.assertEqual((bob["ia_marks"], bob["ea_marks"]), ("12.5", "70.0"))
