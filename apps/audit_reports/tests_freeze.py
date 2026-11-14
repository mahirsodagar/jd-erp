"""Daily reports (faculty + admin) freeze month-wise. A frozen month is
edited only through an access request: employee asks → reporting
manager approves → admin with `audit.daily_report.unlock` grants a
window. `*_any` auditors bypass the freeze."""

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit_reports import freeze
from apps.audit_reports.models import (
    AdminDailyReport, DailyReportAccess, FacultyDailyReport,
)
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

User = get_user_model()

FD = "/api/audit-reports/faculty-daily/"
AD = "/api/audit-reports/admin-daily/"
REQ = "/api/audit-reports/freeze/requests/"
STATUS = "/api/audit-reports/freeze/status/"

TODAY = date(2026, 11, 14)


def _role(name, *keys):
    r = Role.objects.create(name=f"T-{name}")
    r.permissions.add(*Permission.objects.filter(key__in=keys))
    return r


@override_settings(DAILY_REPORT_FREEZE_GRACE_DAYS=0)
class FreezeRuleTests(TestCase):

    def test_previous_month_is_frozen_current_is_not(self):
        self.assertTrue(freeze.month_is_frozen(2026, 10, on=TODAY))
        self.assertFalse(freeze.month_is_frozen(2026, 11, on=TODAY))
        self.assertFalse(freeze.month_is_frozen(2026, 12, on=TODAY))

    @override_settings(DAILY_REPORT_FREEZE_GRACE_DAYS=3)
    def test_grace_days_delay_the_freeze(self):
        self.assertEqual(freeze.freeze_date(2026, 10), date(2026, 11, 4))
        self.assertFalse(freeze.month_is_frozen(2026, 10, on=date(2026, 11, 3)))
        self.assertTrue(freeze.month_is_frozen(2026, 10, on=date(2026, 11, 4)))


@override_settings(DAILY_REPORT_FREEZE_GRACE_DAYS=0)
class FreezeFlowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=inst, campus=campus)

        cls.mgr_user = User.objects.create_user("mgr", "mgr@e.com", "x")
        cls.mgr = make_employee("MGR", user_account=cls.mgr_user, **kw)

        cls.user = User.objects.create_user("asha", "asha@e.com", "x")
        cls.user.roles.add(_role(
            "Faculty", "dashboard.daily_report.submit", "dashboard.admin_daily.submit"))
        cls.emp = make_employee("ASHA", user_account=cls.user,
                                reporting_manager_1=cls.mgr, **kw)

        cls.admin = User.objects.create_user("admin", "admin@e.com", "x")
        cls.admin.roles.add(_role("Unlocker", "audit.daily_report.unlock"))

        cls.auditor = User.objects.create_user("aud", "aud@e.com", "x")
        cls.auditor.roles.add(_role("Auditor", "audit.faculty_daily.edit_any"))

    def setUp(self):
        self.today = mock.patch("apps.audit_reports.freeze.today", return_value=TODAY)
        self.today.start()
        self.addCleanup(self.today.stop)

    def _c(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _post_fd(self, c, day):
        return c.post(FD, {"faculty": self.emp.id, "date": day,
                           "academic_description": "x", "academic_hours": "2"},
                      format="json")

    # --- the freeze itself -------------------------------------------

    def test_current_month_saves_previous_month_is_locked(self):
        c = self._c(self.user)
        self.assertEqual(self._post_fd(c, "2026-11-10").status_code, 201)
        r = self._post_fd(c, "2026-10-28")
        self.assertEqual(r.status_code, 423, r.content)
        self.assertEqual(r.data["code"], "frozen")
        self.assertIn("October 2026", r.data["detail"])

    def test_admin_daily_is_frozen_too_and_edit_delete_are_blocked(self):
        c = self._c(self.user)
        self.assertEqual(c.post(AD, {"rep_date": "2026-10-05", "slot1": "x"},
                                format="json").status_code, 423)
        row = AdminDailyReport.objects.create(user=self.user, rep_date="2026-10-05")
        self.assertEqual(c.patch(f"{AD}{row.id}/", {"slot1": "y"},
                                 format="json").status_code, 423)
        self.assertEqual(c.delete(f"{AD}{row.id}/").status_code, 423)
        self.assertTrue(AdminDailyReport.objects.filter(pk=row.pk).exists())

    def test_edit_any_auditor_bypasses_the_freeze(self):
        row = FacultyDailyReport.objects.create(
            faculty=self.emp, date="2026-10-05", academic_hours=1)
        r = self._c(self.auditor).patch(f"{FD}{row.id}/", {"academic_hours": "3"},
                                        format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_status_endpoint(self):
        r = self._c(self.user).get(STATUS, {"type": "FACULTY", "month": "2026-10"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["frozen"])
        self.assertFalse(r.data["can_edit"])
        self.assertIsNone(r.data["access"])
        r = self._c(self.user).get(STATUS, {"type": "FACULTY", "month": "2026-11"})
        self.assertFalse(r.data["frozen"])
        self.assertTrue(r.data["can_edit"])

    # --- request → manager → admin -----------------------------------

    def _request(self, **over):
        body = {"report_type": "FACULTY", "year": 2026, "month": 10,
                "reason": "Forgot to fill the last week."}
        body.update(over)
        return self._c(self.user).post(REQ, body, format="json")

    def test_full_flow_unlocks_the_month_until_the_date(self):
        r = self._request()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["status"], "PENDING")
        self.assertEqual(r.data["manager_email"], self.mgr.email_primary)
        rid = r.data["id"]

        # Admin cannot grant before the manager approves.
        r = self._c(self.admin).post(f"{REQ}{rid}/grant/",
                                     {"access_until": "2026-11-20"}, format="json")
        self.assertEqual(r.status_code, 400)

        # A stranger cannot decide; the manager can.
        self.assertEqual(self._c(self.admin).post(
            f"{REQ}{rid}/decide/", {"approve": True}, format="json").status_code, 403)
        r = self._c(self.mgr_user).post(f"{REQ}{rid}/decide/",
                                        {"approve": True, "remarks": "ok"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "MANAGER_APPROVED")

        # Still locked until the admin grants.
        self.assertEqual(self._post_fd(self._c(self.user), "2026-10-28").status_code, 423)

        # Only the unlock key grants.
        self.assertEqual(self._c(self.mgr_user).post(
            f"{REQ}{rid}/grant/", {"access_until": "2026-11-20"},
            format="json").status_code, 403)
        r = self._c(self.admin).post(f"{REQ}{rid}/grant/",
                                     {"access_until": "2026-11-20"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "GRANTED")
        self.assertTrue(r.data["is_active"])

        # Now the employee can save October.
        self.assertEqual(self._post_fd(self._c(self.user), "2026-10-28").status_code, 201)
        st = self._c(self.user).get(STATUS, {"type": "FACULTY", "month": "2026-10"}).data
        self.assertTrue(st["can_edit"])
        self.assertEqual(st["access"]["id"], rid)

        # Admin reports are a separate unlock.
        self.assertEqual(self._c(self.user).post(
            AD, {"rep_date": "2026-10-05", "slot1": "x"}, format="json").status_code, 423)

        # Past the window it locks again.
        with mock.patch("apps.audit_reports.freeze.today", return_value=date(2026, 11, 21)):
            self.assertEqual(self._post_fd(self._c(self.user), "2026-10-29").status_code, 423)

    def test_revoke_locks_immediately(self):
        req = DailyReportAccess.objects.create(
            report_type="FACULTY", user=self.user, employee=self.emp, year=2026,
            month=10, reason="x", status=DailyReportAccess.Status.GRANTED,
            access_until=date(2026, 12, 1), manager_email=self.mgr.email_primary)
        self.assertEqual(self._post_fd(self._c(self.user), "2026-10-02").status_code, 201)
        r = self._c(self.admin).post(f"{REQ}{req.id}/revoke/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._post_fd(self._c(self.user), "2026-10-03").status_code, 423)

    def test_manager_can_reject(self):
        rid = self._request().data["id"]
        r = self._c(self.mgr_user).post(f"{REQ}{rid}/decide/",
                                        {"approve": False, "remarks": "no"}, format="json")
        self.assertEqual(r.data["status"], "REJECTED")
        # A rejected request does not block a fresh one.
        self.assertEqual(self._request().status_code, 201)

    def test_request_guards(self):
        # Not frozen → nothing to request.
        self.assertEqual(self._request(month=11).status_code, 400)
        # Duplicate in-progress request.
        self.assertEqual(self._request().status_code, 201)
        self.assertEqual(self._request().status_code, 400)
        # No reporting manager → cannot route.
        self.emp.reporting_manager_1 = None
        self.emp.save(update_fields=["reporting_manager_1"])
        r = self._request(month=9)
        self.assertEqual(r.status_code, 400)
        self.assertIn("reporting manager", r.data["detail"])

    def test_list_scopes(self):
        self._request()
        self.assertEqual(len(self._c(self.user).get(REQ).data), 1)
        self.assertEqual(len(self._c(self.mgr_user).get(REQ, {"scope": "team"}).data), 1)
        self.assertEqual(len(self._c(self.admin).get(REQ, {"scope": "all"}).data), 1)
        self.assertEqual(self._c(self.user).get(REQ, {"scope": "all"}).status_code, 403)
        self.assertEqual(len(self._c(self.admin).get(REQ).data), 0)  # none of their own

    def test_me_flags_reporting_manager(self):
        r = self._c(self.mgr_user).get("/api/auth/me/")
        self.assertTrue(r.data["is_reporting_manager"])
        self.assertFalse(self._c(self.user).get("/api/auth/me/").data["is_reporting_manager"])
