"""The Apply dashboard's leave year is the 1 Jun – 31 May window
containing the date, not a hard-coded one (legacy leave_apply.php
hard-coded 2025-06-01..2026-05-31)."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.leaves.models import LeaveApplication, LeaveType
from apps.leaves.services.balance import cl_dashboard, leave_year
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee


class LeaveYearWindowTests(SimpleTestCase):
    def test_from_june_onwards_is_this_year(self):
        self.assertEqual(
            leave_year(date(2026, 9, 16)), (date(2026, 6, 1), date(2027, 5, 31)),
        )

    def test_before_june_is_last_year(self):
        self.assertEqual(
            leave_year(date(2027, 5, 31)), (date(2026, 6, 1), date(2027, 5, 31)),
        )

    def test_rolls_over_on_1_june(self):
        self.assertEqual(
            leave_year(date(2027, 6, 1)), (date(2027, 6, 1), date(2028, 5, 31)),
        )

    def test_january_boundary(self):
        self.assertEqual(
            leave_year(date(2027, 1, 1)), (date(2026, 6, 1), date(2027, 5, 31)),
        )


class ClDashboardWindowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.emp = make_employee("ASHA", institute=institute, campus=campus)
        cls.cl, _ = LeaveType.objects.get_or_create(
            code="CASUAL",
            defaults={"name": "Casual Leave", "category": LeaveType.Category.LEAVE},
        )

    def _approved_cl(self, day):
        LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=day, to_date=day, from_session=2, count=Decimal("1"),
            reason="x", status=LeaveApplication.Status.APPROVED,
        )

    def test_only_counts_the_current_leave_year(self):
        self._approved_cl(date(2026, 5, 20))  # previous leave year
        self._approved_cl(date(2026, 7, 10))
        self._approved_cl(date(2026, 8, 3))

        d = cl_dashboard(self.emp, on_date=date(2026, 9, 16))

        self.assertEqual(d["leave_year_start"], "2026-06-01")
        self.assertEqual(d["leave_year_end"], "2027-05-31")
        self.assertEqual(d["total_cl_taken"], Decimal("2"))
        self.assertEqual(d["cl_balance"], Decimal("10"))
