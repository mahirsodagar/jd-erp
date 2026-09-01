"""Electives may share a batch's period; non-electives may not.

Ports the PHP `subject_master.iselective` behaviour — several elective
subjects run in the same slot and each student attends only the one they
picked (academics/aget.php:2404).
"""

from datetime import date, time

from django.test import TestCase

from apps.academics.attendance_service import roster_for
from apps.academics.models import ScheduleSlot
from apps.academics.services import create_slot
from apps.admissions.models import Enrollment, Student
from apps.employees.models import Department, Designation, Employee
from apps.master.models import (
    AcademicYear, Batch, Campus, City, Institute, Program, Semester, State,
    Subject, TimeSlot,
)


def make_faculty(*, code, name, campus, institute):
    """Employee has many non-nullable fields; fill the minimum."""
    state, _ = State.objects.get_or_create(name="Karnataka", code="KA")
    city, _ = City.objects.get_or_create(name="Bengaluru", state=state)
    desig, _ = Designation.objects.get_or_create(name="Faculty")
    dept, _ = Department.objects.get_or_create(name="Design")
    return Employee.objects.create(
        emp_code=code, first_name=name, dob=date(1990, 1, 1),
        nationality="INDIAN", blood_group="A+", gender="F",
        employment_type=1,
        date_of_appointment=date(2020, 1, 1),
        date_of_joining=date(2020, 1, 1),
        designation=desig, department=dept,
        campus=campus, institute=institute,
        current_address="1 St", current_city=city, current_state=state,
        permanent_address="1 St", permanent_city=city, permanent_state=state,
        mobile_primary=f"90000000{code[-1]}",
        email_primary=f"{code.lower()}@example.com",
    )


class ElectiveSchedulingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(
            name="BD-1", program=cls.program, campus=cls.campus,
            academic_year=cls.year,
        )
        cls.slot = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=cls.year,
        )
        cls.core = Subject.objects.create(name="Core Studio", code="CORE")
        cls.elec_a = Subject.objects.create(
            name="Textiles", code="ELEA", is_elective=True,
        )
        cls.elec_b = Subject.objects.create(
            name="Ceramics", code="ELEB", is_elective=True,
        )
        cls.f1 = make_faculty(
            code="E1", name="Ann", campus=cls.campus,
            institute=cls.institute,
        )
        cls.f2 = make_faculty(
            code="E2", name="Bob", campus=cls.campus,
            institute=cls.institute,
        )
        cls.f3 = make_faculty(
            code="E3", name="Cy", campus=cls.campus,
            institute=cls.institute,
        )

    def _make(self, subject, instructor):
        return create_slot(
            batch=self.batch, subject=subject, instructor=instructor,
            classroom=None, time_slot=self.slot, date=date(2026, 7, 1),
        )

    def test_two_electives_share_one_period(self):
        a, _ = self._make(self.elec_a, self.f1)
        b, report = self._make(self.elec_b, self.f2)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b, report)
        self.assertTrue(a.is_elective)
        self.assertTrue(b.is_elective)

    def test_two_core_subjects_still_clash(self):
        first, _ = self._make(self.core, self.f1)
        self.assertIsNotNone(first)
        second, report = self._make(
            Subject.objects.create(name="Other", code="OTH"), self.f2,
        )
        self.assertIsNone(second)
        self.assertTrue(any("already scheduled" in e for e in report["errors"]))

    def test_elective_cannot_share_with_a_core_subject(self):
        core, _ = self._make(self.core, self.f1)
        self.assertIsNotNone(core)
        elective, report = self._make(self.elec_a, self.f2)
        self.assertIsNone(elective)
        self.assertTrue(any("already scheduled" in e for e in report["errors"]))

    def test_instructor_clash_still_blocks_between_electives(self):
        """Electives relax the BATCH rule only — one person still cannot
        teach two of them at once."""
        a, _ = self._make(self.elec_a, self.f1)
        self.assertIsNotNone(a)
        b, report = self._make(self.elec_b, self.f1)
        self.assertIsNone(b)
        self.assertTrue(any("Instructor" in e for e in report["errors"]))


class ElectiveRosterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(
            name="BD-1", program=cls.program, campus=cls.campus,
            academic_year=cls.year,
        )
        cls.ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=cls.year,
        )
        cls.core = Subject.objects.create(name="Core", code="CORE")
        cls.elective = Subject.objects.create(
            name="Textiles", code="ELEA", is_elective=True,
        )
        cls.faculty = make_faculty(
            code="E1", name="Ann", campus=cls.campus,
            institute=cls.institute,
        )

        def student(name, electives):
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
                status=Enrollment.Status.ACTIVE,
                elective_subjects=electives,
            )
            return s

        cls.took = student("Took", str(cls.elective.id))
        cls.other = student("Other", "999")
        cls.none = student("NoneChosen", "")

    def _slot(self, subject):
        slot, _ = create_slot(
            batch=self.batch, subject=subject, instructor=self.faculty,
            classroom=None, time_slot=self.ts, date=date(2026, 7, 1),
        )
        return slot

    def test_core_roster_is_whole_batch(self):
        names = {e.student.student_name for e in roster_for(self._slot(self.core))}
        self.assertEqual(names, {"Took", "Other", "NoneChosen"})

    def test_elective_roster_only_those_who_chose_it(self):
        names = {
            e.student.student_name
            for e in roster_for(self._slot(self.elective))
        }
        self.assertEqual(names, {"Took"})

    def test_csv_elective_field_matches_by_token(self):
        """'1' must not match '12' — the field is a list, not a substring."""
        enr = Enrollment.objects.get(student=self.other)
        enr.elective_subjects = f"7, {self.elective.id} ,9"
        enr.save(update_fields=["elective_subjects"])
        names = {
            e.student.student_name
            for e in roster_for(self._slot(self.elective))
        }
        self.assertEqual(names, {"Took", "Other"})
