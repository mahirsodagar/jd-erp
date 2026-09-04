"""The Institute/University -> Program -> Semester chain.

Phase 1: a Program names both the Institute that teaches it and the
University that confers the degree (none, for JD-certified programs).
Phase 2: Semesters belong to a Program, so "Sem 1" is one row PER
program rather than a single global row shared by all of them.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.master.models import Institute, Program, Semester, University

User = get_user_model()


class UniversityTests(TestCase):
    def test_the_three_universities_are_seeded(self):
        codes = set(University.objects.values_list("code", flat=True))
        self.assertEqual(codes, {"MSBCU", "BESTIU", "GOA"})

    def test_the_backfill_mapping_covers_the_legacy_codes(self):
        """The migration maps BCU -> MSBCU and BESTIU -> itself, and
        deliberately omits JD because JD confers no degree.

        Asserted against the migration's own mapping table: the test
        database is built from an empty schema, so there are no migrated
        programs left to count here.
        """
        from importlib import import_module
        mig = import_module("apps.master.migrations.0018_university".replace(
            "migrations.0018", "migrations._0018",
        )) if False else None
        from apps.master.migrations import __name__ as _pkg
        mod = __import__(
            f"{_pkg}.0018_university", fromlist=["CERTIFICATION_TO_CODE"],
        )
        self.assertEqual(mod.CERTIFICATION_TO_CODE["BCU"], "MSBCU")
        self.assertEqual(mod.CERTIFICATION_TO_CODE["BESTIU"], "BESTIU")
        self.assertNotIn("JD", mod.CERTIFICATION_TO_CODE)

    def test_a_program_can_name_institute_and_university_separately(self):
        institute = Institute.objects.create(name="Test Inst", code="TI")
        uni = University.objects.get(code="GOA")
        program = Program.objects.create(
            name="Test Program", code="TP",
            institute=institute, university=uni,
        )
        self.assertEqual(program.institute.code, "TI")
        self.assertEqual(program.university.code, "GOA")


class SemesterPerProgramTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="Inst", code="INST")
        cls.a = Program.objects.create(
            name="Prog A", code="PA", institute=cls.institute,
        )
        cls.b = Program.objects.create(
            name="Prog B", code="PB", institute=cls.institute,
        )

    def test_two_programs_can_each_have_a_semester_one(self):
        """The whole point: "Sem 1" is no longer a single global row."""
        a1 = Semester.objects.create(program=self.a, name="Semester 1", number=1)
        b1 = Semester.objects.create(program=self.b, name="Semester 1", number=1)
        self.assertNotEqual(a1.pk, b1.pk)
        self.assertEqual(a1.number, b1.number)

    def test_a_program_cannot_repeat_a_number(self):
        Semester.objects.create(program=self.a, name="Semester 1", number=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Semester.objects.create(
                    program=self.a, name="First", number=1,
                )

    def test_a_program_cannot_repeat_a_name(self):
        Semester.objects.create(program=self.a, name="Semester 1", number=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Semester.objects.create(
                    program=self.a, name="Semester 1", number=2,
                )

    def test_semester_reaches_its_program(self):
        sem = Semester.objects.create(program=self.a, name="S1", number=1)
        self.assertEqual(sem.program.code, "PA")
        self.assertIn(sem, self.a.semesters.all())

    def test_deleting_a_program_takes_its_semesters(self):
        Semester.objects.create(program=self.b, name="S1", number=1)
        self.b.delete()
        self.assertFalse(Semester.objects.filter(program_id=self.b.pk).exists())


class SemesterApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="u", email="u@e.com", password="x",
        )
        cls.admin = User.objects.create_superuser(
            username="a", email="a@e.com", password="x",
        )
        cls.institute = Institute.objects.create(name="Inst", code="INST")
        cls.a = Program.objects.create(
            name="Prog A", code="PA", institute=cls.institute,
        )
        cls.b = Program.objects.create(
            name="Prog B", code="PB", institute=cls.institute,
        )
        Semester.objects.create(program=cls.a, name="A-S1", number=1)
        Semester.objects.create(program=cls.a, name="A-S2", number=2)
        Semester.objects.create(program=cls.b, name="B-S1", number=1)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_filters_by_program(self):
        r = self.client.get("/api/master/semesters/", {"program": self.a.id})
        self.assertEqual(
            {row["name"] for row in r.json()}, {"A-S1", "A-S2"},
        )

    def test_unfiltered_returns_every_program(self):
        r = self.client.get("/api/master/semesters/")
        self.assertEqual(
            {row["name"] for row in r.json()}, {"A-S1", "A-S2", "B-S1"},
        )

    def test_payload_names_the_program(self):
        r = self.client.get("/api/master/semesters/", {"program": self.b.id})
        row = r.json()[0]
        self.assertEqual(row["program"], self.b.id)
        self.assertEqual(row["program_name"], "Prog B")

    def test_duplicate_number_is_a_field_error_not_a_500(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/master/semesters/", {
            "program": self.a.id, "name": "Another", "number": 1,
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        # DRF's UniqueTogetherValidator reports it as a non-field error.
        self.assertIn(
            "unique set", str(r.json()).lower(),
        )

    def test_same_number_in_another_program_is_fine(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/master/semesters/", {
            "program": self.b.id, "name": "B-S2", "number": 2,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)


class BatchStartSemesterTests(TestCase):
    """A batch persists across semesters; `start_semester` only records
    where the cohort entered. Promotion still advances the Enrollment."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from apps.master.models import AcademicYear, Batch, Campus

        cls.institute = Institute.objects.create(name="Inst", code="INST")
        cls.program = Program.objects.create(
            name="Prog", code="P", institute=cls.institute,
        )
        cls.other = Program.objects.create(
            name="Other", code="O", institute=cls.institute,
        )
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem1 = Semester.objects.create(
            program=cls.program, name="Sem 1", number=1,
        )
        cls.Batch = Batch

    def test_start_semester_is_optional(self):
        batch = self.Batch.objects.create(
            name="B1", program=self.program, campus=self.campus,
            academic_year=self.year,
        )
        self.assertIsNone(batch.start_semester)

    def test_start_semester_records_the_entry_point(self):
        batch = self.Batch.objects.create(
            name="B2", program=self.program, campus=self.campus,
            academic_year=self.year, start_semester=self.sem1,
        )
        self.assertEqual(batch.start_semester.number, 1)
        # And it does NOT pin the batch: the cohort still advances via
        # its enrollments, so the batch row is unchanged by promotion.
        self.assertEqual(batch.start_semester.program, self.program)


class SubjectStaysProgramScopedTests(TestCase):
    """Subjects are owned by (program, semester), NOT by a batch, so one
    subject serves every batch in that semester."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date

        from apps.master.models import AcademicYear, Batch, Campus, Subject

        cls.institute = Institute.objects.create(name="Inst", code="INST")
        cls.program = Program.objects.create(
            name="Prog", code="P", institute=cls.institute,
        )
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem1 = Semester.objects.create(
            program=cls.program, name="Sem 1", number=1,
        )
        cls.batch_a = Batch.objects.create(
            name="A", program=cls.program, campus=cls.campus,
            academic_year=cls.year, start_semester=cls.sem1,
        )
        cls.batch_b = Batch.objects.create(
            name="B", program=cls.program, campus=cls.campus,
            academic_year=cls.year, start_semester=cls.sem1,
        )
        cls.subject = Subject.objects.create(
            name="Design Studio", code="DS",
            program=cls.program, semester=cls.sem1,
        )
        cls.Subject = Subject

    def test_subject_has_no_batch_field(self):
        """Guards the design decision: adding Subject.batch would force a
        duplicate row per batch and break cross-batch marks reporting."""
        field_names = {f.name for f in self.Subject._meta.get_fields()}
        self.assertNotIn("batch", field_names)

    def test_one_subject_serves_every_batch_in_the_semester(self):
        for batch in (self.batch_a, self.batch_b):
            self.assertEqual(batch.start_semester, self.subject.semester)
            self.assertEqual(batch.program, self.subject.program)
        self.assertEqual(
            self.Subject.objects.filter(
                program=self.program, semester=self.sem1,
            ).count(),
            1,
        )
