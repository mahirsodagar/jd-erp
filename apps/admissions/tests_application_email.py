"""First submit of the public application form sends two mails: the
student copy (template `admissions.application_submitted.email`) and the
office copy with the form PDF to the campus acknowledgement inbox. Both
leave From no-reply@dkul.in, Reply-To the campus admissions inbox."""

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

def _office(outbox):
    return [m for m in outbox if m.attachments]


def _student(outbox):
    return [m for m in outbox if not m.attachments]


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    APPLICATION_ACK_CAMPUS_INBOXES=INBOXES,
    OPERATIONS_INBOX="",
)
class ApplicationAcknowledgementTests(RequiredFixture):

    def test_first_submit_mails_student_and_pdf_to_campus(self):
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        student = Student.objects.get(lead_origin=self.lead)
        self.assertEqual(len(mail.outbox), 2)

        # Student copy — the template with the four variables filled.
        (s,) = _student(mail.outbox)
        self.assertEqual(s.to, ["asha@example.com"])
        self.assertIn("no-reply@dkul.in", s.from_email)
        self.assertEqual(s.reply_to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertIn(student.student_name, s.body)
        self.assertIn(student.application_form_id, s.body)
        self.assertIn(student.program.name, s.body)

        # Office copy — with the PDF, to the campus inbox only.
        (m,) = _office(mail.outbox)
        self.assertEqual(m.to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertEqual(m.cc, [])
        self.assertEqual(m.reply_to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
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

    def test_resubmit_is_silent(self):
        self.client.post(self.url, self.payload())
        self.assertEqual(len(mail.outbox), 2)
        r = self.client.post(self.url, self.payload(father_occupation="Doctor"))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(mail.outbox), 2)

    def test_campus_inbox_lookup_is_by_code(self):
        self.assertEqual(campus_inbox_for(Campus(code="goa")),
                         "acknowledgement.goa@jdinstitute.edu.in")
        self.assertEqual(campus_inbox_for(Campus(code="HYD")), "")

    @override_settings(EMAIL_DEFAULT_REPLY_TO="admin.a@jdinstitute.edu.in")
    def test_campus_without_inbox_still_mails_the_student(self):
        self.campus.code = "HYD"
        self.campus.save(update_fields=["code"])
        r = self.client.post(self.url, self.payload())
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(mail.outbox), 1)
        (s,) = _student(mail.outbox)
        self.assertEqual(s.to, ["asha@example.com"])
        # No campus inbox → the default Reply-To.
        self.assertEqual(s.reply_to, ["admin.a@jdinstitute.edu.in"])

    @override_settings(OPERATIONS_INBOX="ops@jdinstitute.edu.in")
    def test_operations_inbox_is_cced_on_office_copy(self):
        self.client.post(self.url, self.payload())
        (m,) = _office(mail.outbox)
        self.assertEqual(m.to, ["acknowledgement.bengaluru@jdinstitute.edu.in"])
        self.assertEqual(m.cc, ["ops@jdinstitute.edu.in"])
