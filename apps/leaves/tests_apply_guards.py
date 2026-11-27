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

    def test_permission_type_matched_by_name_not_only_code(self):
        # HR creates "Permission" from the Leave Types page with its own
        # code; it must still be restricted to the two session slots.
        perm2 = LeaveType.objects.create(
            code="PERM", name="Permission Leave",
            category=LeaveType.Category.LEAVE, half_day_allowed=True,
        )
        self.assertTrue(perm2.is_permission)
        self.assertFalse(self.cl.is_permission)
        r = self._apply(perm2, "2026-10-06", session=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Session 1", r.json()["from_session"][0])
        self.assertEqual(self._apply(perm2, "2026-10-06", session=3).status_code, 201)
        types = self.client.get("/api/leaves/types/").json()
        rows = types["results"] if isinstance(types, dict) else types
        by_code = {t["code"]: t for t in rows}
        self.assertTrue(by_code["PERM"]["is_permission"])
        self.assertFalse(by_code["CASUAL"]["is_permission"])

    def test_first_and_second_half_same_day_coexist(self):
        r = self._apply(self.cl, "2026-10-05", session=5)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(r.json()["count"]), Decimal("0.5"))
        self.assertEqual(self._apply(self.cl, "2026-10-05", session=1).status_code, 201)
        self.assertEqual(self._apply(self.cl, "2026-10-05", session=5).status_code, 400)

    def test_half_day_clashes_with_permission_inside_it(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05", session=5).status_code, 201)
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=4).status_code, 400)
        self.assertEqual(self._apply(self.perm, "2026-10-05", session=3).status_code, 201)

    def test_unknown_session_rejected(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05", session=6).status_code, 400)

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

    def test_comp_off_is_unlimited_like_on_duty(self):
        # Client (2026-11-27): the earned pool is informational only, so a
        # comp-off leave goes through even with nothing earned and even
        # though the type is flagged enforce_balance.
        self.assertEqual(self._apply(self.co, "2026-10-05").status_code, 201)
        self.assertEqual(self._apply(self.co, "2026-10-12", "2026-10-16").status_code, 201)

    def test_unenforced_types_are_unlimited(self):
        self.assertEqual(self._apply(self.visit, "2026-10-01", "2026-10-20").status_code, 201)

    # --- approve re-check -----------------------------------------------

    def _boss_client(self):
        boss = User.objects.create_user(
            username="boss", email="boss@e.com", password="x",
        )
        c = APIClient()
        c.force_authenticate(user=boss)
        return c

    def test_approve_blocked_when_it_would_overdraw(self):
        # A pending row filed before the guard existed.
        app = LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=date(2026, 10, 5), to_date=date(2026, 10, 9),
            from_session=2, count=Decimal("5"), reason="x",
            manager_email="boss@e.com",
        )
        r = self._boss_client().patch(f"{APPLY}{app.id}/decision/",
                                      {"status": 2}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        app.refresh_from_db()
        self.assertEqual(app.status, LeaveApplication.Status.PENDING)

    def test_approve_keeps_other_pending_reserved(self):
        # 3 granted: two 2-day pendings can't both be approved.
        a = self._apply(self.cl, "2026-10-05", "2026-10-06").json()["id"]
        LeaveApplication.objects.filter(pk=a).update(count=Decimal("2"))
        b = LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=date(2026, 10, 12), to_date=date(2026, 10, 13),
            from_session=2, count=Decimal("2"), reason="x",
            manager_email="boss@e.com",
        )
        boss = self._boss_client()
        self.assertEqual(boss.patch(f"{APPLY}{a}/decision/", {"status": 2},
                                    format="json").status_code, 200)
        r = boss.patch(f"{APPLY}{b.id}/decision/", {"status": 2}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    # --- self-routing / self-approval -----------------------------------

    def test_cannot_route_leave_to_own_email(self):
        for own in ("asha@e.com", self.emp.email_primary):
            r = self.client.post(APPLY, {
                "leave_type": self.cl.id, "from_date": "2026-10-05",
                "to_date": "2026-10-05", "from_session": 2,
                "reason": "personal", "manager_email": own,
            }, format="json")
            self.assertEqual(r.status_code, 400, r.content)
            self.assertIn("manager_email", r.json())

    def test_cannot_decide_own_leave_even_with_matching_snapshot(self):
        app = LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.visit,
            from_date=date(2026, 10, 5), to_date=date(2026, 10, 5),
            from_session=2, count=Decimal("1"), reason="x",
            manager_email="asha@e.com",
        )
        r = self.client.patch(f"{APPLY}{app.id}/decision/",
                              {"status": 2}, format="json")
        self.assertEqual(r.status_code, 403, r.content)

    def test_cannot_route_compoff_to_self_or_claim_same_session_twice(self):
        url = "/api/leaves/comp-off/"
        body = {"worked_date": "2026-09-06", "worked_session_1": 1,
                "worked_session_2": 0, "reason": "event duty",
                "manager_email": "asha@e.com"}
        self.assertEqual(self.client.post(url, body, format="json").status_code, 400)
        body["manager_email"] = "boss@e.com"
        self.assertEqual(self.client.post(url, body, format="json").status_code, 201)
        # Same session again → refused; the other session is still claimable.
        r = self.client.post(url, body, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already", r.json()["detail"])
        body["worked_session_1"], body["worked_session_2"] = 0, 1
        self.assertEqual(self.client.post(url, body, format="json").status_code, 201)
        # Future date → refused.
        body["worked_date"] = "2099-01-01"
        self.assertEqual(self.client.post(url, body, format="json").status_code, 400)

    # --- allocation windows ----------------------------------------------

    def test_balance_is_scoped_to_the_window_covering_the_leave(self):
        # A spent 2025-26 grant does not carry into 2026-27.
        LeaveAllocation.objects.create(
            employee=self.emp, leave_type=self.cl, count=Decimal("2"),
            start_date=date(2025, 6, 1), end_date=date(2026, 5, 31),
        )
        LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=date(2026, 1, 5), to_date=date(2026, 1, 6),
            from_session=2, count=Decimal("2"), reason="x",
            manager_email="boss@e.com", status=LeaveApplication.Status.APPROVED,
        )
        r = self.client.get(f"{APPLY}balances/?on=2026-10-01").json()
        cl = next(x for x in r if x["leave_type_code"] == "CASUAL")
        self.assertEqual(Decimal(cl["granted"]), Decimal("3"))
        self.assertEqual(Decimal(cl["availed"]), Decimal("0"))
        self.assertEqual(cl["window_start"], "2026-06-01")
        # Only 3 remain in 2026-27 even though 2025-26 had 2 more granted.
        self.assertEqual(self._apply(self.cl, "2026-10-05", "2026-10-08").status_code, 400)
        self.assertEqual(self._apply(self.cl, "2026-10-05", "2026-10-07").status_code, 201)

    def test_no_allocation_window_refuses_enforced_type(self):
        r = self._apply(self.cl, "2030-01-05")
        self.assertEqual(r.status_code, 400)
        self.assertIn("allocation", r.json()["detail"])

    def test_balance_subtracts_pending(self):
        self.assertEqual(self._apply(self.cl, "2026-10-05", "2026-10-06").status_code, 201)
        r = self.client.get(f"{APPLY}balances/?on=2026-10-01").json()
        cl = next(x for x in r if x["leave_type_code"] == "CASUAL")
        self.assertEqual(Decimal(cl["pending"]), Decimal("2"))
        self.assertEqual(Decimal(cl["balance"]), Decimal("1"))

    def test_type_code_is_immutable(self):
        self.user.is_superuser = True
        self.user.save()
        r = self.client.patch(f"/api/leaves/types/{self.cl.id}/",
                              {"code": "CL"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f"/api/leaves/types/{self.cl.id}/",
                              {"code": "CASUAL", "name": "Casual"}, format="json")
        self.assertEqual(r.status_code, 200)
