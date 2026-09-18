"""Relieving emails go out on apply, reject and completion (legacy parity)."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.employees.models import Department, Designation, Employee
from apps.master.models import Campus, City, Institute, State
from apps.notifications.models import NotificationDispatchLog as Log
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

    def test_completion_sends_both_letters_to_personal_mail(self):
        pk = self._submit()
        for level in (1, 2, 4):
            self._decide(pk, level, "APPROVED")
        mail.outbox.clear()

        r = self.client.post(f"/api/hr/relieving/{pk}/finalize/",
                             {"last_working_date_approved": "2026-10-31"},
                             format="json")
        self.assertEqual(r.status_code, 200, r.data)

        self.assertEqual(len(mail.outbox), 2)
        relieving, experience = mail.outbox

        self.assertEqual(relieving.to, ["asha.personal@gmail.com"])
        self.assertEqual(relieving.cc, [
            "mgr1@jdinstitute.edu.in", "mgr2@jdinstitute.edu.in",
            "mgr4@jdinstitute.edu.in", "emp1@jdinstitute.edu.in",
        ])
        (name, content, ctype), = relieving.attachments
        self.assertTrue(name.startswith("REL-JDIFT-"))
        self.assertEqual(ctype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        self.assertEqual(experience.to, ["asha.personal@gmail.com"])
        self.assertEqual(experience.cc, ["mgr4@jdinstitute.edu.in"])
        self.assertTrue(experience.attachments[0][0].startswith("EXP-JDIFT-"))

        for key in (TPL_RELIEVING_LETTER, TPL_EXPERIENCE_LETTER):
            self.assertEqual(Log.objects.get(template_key=key).status,
                             Log.Status.SENT)

    def test_mail_failure_does_not_break_the_workflow(self):
        with patch("apps.notifications.email.send_email",
                   return_value=(False, "SMTPServerDisconnected: gone")):
            self._submit()

        log = Log.objects.get(template_key=TPL_APPLICATION)
        self.assertEqual(log.status, Log.Status.FAILED)
        self.assertIn("SMTPServerDisconnected", log.error)
