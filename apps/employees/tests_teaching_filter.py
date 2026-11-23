"""`?teaching=1` narrows the employee list to the designations in
TIMETABLE_FACULTY_DESIGNATIONS (default: Faculty only) — the timetable's
Faculty dropdown (client bug 2026-11-21: every designation was listed)."""

from django.http import QueryDict
from django.test import TestCase, override_settings

from apps.employees.models import Designation, Employee
from apps.employees.views import _apply_filters
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee


class TeachingFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")

        def emp(code, designation):
            desig, _ = Designation.objects.get_or_create(name=designation)
            e = make_employee(code, institute=inst, campus=campus)
            e.designation = desig
            e.save(update_fields=["designation"])
            return e

        emp("FAC1", "Faculty")
        emp("FAC2", "faculty")           # case-insensitive match
        emp("ASST", "Assistant Professor")
        emp("VIS", "Visiting Faculty")   # not an exact match
        emp("ACC", "Accountant")
        emp("HOD", "Head Of Department")

    def _codes(self, q):
        qs = _apply_filters(Employee.objects.all(), QueryDict(q))
        return sorted(qs.values_list("emp_code", flat=True))

    def test_default_is_faculty_designation_only(self):
        self.assertEqual(self._codes("teaching=1"), ["FAC1", "FAC2"])

    def test_not_set_is_no_filter(self):
        self.assertEqual(len(self._codes("")), 6)
        self.assertEqual(len(self._codes("teaching=0")), 6)

    @override_settings(TIMETABLE_FACULTY_DESIGNATIONS=[
        "Faculty", "Assistant Professor", "Visiting Faculty",
    ])
    def test_setting_widens_the_list(self):
        self.assertEqual(self._codes("teaching=1"),
                         ["ASST", "FAC1", "FAC2", "VIS"])

    @override_settings(TIMETABLE_FACULTY_DESIGNATIONS=[])
    def test_empty_setting_yields_nobody(self):
        self.assertEqual(self._codes("teaching=1"), [])
