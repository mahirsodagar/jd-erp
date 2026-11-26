"""A student cannot hold two pending/approved leaves covering the same day."""

from datetime import date

from django.test import TestCase, override_settings

from apps.admissions.models import Student
from apps.master.models import AcademicYear, Campus, Institute, Program
from apps.student_leaves import services
from apps.student_leaves.models import StudentLeaveApplication


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StudentLeaveOverlapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year,
        )

    def _apply(self, frm, to):
        return services.apply_leave(
            student=self.student, leave_date=frm, leave_edate=to,
            student_remarks="family function", batch_mentor_email="mentor@e.com",
        )

    def test_overlapping_range_is_refused(self):
        self._apply(date(2026, 3, 1), date(2026, 3, 5))
        with self.assertRaises(ValueError) as cm:
            self._apply(date(2026, 3, 3), date(2026, 3, 7))
        self.assertIn("Overlaps", str(cm.exception))

    def test_approved_leave_also_blocks(self):
        app = self._apply(date(2026, 3, 1), date(2026, 3, 5))
        StudentLeaveApplication.objects.filter(pk=app.pk).update(
            status=StudentLeaveApplication.Status.APPROVED,
        )
        with self.assertRaises(ValueError):
            self._apply(date(2026, 3, 5), date(2026, 3, 5))

    def test_rejected_and_adjacent_do_not_block(self):
        app = self._apply(date(2026, 3, 1), date(2026, 3, 5))
        self._apply(date(2026, 3, 6), date(2026, 3, 6))
        StudentLeaveApplication.objects.filter(pk=app.pk).update(
            status=StudentLeaveApplication.Status.REJECTED,
        )
        self._apply(date(2026, 3, 2), date(2026, 3, 2))
