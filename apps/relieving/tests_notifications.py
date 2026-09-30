"""Relieving emails go out on apply, reject and completion (legacy parity);
the experience letter goes out from HR's own button. Also covers HR's
direct accept."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.employees.models import Department, Designation, Employee
from apps.master.models import Campus, City, Institute, State
from apps.notifications.models import NotificationDispatchLog as Log
from apps.relieving.models import RelievingApplication
from apps.relieving.notifications import (
    TPL_APPLICATION, TPL_EXPERIENCE_LETTER, TPL_REJECTED, TPL_RELIEVING_LETTER,
)


def make_employee(code, *, institute, campus, email_alternate="", **extra):
    state, _ = State.objects.get_or_create(name="Karnataka", code="KA")
    city, _ = City.objects.get_or_create(name="Bengaluru", state=state)
    desig, _ = Designation.objects.get_or_create(name="Faculty")
    dept, _ = Department.objects.get_or_create(name="Design")
    return Employee.objects.create(
        emp_code=code, first_name=code.title(), dob=date(1990, 1, 1),
        nationality="INDIAN", blood_group="A+", gender="F",
        employment_type=1,
        date_of_appointment=date(2020, 1, 1),
        date_of_joining=date(2020, 1, 1),
        designation=desig, department=dept,
        campus=campus, institute=institute,
        current_address="1 St", current_city=city, current_state=state,
        permanent_address="1 St", permanent_city=city, permanent_state=state,
        mobile_primary="9000000000",
        email_primary=f"{code.lower()}@jdinstitute.edu.in",
        email_alternate=email_alternate,
        **extra,
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="JD Communications <admin.a@jdinstitute.edu.in>",
    # Route purely by reporting managers here; the fixed L3/L4 approvers
    # have their own tests in tests_workflow.
    RELIEVING_L3_APPROVER_EMAIL="",
    RELIEVING_L4_APPROVER_EMAIL="",
)
class RelievingEmailTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=inst, campus=campus)
        cls.m1 = make_employee("MGR1", **kw)
        cls.m2 = make_employee("MGR2", **kw)
        cls.m4 = make_employee("MGR4", **kw)  # level 3 left unset → SKIPPED
        cls.emp = make_employee(
            "EMP1", email_alternate="asha.personal@gmail.com",
            reporting_manager_1=cls.m1, reporting_manager_2=cls.m2,
            reporting_manager_4=cls.m4, **kw,
        )
        cls.admin = get_user_model().objects.create_superuser(
            "hradmin", "hr@jdinstitute.edu.in", "x",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _submit(self):
        r = self.client.post("/api/hr/relieving/", {
            "employee": self.emp.id,
            "reason": "Relocating to another city.",
            "last_working_date_requested": "2026-10-31",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data["id"]

    def _decide(self, pk, level, decision, remarks=""):
        r = self.client.post(f"/api/hr/relieving/{pk}/decide/{level}/",
                             {"decision": decision, "remarks": remarks},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)

    def test_apply_mails_first_approver_and_ccs_the_rest(self):
        pk = self._submit()

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["mgr1@jdinstitute.edu.in"])
        self.assertEqual(msg.cc, ["mgr2@jdinstitute.edu.in",
                                  "mgr4@jdinstitute.edu.in"])
        self.assertIn("Relocating to another city.", msg.body)
        self.assertIn("EMP1", msg.body)

        log = Log.objects.get(template_key=TPL_APPLICATION)
        self.assertEqual(log.status, Log.Status.SENT)
        self.assertEqual(log.object_id, str(pk))

    def test_reject_mails_approvers_with_the_reason(self):
        pk = self._submit()
        mail.outbox.clear()

        self._decide(pk, 1, "APPROVED")
        self.assertEqual(mail.outbox, [])  # intermediate approval: no mail

        self._decide(pk, 2, "REJECTED", "Notice period not served.")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["mgr1@jdinstitute.edu.in"])
        self.assertIn("Rejected", msg.subject)
        self.assertIn("Notice period not served.", msg.body)
        self.assertEqual(Log.objects.get(template_key=TPL_REJECTED).status,
                         Log.Status.SENT)

    def _complete(self):
        pk = self._submit()
        for level in (1, 2, 4):
            self._decide(pk, level, "APPROVED")
        return pk

    def test_final_approval_sends_only_the_relieving_letter(self):
        pk = self._submit()
        for level in (1, 2):
            self._decide(pk, level, "APPROVED")
        mail.outbox.clear()

        self._decide(pk, 4, "APPROVED")  # final level — no HR finalize step

        self.assertEqual(len(mail.outbox), 1)
        relieving, = mail.outbox

        self.assertEqual(relieving.to, ["asha.personal@gmail.com"])
        self.assertEqual(relieving.cc, [
            "mgr1@jdinstitute.edu.in", "mgr2@jdinstitute.edu.in",
            "mgr4@jdinstitute.edu.in", "emp1@jdinstitute.edu.in",
        ])
        (name, content, ctype), = relieving.attachments
        self.assertTrue(name.startswith("REL-JDIFT-"))
        self.assertEqual(ctype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        self.assertEqual(Log.objects.get(template_key=TPL_RELIEVING_LETTER).status,
                         Log.Status.SENT)
        self.assertFalse(Log.objects.filter(
            template_key=TPL_EXPERIENCE_LETTER).exists())

    def test_hr_button_sends_experience_letter_and_can_resend(self):
        pk = self._complete()
        mail.outbox.clear()

        r = self.client.post(f"/api/hr/relieving/{pk}/send-experience-letter/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNotNone(r.data["experience_letter_sent_at"])

        experience, = mail.outbox
        self.assertEqual(experience.to, ["asha.personal@gmail.com"])
        self.assertEqual(experience.cc, ["mgr4@jdinstitute.edu.in"])
        self.assertTrue(experience.attachments[0][0].startswith("EXP-JDIFT-"))

        r = self.client.post(f"/api/hr/relieving/{pk}/send-experience-letter/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(mail.outbox), 2)

    def test_experience_letter_needs_completed_application(self):
        pk = self._submit()
        r = self.client.post(f"/api/hr/relieving/{pk}/send-experience-letter/")
        self.assertEqual(r.status_code, 400)

    def test_experience_letter_send_failure_is_reported(self):
        pk = self._complete()
        with patch("apps.notifications.email.send_email",
                   return_value=(False, "SMTPServerDisconnected: gone")):
            r = self.client.post(f"/api/hr/relieving/{pk}/send-experience-letter/")
        self.assertEqual(r.status_code, 502)
        self.assertIn("SMTPServerDisconnected", r.data["detail"])
        self.assertIsNone(
            RelievingApplication.objects.get(pk=pk).experience_letter_sent_at)

    def test_hr_accept_completes_in_one_step(self):
        pk = self._submit()
        self._decide(pk, 1, "APPROVED")
        mail.outbox.clear()

        r = self.client.post(f"/api/hr/relieving/{pk}/accept/", {
            "last_working_date_approved": "2026-10-15",
            "remarks": "Notice waived.",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "COMPLETED")
        self.assertEqual(r.data["last_working_date_approved"], "2026-10-15")
        self.assertTrue(r.data["relieving_letter_no"].startswith("REL-JDIFT-"))

        by_level = {a["level"]: a for a in r.data["approvals"]}
        self.assertEqual(by_level[1]["remarks"], "")  # decided by RM1 itself
        self.assertEqual(by_level[2]["status"], "APPROVED")
        self.assertIn("Accepted directly by HR. Notice waived.",
                      by_level[2]["remarks"])
        self.assertEqual(by_level[3]["status"], "SKIPPED")

        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.INACTIVE)
        self.assertEqual(len(mail.outbox), 1)  # relieving letter only

    def test_accept_rejected_application_fails(self):
        pk = self._submit()
        self._decide(pk, 1, "REJECTED", "No.")
        r = self.client.post(f"/api/hr/relieving/{pk}/accept/", {
            "last_working_date_approved": "2026-10-15",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_accept_needs_finalize_permission(self):
        pk = self._submit()
        self.client.force_authenticate(
            get_user_model().objects.create_user("plain", "p@x.in", "x"))
        r = self.client.post(f"/api/hr/relieving/{pk}/accept/", {
            "last_working_date_approved": "2026-10-15",
        }, format="json")
        self.assertEqual(r.status_code, 403)

    def test_mail_failure_does_not_break_the_workflow(self):
        with patch("apps.notifications.email.send_email",
                   return_value=(False, "SMTPServerDisconnected: gone")):
            self._submit()

        log = Log.objects.get(template_key=TPL_APPLICATION)
        self.assertEqual(log.status, Log.Status.FAILED)
        self.assertIn("SMTPServerDisconnected", log.error)
