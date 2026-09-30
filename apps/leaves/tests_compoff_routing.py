"""Comp-off routing: the request goes to the manager email given at apply
time (default: reporting manager 1), HR is copied, and only that manager
(or an approve_any holder) can decide it."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.leaves.models import CompOffApplication
from apps.leaves.services.notifications import HR_INBOX
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.seed import seed_faculty_role, seed_permissions

User = get_user_model()

URL = "/api/leaves/comp-off/"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
)
class CompOffRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        faculty = seed_faculty_role()
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")

        def person(code):
            u = User.objects.create_user(
                username=code.lower(),
                email=f"{code.lower()}@jdinstitute.edu.in", password="x",
            )
            u.roles.add(faculty)
            return u, make_employee(code, institute=institute, campus=campus,
                                    user_account=u)

        cls.boss_user, cls.boss = person("BOSS")
        cls.other_user, cls.other = person("OTHER")
        cls.user, cls.emp = person("ASHA")
        cls.emp.reporting_manager_1 = cls.boss
        cls.emp.save(update_fields=["reporting_manager_1"])
        cls.orphan_user, cls.orphan = person("NORM")

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def _apply(self, user, **extra):
        return self._client(user).post(URL, {
            "worked_date": "2026-09-06", "worked_session_1": 1,
            "worked_session_2": 1, "reason": "exam duty", **extra,
        }, format="json")

    def test_reporting_manager_endpoint(self):
        r = self._client(self.user).get("/api/leaves/reporting-manager/")
        self.assertEqual(r.json()["manager"]["email"], self.boss.email_primary)
        r = self._client(self.orphan_user).get("/api/leaves/reporting-manager/")
        self.assertIsNone(r.json()["manager"])

    def test_defaults_to_reporting_manager_and_copies_hr(self):
        r = self._apply(self.user, cc_emails="peer@jdinstitute.edu.in")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["manager_email"], self.boss.email_primary)
        msg = mail.outbox[-1]
        self.assertEqual(msg.to, [self.boss.email_primary])
        self.assertEqual(msg.cc, ["peer@jdinstitute.edu.in", HR_INBOX])

        team = self._client(self.boss_user).get(URL, {"scope": "team"}).json()
        self.assertEqual([c["id"] for c in team], [r.json()["id"]])

    def test_no_manager_anywhere_is_rejected(self):
        r = self._apply(self.orphan_user)
        self.assertEqual(r.status_code, 400)
        self.assertIn("manager_email", r.json())
        self.assertFalse(CompOffApplication.objects.exists())

    def test_typed_email_routes_there_not_to_reporting_manager(self):
        r = self._apply(self.user, manager_email=self.other.email_primary)
        co_id = r.json()["id"]
        self.assertEqual(
            self._client(self.boss_user).get(URL, {"scope": "team"}).json(), [])
        denied = self._client(self.boss_user).patch(
            f"{URL}{co_id}/decision/", {"status": 2}, format="json")
        self.assertEqual(denied.status_code, 403)
        ok = self._client(self.other_user).patch(
            f"{URL}{co_id}/decision/", {"status": 2}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(mail.outbox[-1].cc, [self.other.email_primary])

    def test_manager_change_does_not_reroute_pending(self):
        co_id = self._apply(self.user).json()["id"]
        self.emp.reporting_manager_1 = self.other
        self.emp.save(update_fields=["reporting_manager_1"])
        ok = self._client(self.boss_user).patch(
            f"{URL}{co_id}/decision/", {"status": 2}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)
