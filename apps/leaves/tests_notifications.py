"""Leave / comp-off mail is actually delivered, not just logged."""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from apps.leaves.models import EmailDispatchLog
from apps.leaves.services.notifications import (
    TPL_COMPOFF_APPLIED, TPL_LEAVE_APPLIED, reply_to_for, send_email_now,
)


SEND_KW = dict(
    template=TPL_LEAVE_APPLIED,
    to="manager@jdinstitute.edu.in",
    cc="hr@jdinstitute.edu.in",
    subject="Leave application — Asha (2026-09-16)",
    body="Asha has applied for Casual Leave.",
)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    LEAVES_HR_INBOX="leave@jdinstitute.edu.in",
    EMAIL_REPLY_TO_POLICY={TPL_LEAVE_APPLIED: "HR_LEAVE", TPL_COMPOFF_APPLIED: "HR_LEAVE"},
)
class LeaveMailDeliveryTests(TestCase):

    def test_send_puts_the_message_on_the_wire(self):
        log = send_email_now(**SEND_KW)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["manager@jdinstitute.edu.in"])
        self.assertEqual(msg.cc, ["hr@jdinstitute.edu.in"])
        self.assertEqual(msg.subject, SEND_KW["subject"])
        # From is the fixed no-reply sender; replies go to the leave dept.
        self.assertIn("no-reply@dkul.in", msg.from_email)
        self.assertEqual(msg.reply_to, ["leave@jdinstitute.edu.in"])

        log.refresh_from_db()
        self.assertEqual(log.status, EmailDispatchLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)
        self.assertEqual(log.error, "")

    def test_failure_is_recorded_and_never_raises(self):
        with patch("apps.notifications.email.send_email",
                   return_value=(False, "SMTPAuthenticationError: nope")):
            log = send_email_now(**SEND_KW)

        log.refresh_from_db()
        self.assertEqual(log.status, EmailDispatchLog.Status.FAILED)
        self.assertIn("SMTPAuthenticationError", log.error)
        self.assertIsNone(log.sent_at)

    def test_leave_and_compoff_reply_to_the_leave_department(self):
        self.assertEqual(reply_to_for(TPL_LEAVE_APPLIED), "leave@jdinstitute.edu.in")
        self.assertEqual(reply_to_for(TPL_COMPOFF_APPLIED), "leave@jdinstitute.edu.in")

    def test_failed_rows_are_replayed_by_the_command(self):
        from django.core.management import call_command

        with patch("apps.notifications.email.send_email",
                   return_value=(False, "SMTPServerDisconnected")):
            send_email_now(**SEND_KW)
        self.assertEqual(mail.outbox, [])

        call_command("send_leave_emails", "--failed")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            EmailDispatchLog.objects.get().status,
            EmailDispatchLog.Status.SENT,
        )
