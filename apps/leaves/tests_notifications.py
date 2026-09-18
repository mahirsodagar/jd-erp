"""Leave / comp-off mail is actually delivered, not just logged."""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from apps.leaves.models import EmailDispatchLog
from apps.leaves.services.notifications import (
    TPL_COMPOFF_APPLIED, TPL_LEAVE_APPLIED, _transport_for, send_email_now,
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
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
    EMAIL_SENDER_DOMAIN_POLICY={
        TPL_LEAVE_APPLIED: "HR", TPL_COMPOFF_APPLIED: "HR",
    },
    EMAIL_SENDER_BY_DOMAIN={"jdinstitute.edu.in": "admin.a@jdinstitute.edu.in"},
    EMAIL_SMTP_BY_DOMAIN={},
    EMAIL_DOMAIN_HR="jdinstitute.edu.in",
    DEFAULT_FROM_EMAIL="JD Communications <admin.a@jdinstitute.edu.in>",
)
class LeaveMailDeliveryTests(TestCase):

    def test_send_puts_the_message_on_the_wire(self):
        log = send_email_now(**SEND_KW)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["manager@jdinstitute.edu.in"])
        self.assertEqual(msg.cc, ["hr@jdinstitute.edu.in"])
        self.assertEqual(msg.subject, SEND_KW["subject"])

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

    def test_leave_mail_sends_from_the_hr_domain(self):
        smtp_cfg, from_email = _transport_for(TPL_LEAVE_APPLIED)
        self.assertIsNone(smtp_cfg)  # HR domain uses the default backend
        self.assertEqual(from_email, "admin.a@jdinstitute.edu.in")

        # Comp-off follows the same policy as leave.
        self.assertEqual(_transport_for(TPL_COMPOFF_APPLIED)[1], from_email)

    @override_settings(EMAIL_SMTP_OUTBOUND_ENABLED=False)
    def test_host_without_smtp_egress_keeps_the_mail_queued(self):
        log = send_email_now(**SEND_KW)

        self.assertEqual(mail.outbox, [])
        log.refresh_from_db()
        self.assertEqual(log.status, EmailDispatchLog.Status.QUEUED)

    @override_settings(EMAIL_SMTP_OUTBOUND_ENABLED=False)
    def test_queued_rows_are_drained_by_the_replay_command(self):
        from django.core.management import call_command

        send_email_now(**SEND_KW)
        self.assertEqual(mail.outbox, [])

        with override_settings(EMAIL_SMTP_OUTBOUND_ENABLED=True):
            call_command("send_leave_emails")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            EmailDispatchLog.objects.get().status,
            EmailDispatchLog.Status.SENT,
        )
