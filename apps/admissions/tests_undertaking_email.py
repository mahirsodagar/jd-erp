"""Sending the undertaking copies the campus undertaking inbox."""

from types import SimpleNamespace

from django.core import mail
from django.test import TestCase, override_settings

from apps.admissions.services_undertaking import (
    send_undertaking, undertaking_campus_inbox_for,
)
from apps.admissions.tests_undertaking_pdf import _fixture, _installment
from apps.master.models import Campus

INBOXES = {
    "BNG": "undertaking.bangalore@jdinstitute.edu.in",
    "GOA": "undertaking.goa@jdinstitute.edu.in",
}
STAFF = SimpleNamespace(full_name="Counsellor One", username="c1",
                        email="c1@jdinstitute.edu.in")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="JD Communications <admin.a@jdinstitute.edu.in>",
    UNDERTAKING_CAMPUS_INBOXES=INBOXES,
)
class UndertakingEmailTests(TestCase):

    def test_student_to_staff_and_campus_cc_with_pdf(self):
        e = _fixture()
        _installment(e, 1, "10000")
        result = send_undertaking(e, requested_by=STAFF)

        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["srujan@example.com"])
        self.assertEqual(m.cc, ["c1@jdinstitute.edu.in",
                                "undertaking.bangalore@jdinstitute.edu.in"])
        self.assertEqual(m.attachments[0][2], "application/pdf")
        self.assertTrue(m.attachments[0][1].startswith(b"%PDF"))
        self.assertIn("undertaking.bangalore@jdinstitute.edu.in", result["cc"])

    def test_extra_cc_does_not_duplicate_the_campus_inbox(self):
        e = _fixture()
        _installment(e, 1, "10000")
        send_undertaking(
            e, requested_by=STAFF,
            extra_cc=["undertaking.bangalore@jdinstitute.edu.in", "x@y.com"],
        )
        cc = mail.outbox[0].cc
        self.assertEqual(cc.count("undertaking.bangalore@jdinstitute.edu.in"), 1)
        self.assertIn("x@y.com", cc)

    def test_campus_without_inbox_keeps_staff_cc_only(self):
        e = _fixture()
        e.campus.code = "HYD"
        e.campus.save(update_fields=["code"])
        _installment(e, 1, "10000")
        send_undertaking(e, requested_by=STAFF)
        self.assertEqual(mail.outbox[0].cc, ["c1@jdinstitute.edu.in"])

    def test_lookup_is_by_code(self):
        self.assertEqual(undertaking_campus_inbox_for(Campus(code="goa")),
                         "undertaking.goa@jdinstitute.edu.in")
        self.assertEqual(undertaking_campus_inbox_for(Campus(code="VJY")), "")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="JD Communications <admin.a@jdinstitute.edu.in>",
    UNDERTAKING_CAMPUS_INBOXES=INBOXES,
    # Fixture institute code is "JDI" — opt it in to the MSG91 template.
    UNDERTAKING_MSG91_INSTITUTES=["JDI"],
)
class UndertakingMsg91Tests(TestCase):
    """Opted-in institutes send MSG91 `undertaking_institute` with the PDF
    attached; a MSG91 failure falls back to the SMTP mail."""

    def _send(self, ret):
        from unittest import mock
        e = _fixture()
        _installment(e, 1, "10000")
        with mock.patch("apps.notifications.msg91.send_msg91_template",
                        return_value=ret) as m:
            result = send_undertaking(e, requested_by=STAFF)
        return e, m, result

    def test_msg91_with_pdf_attachment(self):
        from apps.notifications.models import NotificationDispatchLog as L
        e, m, result = self._send((True, '{"status":"success"}'))
        self.assertEqual(result["transport"], "msg91")
        self.assertEqual(len(mail.outbox), 0)
        k = m.call_args.kwargs
        self.assertEqual(k["template_name"], "undertaking_institute")
        self.assertEqual(k["recipient_email"], "srujan@example.com")
        self.assertEqual(k["cc"], ["c1@jdinstitute.edu.in",
                                   "undertaking.bangalore@jdinstitute.edu.in"])
        self.assertEqual(k["variables"]["StudentName"], e.student.student_name)
        name, content, mimetype = k["attachments"][0]
        self.assertTrue(name.endswith(".pdf"))
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(L.objects.get(
            template_key="admissions.undertaking.email").status, L.Status.SENT)

    def test_msg91_failure_falls_back_to_smtp(self):
        _e, _m, result = self._send((False, "HTTP 400: attachment rejected"))
        self.assertEqual(result["transport"], "smtp")
        self.assertIn("attachment rejected", result["msg91_error"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(mail.outbox[0].attachments[0][1].startswith(b"%PDF"))

    @override_settings(UNDERTAKING_MSG91_INSTITUTES=["JDIFT"])
    def test_other_institutes_stay_on_smtp(self):
        _e, m, result = self._send((True, "ok"))
        m.assert_not_called()
        self.assertEqual(result["transport"], "smtp")
        self.assertEqual(len(mail.outbox), 1)


class Msg91AttachmentPayloadTests(TestCase):
    def test_attachment_is_base64_data_uri(self):
        import json
        from apps.notifications.msg91 import send_msg91_template
        ok, body = send_msg91_template(
            template_name="t", recipient_email="a@example.com",
            attachments=[("x.pdf", b"%PDF-1", "application/pdf")],
            dry_run=True)
        att = json.loads(body)["attachments"][0]
        self.assertEqual(att, {"fileName": "x.pdf",
                               "file": "data:application/pdf;base64,JVBERi0x"})
