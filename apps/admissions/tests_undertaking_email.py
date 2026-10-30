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
