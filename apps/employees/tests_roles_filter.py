"""`?roles=Faculty,HOD` narrows the employee list to staff whose login
holds any of those roles (used by the Publish Timetable faculty picker)."""

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase

from apps.employees.models import Employee
from apps.employees.views import _apply_filters
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.models import Role

User = get_user_model()


class RolesFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        # System roles, created by roles.0004.
        faculty = Role.objects.get(name="Faculty")
        hod = Role.objects.get(name="HOD")
        hr = Role.objects.get(name="HR")

        def emp(code, *roles):
            u = User.objects.create_user(
                username=code.lower(), email=f"{code.lower()}@e.com", password="x",
            )
            for r in roles:
                u.roles.add(r)
            return make_employee(code, institute=inst, campus=campus,
                                 user_account=u)

        cls.fac = emp("FAC", faculty)
        cls.hod = emp("HOD", hod)
        cls.both = emp("BOTH", faculty, hod)
        emp("HRX", hr)
        make_employee("NOLOGIN", institute=inst, campus=campus)

    def _codes(self, q):
        qs = _apply_filters(Employee.objects.all(), QueryDict(q))
        return sorted(qs.values_list("emp_code", flat=True))

    def test_faculty_or_hod_each_once(self):
        self.assertEqual(self._codes("roles=Faculty,HOD"), ["BOTH", "FAC", "HOD"])

    def test_case_insensitive(self):
        self.assertEqual(self._codes("roles=hod"), ["BOTH", "HOD"])

    def test_blank_is_no_filter(self):
        self.assertEqual(len(self._codes("roles=")), 5)
