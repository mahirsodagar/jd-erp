"""First submit of the public application form emails the form PDF to
the student with the campus acknowledgement inbox in CC."""

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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
    APPLICATION_ACK_CAMPUS_INBOXES=INBOXES,
    OPERATIONS_INBOX="",
    # A developer .env may point jdindia.com at a real Zoho SMTP.
    EMAIL_SMTP_BY_DOMAIN={},
)
class ApplicationAcknowledgementTests(RequiredFixture):

    def test_first_submit_mails_student_and_campus_with_pdf(self):
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        student = Student.objects.get(lead_origin=self.lead)

        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["asha@example.com"])
        self.assertEqual(m.cc, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertIn(student.application_form_id, m.subject)
        name, content, mimetype = m.attachments[0]
        self.assertEqual(name, f"Application-{student.application_form_id}.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        log = NotificationDispatchLog.objects.get(
            template_key="admissions.form_submitted.email",
        )
        self.assertEqual(log.status, NotificationDispatchLog.Status.SENT)

    def test_resubmit_is_silent(self):
        self.client.post(self.url, self.payload())
        self.assertEqual(len(mail.outbox), 1)
        r = self.client.post(self.url, self.payload(father_occupation="Doctor"))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(mail.outbox), 1)

    def test_campus_inbox_lookup_is_by_code(self):
        self.assertEqual(campus_inbox_for(Campus(code="goa")),
                         "acknowledgement.goa@jdinstitute.edu.in")
        self.assertEqual(campus_inbox_for(Campus(code="HYD")), "")

    def test_campus_without_inbox_still_mails_the_student(self):
        self.campus.code = "HYD"
        self.campus.save(update_fields=["code"])
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, [])
