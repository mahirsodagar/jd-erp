"""'Send handbook' attaches the institute's own Student Handbook PDF."""

import tempfile

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from apps.admissions.services_handbook import send_handbook_email
from apps.admissions.tests_undertaking_pdf import _fixture


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="JD Communications <admin.a@jdinstitute.edu.in>",
    MEDIA_ROOT=tempfile.mkdtemp(),
)
class HandbookEmailTests(TestCase):

    def test_attaches_the_institutes_pdf(self):
        e = _fixture()
        inst = e.student.institute
        inst.handbook_pdf.save("hb.pdf", ContentFile(b"%PDF-1.4 jdi"),
                               save=True)

        ok, msg = send_handbook_email(student=e.student)

        self.assertTrue(ok, msg)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["srujan@example.com"])
        self.assertIn("Student Handbook", m.subject)
        self.assertIn("JD Institute of Fashion Technology", m.subject)
        self.assertEqual(len(m.attachments), 1)
        name, content, ctype = m.attachments[0]
        self.assertEqual(name, "JDI_Student_Handbook.pdf")
        self.assertEqual(content, b"%PDF-1.4 jdi")
        self.assertEqual(ctype, "application/pdf")
        self.assertIn("attached", m.body)
        self.assertIn("Kuruva Srujan", m.body)

    def test_refused_when_institute_has_no_handbook(self):
        e = _fixture()
        ok, msg = send_handbook_email(student=e.student)
        self.assertFalse(ok)
        self.assertIn("No student handbook uploaded", msg)
        self.assertEqual(mail.outbox, [])

    def test_refused_without_student_email(self):
        e = _fixture()
        e.student.student_email = ""
        e.student.save(update_fields=["student_email"])
        ok, msg = send_handbook_email(student=e.student)
        self.assertFalse(ok)
        self.assertEqual(mail.outbox, [])
