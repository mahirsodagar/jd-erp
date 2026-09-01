"""Program Year = legacy `course_master`.

A year covers a SET of semesters (PHP stored them as a comma-separated
`sem_id` and matched with FIND_IN_SET), and promotion places a student in
the year that covers their new semester.
"""

from datetime import date

from django.test import TestCase

from apps.admissions.models import Enrollment, Student
from apps.admissions.services import promote_batch
from apps.master.models import (
    AcademicYear, Batch, Campus, Course, Institute, Program, Semester,
)


class ProgramYearLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.other_program = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.institute,
        )
        cls.sems = {
            n: Semester.objects.create(name=f"Sem {n}", number=n)
            for n in (1, 2, 3, 4)
        }
        cls.year1 = Course.objects.create(
            name="Year 1", code="BDES-Y1", program=cls.program,
        )
        cls.year1.semesters.set([cls.sems[1], cls.sems[2]])
        cls.year2 = Course.objects.create(
            name="Year 2", code="BDES-Y2", program=cls.program,
        )
        cls.year2.semesters.set([cls.sems[3], cls.sems[4]])

    def test_finds_the_year_covering_a_semester(self):
        self.assertEqual(
            Course.for_semester(program=self.program, semester=self.sems[2]),
            self.year1,
        )
        self.assertEqual(
            Course.for_semester(program=self.program, semester=self.sems[3]),
            self.year2,
        )

    def test_scoped_to_the_program(self):
        """Another program's years must never match."""
        self.assertIsNone(
            Course.for_semester(
                program=self.other_program, semester=self.sems[1],
            ),
        )

    def test_none_when_no_year_covers_it(self):
        sem9 = Semester.objects.create(name="Sem 9", number=9)
        self.assertIsNone(
            Course.for_semester(program=self.program, semester=sem9),
        )

    def test_inactive_years_are_ignored(self):
        self.year1.is_active = False
        self.year1.save(update_fields=["is_active"])
        self.assertIsNone(
            Course.for_semester(program=self.program, semester=self.sems[1]),
        )


class PromotionPicksProgramYearTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.y26 = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.y27 = AcademicYear.objects.create(
            code="27-28", start_date=date(2027, 6, 1), end_date=date(2028, 5, 31),
        )
        cls.sem2 = Semester.objects.create(name="Sem 2", number=2)
        cls.sem3 = Semester.objects.create(name="Sem 3", number=3)

        cls.year1 = Course.objects.create(
            name="Year 1", code="Y1", program=cls.program,
        )
        cls.year1.semesters.set([cls.sem2])
        cls.year2 = Course.objects.create(
            name="Year 2", code="Y2", program=cls.program,
        )
        cls.year2.semesters.set([cls.sem3])

        cls.batch_a = Batch.objects.create(
            name="A", program=cls.program, campus=cls.campus,
            academic_year=cls.y26,
        )
        cls.batch_b = Batch.objects.create(
            name="B", program=cls.program, campus=cls.campus,
            academic_year=cls.y27,
        )

        cls.student = Student.objects.create(
            application_form_id="AF1", student_name="Asha", gender="F",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=cls.institute, campus=cls.campus, program=cls.program,
            academic_year=cls.y26,
        )
        Enrollment.objects.create(
            student=cls.student, program=cls.program, course=cls.year1,
            semester=cls.sem2, campus=cls.campus, batch=cls.batch_a,
            academic_year=cls.y26, status=Enrollment.Status.ACTIVE,
        )

    def test_promotion_moves_the_student_into_the_next_year(self):
        promote_batch(
            source_batch=self.batch_a, source_semester=self.sem2,
            target_batch=self.batch_b, target_semester=self.sem3,
            target_academic_year=self.y27,
        )
        new = Enrollment.objects.get(
            student=self.student, status=Enrollment.Status.ACTIVE,
        )
        self.assertEqual(new.semester, self.sem3)
        self.assertEqual(new.course, self.year2)

    def test_falls_back_to_the_old_year_when_unmapped(self):
        """An unmapped target semester must not blank the student's year."""
        self.year2.semesters.clear()
        promote_batch(
            source_batch=self.batch_a, source_semester=self.sem2,
            target_batch=self.batch_b, target_semester=self.sem3,
            target_academic_year=self.y27,
        )
        new = Enrollment.objects.get(
            student=self.student, status=Enrollment.Status.ACTIVE,
        )
        self.assertEqual(new.course, self.year1)
