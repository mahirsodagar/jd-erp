"""`?teaching=1` narrows employee lists to TEACHING STAFF.

Client, 2026-11-25: the flag `Employee.is_teaching` decides, whatever
the designation — an HOD who also teaches is ticked by HR and appears in
every faculty / instructor / mentor picker. Before this it was
designation == Faculty only (2026-11-21), which hid such HODs. New hires
with a Faculty designation get the flag on create unless HR unticks it.
"""

from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.employees.models import Designation, Employee
from apps.employees.serializers import EmployeeCreateSerializer
from apps.employees.views import _apply_filters
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee


class TeachingFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")

        def emp(code, designation, teaching):
            desig, _ = Designation.objects.get_or_create(name=designation)
            e = make_employee(code, institute=cls.inst, campus=cls.campus)
            e.designation = desig
            e.is_teaching = teaching
            e.save(update_fields=["designation", "is_teaching"])
            return e

        emp("FAC1", "Faculty", True)
        emp("FAC2", "Faculty", False)        # Faculty on paper, HR says no
        emp("HOD", "Head Of Department", True)  # HOD who also teaches
        emp("ACC", "Accountant", False)
        emp("VIS", "Visiting Faculty", True)

    def _codes(self, q):
        qs = _apply_filters(Employee.objects.all(), QueryDict(q))
        return sorted(qs.values_list("emp_code", flat=True))

    def test_flag_decides_not_designation(self):
        self.assertEqual(self._codes("teaching=1"), ["FAC1", "HOD", "VIS"])

    def test_not_set_is_no_filter(self):
        self.assertEqual(len(self._codes("")), 5)
        self.assertEqual(len(self._codes("teaching=0")), 5)

    def test_options_endpoint_honours_the_flag(self):
        from django.contrib.auth import get_user_model
        u = get_user_model().objects.create_user(
            username="any", password="x", email="any@example.com")
        c = APIClient()
        c.force_authenticate(u)
        r = c.get(reverse("employee-options"), {"teaching": "1"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(e["emp_code"] for e in r.data), ["FAC1", "HOD", "VIS"])
        self.assertTrue(all(e["is_teaching"] for e in r.data))
        r = c.get(reverse("employee-options"))
        self.assertEqual(len(r.data), 5)

    def test_create_defaults_flag_from_designation(self):
        fac = Designation.objects.get(name="Faculty")
        acc = Designation.objects.get(name="Accountant")
        base = make_employee("TPL", institute=self.inst, campus=self.campus)
        common = {
            "first_name": "New", "dob": "1990-01-01", "nationality": "INDIAN",
            "blood_group": "A+", "gender": "F", "employment_type": 1,
            "employment_category": "CONTRACT",
            "date_of_appointment": "2020-01-01", "date_of_joining": "2020-01-01",
            "department": base.department_id, "campus": self.campus.id,
            "institute": self.inst.id,
            "current_address": "1 St", "current_city": base.current_city_id,
            "current_state": base.current_state_id,
            "permanent_address": "1 St", "permanent_city": base.current_city_id,
            "permanent_state": base.current_state_id,
            "mobile_primary": "9999999999", "email_primary": "n@example.com",
        }
        s = EmployeeCreateSerializer(data={**common, "designation": fac.id})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertTrue(s.validated_data["is_teaching"])
        s = EmployeeCreateSerializer(data={**common, "designation": acc.id,
                                           "email_primary": "m@example.com"})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertFalse(s.validated_data["is_teaching"])
        # Explicit value wins over the designation default.
        s = EmployeeCreateSerializer(data={**common, "designation": acc.id,
                                           "is_teaching": True,
                                           "email_primary": "o@example.com"})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertTrue(s.validated_data["is_teaching"])
