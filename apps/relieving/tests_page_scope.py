"""Three-page split (2026-11-12): a faculty member sees only their own
applications (My Relieving); the dashboard list carries only chains the
caller approves on; the report needs its own key."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.master.models import Campus, Institute
from apps.relieving.models import RelievingApplication
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

from .tests_notifications import make_employee
from .tests_workflow import set_managers

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RelievingPageScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.inst = Institute.objects.create(name="JD School of Design", code="JDSD")
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=cls.inst, campus=campus)

        def with_login(code):
            emp = make_employee(code, **kw)
            emp.user_account = User.objects.create_user(code.lower(), emp.email_primary, "x")
            emp.save(update_fields=["user_account"])
            return emp

        cls.m1, cls.m2, cls.m3, cls.m4 = (with_login(f"MGR{i}") for i in range(1, 5))
        cls.faculty_a = with_login("FACA")
        cls.faculty_b = with_login("FACB")
        cls.outsider = with_login("OUT")  # employee on nobody's chain
        seed_permissions()
        cls.reporter = User.objects.create_user("reporter", "r@x.in", "x")
        role = Role.objects.create(name="Reporter")
        role.permissions.set(Permission.objects.filter(key="hr.relieving.report"))
        cls.reporter.roles.add(role)

    def setUp(self):
        set_managers(self.inst, {1: self.m1, 2: self.m2, 3: self.m3, 4: self.m4})
        self.app_a = self._submit(self.faculty_a)
        self.app_b = self._submit(self.faculty_b)

    def _client(self, who):
        c = APIClient()
        c.force_authenticate(getattr(who, "user_account", who))
        return c

    def _submit(self, emp):
        r = self._client(emp).post("/api/hr/relieving/", {
            "employee": emp.id, "application_type": "RELIEVING",
            "reason": "Moving on to further studies.",
            "last_working_date_requested": "2026-12-31",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return RelievingApplication.objects.get(pk=r.data["id"])

    # --- My Relieving --------------------------------------------------

    def test_me_returns_only_my_own_applications(self):
        r = self._client(self.faculty_a).get("/api/hr/relieving/me/")
        self.assertEqual([a["id"] for a in r.data], [self.app_a.id])

    def test_faculty_dashboard_list_is_empty_even_for_own_application(self):
        """The dashboard is the approvers' page; a faculty member on no
        chain gets nothing from it — not even their own row, which lives
        on My Relieving."""
        r = self._client(self.faculty_a).get("/api/hr/relieving/")
        self.assertEqual(r.data, [])

    def test_faculty_cannot_open_a_colleagues_application(self):
        # Hidden as 404, not 403: a colleague should not even learn the id exists.
        r = self._client(self.faculty_a).get(f"/api/hr/relieving/{self.app_b.id}/")
        self.assertEqual(r.status_code, 404)
        r = self._client(self.faculty_a).get(f"/api/hr/relieving/{self.app_a.id}/")
        self.assertEqual(r.status_code, 200)

    # --- Dashboard -------------------------------------------------------

    def test_approver_dashboard_lists_only_their_chains(self):
        r = self._client(self.m1).get("/api/hr/relieving/")
        self.assertEqual({a["id"] for a in r.data}, {self.app_a.id, self.app_b.id})
        # Someone not on any chain sees nothing.
        r = self._client(self.outsider).get("/api/hr/relieving/")
        self.assertEqual(r.data, [])

    def test_me_flag_marks_approvers_for_the_dashboard_menu(self):
        self.assertTrue(self._client(self.m3).get("/api/auth/me/").data["is_relieving_approver"])
        self.assertFalse(self._client(self.faculty_a).get("/api/auth/me/").data["is_relieving_approver"])

    # --- Report ----------------------------------------------------------

    def test_report_needs_its_own_key(self):
        self.assertEqual(self._client(self.m1).get("/api/hr/relieving/report/").status_code, 403)
        self.assertEqual(self._client(self.faculty_a).get("/api/hr/relieving/report/").status_code, 403)
        r = self._client(self.reporter).get("/api/hr/relieving/report/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 2)

    def test_report_filters_and_csv(self):
        c = self._client(self.reporter)
        self.assertEqual(c.get("/api/hr/relieving/report/?status=REJECTED").data["count"], 0)
        self.assertEqual(c.get(f"/api/hr/relieving/report/?institute={self.inst.id}").data["count"], 2)
        self.assertEqual(c.get("/api/hr/relieving/report/?end_date=2000-01-01").data["count"], 0)

        r = c.get("/api/hr/relieving/report/?output=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Relieving Report.csv", r["Content-Disposition"])
        body = r.content.decode("utf-8-sig")
        header, *rows = [ln for ln in body.splitlines() if ln]
        self.assertIn("Manager 4 date", header)
        self.assertEqual(len(rows), 2)
        self.assertIn("Mgr1,Academic Manager,Pending", body)  # L1 columns
