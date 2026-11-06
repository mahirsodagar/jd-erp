"""Team Approval must find a manager's leaves even when the manager's
portal login email differs from the employee email the request was
routed to (prod: manager logs in with a Gmail address, requests go to
the institute address on the employee record)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.leaves.models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)
from apps.master.models import Campus, Institute
from apps.notifications.inapp import user_by_email
from apps.notifications.models import InAppNotification
from apps.relieving.tests_notifications import make_employee
from apps.roles.seed import seed_faculty_role, seed_permissions

User = get_user_model()

LEAVES = "/api/leaves/applications/"
COMPOFF = "/api/leaves/comp-off/"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class TeamScopeLoginEmailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        faculty = seed_faculty_role()
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")

        # Manager: logs in with a personal address, employee record
        # carries the institute address (what requests are routed to).
        cls.boss_user = User.objects.create_user(
            username="boss", email="BOSS.K7@gmail.com", password="x",
        )
        cls.boss_user.roles.add(faculty)
        cls.boss = make_employee(
            "BOSS", institute=institute, campus=campus,
            user_account=cls.boss_user,
        )
        assert cls.boss.email_primary.lower() != cls.boss_user.email.lower()

        cls.user = User.objects.create_user(
            username="asha", email="asha@jdinstitute.edu.in", password="x",
        )
        cls.user.roles.add(faculty)
        cls.emp = make_employee(
            "ASHA", institute=institute, campus=campus,
            user_account=cls.user, reporting_manager_1=cls.boss,
        )

        cls.cl = LeaveType.objects.create(name="Casual Leave", code="CL")
        LeaveAllocation.objects.create(
            employee=cls.emp, leave_type=cls.cl, count=Decimal("10"),
            start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_leave_shows_in_manager_team_list_and_is_decidable(self):
        r = self._client(self.user).post(LEAVES, {
            "leave_type": self.cl.id, "from_date": "2026-11-10",
            "to_date": "2026-11-10", "from_session": 1, "reason": "family event",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["manager_email"], self.boss.email_primary)
        leave_id = r.json()["id"]

        team = self._client(self.boss_user).get(LEAVES, {"scope": "team"})
        self.assertEqual([a["id"] for a in team.json()], [leave_id])

        detail = self._client(self.boss_user).get(f"{LEAVES}{leave_id}/")
        self.assertEqual(detail.status_code, 200)

        d = self._client(self.boss_user).patch(
            f"{LEAVES}{leave_id}/decision/", {"status": 2}, format="json",
        )
        self.assertEqual(d.status_code, 200, d.content)
        self.assertEqual(
            LeaveApplication.objects.get(pk=leave_id).status,
            LeaveApplication.Status.APPROVED,
        )

    def test_compoff_shows_in_manager_team_list_and_is_decidable(self):
        r = self._client(self.user).post(COMPOFF, {
            "worked_date": "2026-11-01", "worked_session_1": 1,
            "worked_session_2": 1, "reason": "exam duty",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        co_id = r.json()["id"]

        team = self._client(self.boss_user).get(COMPOFF, {"scope": "team"})
        self.assertEqual([c["id"] for c in team.json()], [co_id])

        d = self._client(self.boss_user).patch(
            f"{COMPOFF}{co_id}/decision/", {"status": 2}, format="json",
        )
        self.assertEqual(d.status_code, 200, d.content)
        self.assertEqual(
            CompOffApplication.objects.get(pk=co_id).status,
            CompOffApplication.Status.APPROVED,
        )

    def test_unrelated_user_sees_nothing_and_cannot_decide(self):
        app = LeaveApplication.objects.create(
            employee=self.emp, leave_type=self.cl,
            from_date=date(2026, 11, 12), to_date=date(2026, 11, 12),
            from_session=1, count=Decimal("1"), reason="x",
            manager_email=self.boss.email_primary,
        )
        stranger = User.objects.create_user(
            username="norm", email="norm@jdinstitute.edu.in", password="x",
        )
        team = self._client(stranger).get(LEAVES, {"scope": "team"})
        self.assertEqual(team.json(), [])
        d = self._client(stranger).patch(
            f"{LEAVES}{app.id}/decision/", {"status": 2}, format="json",
        )
        self.assertEqual(d.status_code, 403)

    def test_bell_notification_reaches_manager_login_account(self):
        self.assertEqual(user_by_email(self.boss.email_primary), self.boss_user)
        self.assertIsNone(user_by_email("nobody@jdinstitute.edu.in"))
        self._client(self.user).post(LEAVES, {
            "leave_type": self.cl.id, "from_date": "2026-11-20",
            "to_date": "2026-11-20", "from_session": 1, "reason": "family event",
        }, format="json")
        self.assertTrue(
            InAppNotification.objects.filter(recipient=self.boss_user).exists()
        )
