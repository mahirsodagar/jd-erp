"""L3 = Principal, L4 = HR (fixed from settings), and the final approval
issues the letters with no separate HR finalize step."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.master.models import Campus, Institute
from apps.relieving.models import RelievingApplication, RelievingApproval

from .tests_notifications import make_employee

PRINCIPAL = "principal@jdinstitute.edu.in"
HR = "trupti@jdinstitute.edu.in"

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    RELIEVING_L3_APPROVER_EMAIL=PRINCIPAL,
    RELIEVING_L4_APPROVER_EMAIL=HR,
)
class RelievingWorkflowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JD School of Design", code="JDSD")
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=inst, campus=campus)

        def with_login(code, **extra):
            emp = make_employee(code, **kw, **extra)
            emp.user_account = User.objects.create_user(
                code.lower(), emp.email_primary, "x")
            emp.save(update_fields=["user_account"])
            return emp

        cls.m1 = with_login("MGR1")
        cls.m2 = with_login("MGR2")
        cls.rm3 = make_employee("RM3", **kw)
        cls.rm4 = make_employee("RM4", **kw)
        cls.principal = with_login("PRINCIPAL")
        cls.hr = with_login("TRUPTI")
        cls.emp = with_login(
            "EMP1",
            reporting_manager_1=cls.m1, reporting_manager_2=cls.m2,
            reporting_manager_3=cls.rm3, reporting_manager_4=cls.rm4,
        )

    def _client(self, emp):
        c = APIClient()
        c.force_authenticate(emp.user_account)
        return c

    def _submit(self):
        r = self._client(self.emp).post("/api/hr/relieving/", {
            "employee": self.emp.id,
            "reason": "Moving on to further studies.",
            "last_working_date_requested": "2026-10-31",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def _decide(self, approver, pk, level):
        r = self._client(approver).post(
            f"/api/hr/relieving/{pk}/decide/{level}/",
            {"decision": "APPROVED"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def _chain(self, pk):
        return list(RelievingApproval.objects.filter(application_id=pk)
                    .order_by("level").values_list("approver_id", flat=True))

    def test_principal_and_hr_replace_reporting_managers_3_and_4(self):
        pk = self._submit()
        self.assertEqual(self._chain(pk), [
            self.m1.id, self.m2.id, self.principal.id, self.hr.id,
        ])

    @override_settings(RELIEVING_L4_APPROVER_EMAIL="")
    def test_blank_setting_falls_back_to_reporting_manager(self):
        pk = self._submit()
        self.assertEqual(self._chain(pk)[3], self.rm4.id)

    @override_settings(RELIEVING_L3_APPROVER_EMAIL="nobody@jdinstitute.edu.in")
    def test_unmatched_email_falls_back_to_reporting_manager(self):
        pk = self._submit()
        self.assertEqual(self._chain(pk)[2], self.rm3.id)

    def test_inactive_approver_is_not_routed_to(self):
        self.principal.set_status(Employee.Status.INACTIVE)
        pk = self._submit()
        self.assertEqual(self._chain(pk)[2], self.rm3.id)

    def test_hr_final_approval_issues_letters_for_the_employee(self):
        pk = self._submit()
        self._decide(self.m1, pk, 1)
        self._decide(self.m2, pk, 2)
        data = self._decide(self.principal, pk, 3)
        self.assertEqual(data["status"], "IN_REVIEW")

        mail.outbox.clear()
        data = self._decide(self.hr, pk, 4)

        self.assertEqual(data["status"], "COMPLETED")
        self.assertTrue(data["relieving_letter_no"].startswith("REL-JDSD-"))
        self.assertTrue(data["experience_letter_no"].startswith("EXP-JDSD-"))
        self.assertEqual(data["last_working_date_approved"], "2026-10-31")

        app = RelievingApplication.objects.get(pk=pk)
        self.assertEqual(app.finalized_by, self.hr.user_account)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.INACTIVE)
        self.assertEqual(len(mail.outbox), 2)  # relieving + experience

        # The employee can open their letter immediately.
        r = self._client(self.emp).get(
            f"/api/hr/relieving/{pk}/relieving-letter.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_approval_before_final_level_does_not_issue_letters(self):
        pk = self._submit()
        self._decide(self.m1, pk, 1)
        r = self._client(self.emp).get(
            f"/api/hr/relieving/{pk}/relieving-letter.pdf")
        self.assertEqual(r.status_code, 400)
