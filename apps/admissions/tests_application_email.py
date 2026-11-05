"""First submit of the public application form sends two mails: the
student copy via MSG91 (`application_submitted_3`) and the office copy
with the form PDF to the campus acknowledgement inbox over SMTP."""

from unittest import mock

from django.core import mail
from django.test import override_settings

from apps.admissions.models import Student
from apps.admissions.services_application_email import campus_inbox_for
from apps.admissions.tests_required_fields import RequiredFixture
from apps.master.models import Campus
from apps.notifications.models import NotificationDispatchLog

INBOXES = {
    "BLR": "acknowledgement.bengaluru@jdinstitute.edu.in",
    "GOA": "acknowledgement.goa@jdinstitute.edu.in",
}

MSG91_OK = (True, '{"status": "success"}')


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
    APPLICATION_ACK_CAMPUS_INBOXES=INBOXES,
    OPERATIONS_INBOX="",
    # A developer .env may point jdindia.com at a real Zoho SMTP.
    EMAIL_SMTP_BY_DOMAIN={},
)
@mock.patch("apps.notifications.msg91.send_msg91_template", return_value=MSG91_OK)
class ApplicationAcknowledgementTests(RequiredFixture):

    def test_first_submit_msg91_to_student_pdf_to_campus(self, msg91):
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        student = Student.objects.get(lead_origin=self.lead)

        # Student copy — MSG91 template with the four variables.
        msg91.assert_called_once()
        k = msg91.call_args.kwargs
        self.assertEqual(k["template_name"], "application_submitted_3")
        self.assertEqual(k["recipient_email"], "asha@example.com")
        v = k["variables"]
        self.assertEqual(v["Student_Name"], student.student_name)
        self.assertEqual(v["Application_ID"], student.application_form_id)
        self.assertEqual(v["Course_Name"], student.program.name)
        self.assertRegex(v["Submission_Date"], r"^\d{2}-\d{2}-\d{4}$")

        # Office copy — SMTP with the PDF, to the campus inbox only.
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertEqual(m.cc, [])
        self.assertIn(student.application_form_id, m.subject)
        name, content, mimetype = m.attachments[0]
        self.assertEqual(name, f"Application-{student.application_form_id}.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        S = NotificationDispatchLog.Status
        self.assertEqual(NotificationDispatchLog.objects.get(
            template_key="admissions.form_submitted.email").status, S.SENT)
        self.assertEqual(NotificationDispatchLog.objects.get(
            template_key="admissions.application_submitted.email").status, S.SENT)

    def test_resubmit_is_silent(self, msg91):
        self.client.post(self.url, self.payload())
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(self.url, self.payload(father_occupation="Doctor"))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(msg91.call_count, 1)

    def test_campus_inbox_lookup_is_by_code(self, msg91):
        self.assertEqual(campus_inbox_for(Campus(code="goa")),
                         "acknowledgement.goa@jdinstitute.edu.in")
        self.assertEqual(campus_inbox_for(Campus(code="HYD")), "")

    def test_campus_without_inbox_still_mails_the_student(self, msg91):
        self.campus.code = "HYD"
        self.campus.save(update_fields=["code"])
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        msg91.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(OPERATIONS_INBOX="ops@jdinstitute.edu.in")
    def test_operations_inbox_is_cced_on_office_copy(self, msg91):
        self.client.post(self.url, self.payload())
        m = mail.outbox[0]
        self.assertEqual(m.to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertEqual(m.cc, ["ops@jdinstitute.edu.in"])
