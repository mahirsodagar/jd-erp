"""Applying for leave is blocked when it overlaps an existing pending /
approved leave, or when it would overdraw a balance-enforced type."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.seed import seed_faculty_role, seed_permissions

User = get_user_model()

APPLY = "/api/leaves/applications/"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ApplyGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        faculty = seed_faculty_role()
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.user = User.objects.create_user(
            username="asha", email="asha@e.com", password="x",
        )
        cls.user.roles.add(faculty)
        cls.emp = make_employee("ASHA", institute=institute, campus=campus,
                                user_account=cls.user)
        cls.cl = LeaveType.objects.create(
            code="CASUAL", name="Casual Leave",
            category=LeaveType.Category.LEAVE, half_day_allowed=True,
            enforce_balance=True,
        )
        cls.co = LeaveType.objects.create(
            code="COMP_OFF", name="Comp-Off",
            category=LeaveType.Category.LEAVE, half_day_allowed=True,
            enforce_balance=True,
        )
        cls.perm = LeaveType.objects.create(
            code="PERMISSION", name="Permission",
            category=LeaveType.Category.LEAVE, half_day_allowed=True,
        )
        cls.visit = LeaveType.objects.create(
            code="VISIT", name="Visits", category=LeaveType.Category.ON_DUTY,
        )
        LeaveAllocation.objects.create(
            employee=cls.emp, leave_type=cls.cl, count=Decimal("3"),
            start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _apply(self, lt, frm, to=None, session=2):
        return self.client.post(APPLY, {
            "leave_type": lt.id, "from_date": frm, "to_date": to or frm,
            "from_session": session, "reason": "personal",
            "manager_email": "boss@e.com",
        }, format="json")

    # --- overlap -------------------------------------------------------

    def test_overlapping_range_is_rejected(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05", "2026-10-06").status_code, 201)
        r = self._apply(self.visit, "2026-10-06", "2026-10-08")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Overlaps", r.json()["detail"])

    def test_adjacent_range_is_fine(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05").status_code, 201)
        self.assertEqual(self._apply(self.cl, "2026-10-06").status_code, 201)

    def test_rejected_leave_does_not_block(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05").status_code, 201)
        LeaveApplication.objects.update(status=LeaveApplication.Status.REJECTED)
        self.assertEqual(self._apply(self.cl, "2026-10-05").status_code, 201)

    def test_different_permission_slots_same_day_coexist(self):
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=3).status_code, 201)
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=4).status_code, 201)
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=3).status_code, 400)

    def test_part_day_clashes_with_full_day(self):
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=3).status_code, 201)
        self.assertEqual(self._apply(self.cl, "2026-10-05").status_code, 400)

    # --- balance -------------------------------------------------------

    def test_cannot_exceed_granted(self):
        r = self._apply(self.cl, "2026-10-05", "2026-10-08")  # 4 days, 3 granted
        self.assertEqual(r.status_code, 400)
        self.assertIn("Insufficient", r.json()["detail"])

    def test_pending_applies_reserve_balance(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05", "2026-10-06").status_code, 201)
        self.assertEqual(self._apply(self.cl, "2026-10-12", "2026-10-13").status_code, 400)
        self.assertEqual(self._apply(self.cl, "2026-10-12").status_code, 201)

    def test_comp_off_limited_to_earned(self):
        self.assertEqual(self._apply(self.co, "2026-10-05").status_code, 400)
        CompOffApplication.objects.create(
            employee=self.emp, worked_date=date(2026, 9, 6),
            worked_session_1=1, worked_session_2=1, count=Decimal("1"),
            reason="x", status=CompOffApplication.Status.APPROVED,
        )
        self.assertEqual(self._apply(self.co, "2026-10-05").status_code, 201)

    def test_unenforced_types_are_unlimited(self):
        self.assertEqual(self._apply(self.visit, "2026-10-01", "2026-10-20").status_code, 201)

    # --- approve re-check -----------------------------------------------

    def test_approve_blocked_when_it_would_overdraw(self):
        # A pending row filed before the guard existed.
        app = LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=date(2026, 10, 5), to_date=date(2026, 10, 9),
            from_session=2, count=Decimal("5"), reason="x",
            manager_email="asha@e.com",
        )
        r = self.client.patch(f"{APPLY}{app.id}/decision/",
                              {"status": 2}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        app.refresh_from_db()
        self.assertEqual(app.status, LeaveApplication.Status.PENDING)
