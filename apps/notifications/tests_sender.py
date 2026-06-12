"""Tests for per-trigger sender-domain routing (apps.notifications.sender)."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.notifications.email import send_email
from apps.notifications.sender import is_diploma, resolve_sender, transport_for


POLICY = {
    "lead.fee_link.email": "COURSE",
    "student.portal_credentials.email": "PORTAL",
    "hr.relieving.letter.email": "HR",
    "tasks.assigned.email": None,  # no policy → provider default
}

BY_DOMAIN = {
    "mail.jdinstitute.com": "admin@mail.jdinstitute.com",
    "jdinstitute.edu.in": "admin.a@jdinstitute.edu.in",
    # jdindia.com intentionally absent → not yet a live sender
}


@override_settings(
    EMAIL_SENDER_DOMAIN_POLICY=POLICY,
    EMAIL_SENDER_BY_DOMAIN=BY_DOMAIN,
    EMAIL_DOMAIN_DIPLOMA="jdinstitute.edu.in",
    EMAIL_DOMAIN_DEGREE="jdindia.com",
    EMAIL_DOMAIN_PORTAL="mail.jdinstitute.com",
    EMAIL_DOMAIN_HR="jdinstitute.edu.in",
)
class ResolveSenderTests(TestCase):
    def test_diploma_detection(self):
        self.assertTrue(is_diploma("Diploma"))
        self.assertTrue(is_diploma("  pg diploma in design "))
        self.assertFalse(is_diploma("B.Des"))
        self.assertFalse(is_diploma(""))
        self.assertFalse(is_diploma(None))

    def test_course_policy_diploma_routes_to_edu_in(self):
        s = resolve_sender("lead.fee_link.email", degree_type="Diploma")
        self.assertEqual(s.domain, "jdinstitute.edu.in")
        self.assertEqual(s.from_email, "admin.a@jdinstitute.edu.in")
        self.assertTrue(s.is_live)

    def test_course_policy_degree_routes_to_jdindia_but_not_live(self):
        # jdindia.com has no verified From yet → resolved but not live,
        # so the dispatcher falls back to the provider default.
        s = resolve_sender("lead.fee_link.email", degree_type="B.Des")
        self.assertEqual(s.domain, "jdindia.com")
        self.assertEqual(s.from_email, "")
        self.assertFalse(s.is_live)

    def test_portal_policy_fixed_domain(self):
        s = resolve_sender("student.portal_credentials.email", degree_type="Diploma")
        self.assertEqual(s.domain, "mail.jdinstitute.com")
        self.assertTrue(s.is_live)

    def test_hr_policy_fixed_domain(self):
        s = resolve_sender("hr.relieving.letter.email")
        self.assertEqual(s.domain, "jdinstitute.edu.in")
        self.assertTrue(s.is_live)

    def test_unpoliced_trigger_returns_none(self):
        self.assertIsNone(resolve_sender("tasks.assigned.email"))
        self.assertIsNone(resolve_sender("some.unknown.email"))


@override_settings(
    EMAIL_SMTP_BY_DOMAIN={"jdindia.com": {"host": "smtp.zoho.com"}},
    MSG91_DOMAIN="mail.jdinstitute.com",
)
class TransportForTests(TestCase):
    def test_jdindia_uses_dedicated_smtp(self):
        kind, cfg = transport_for("jdindia.com")
        self.assertEqual(kind, "smtp")
        self.assertEqual(cfg, {"host": "smtp.zoho.com"})

    def test_mail_jdinstitute_uses_msg91(self):
        kind, cfg = transport_for("mail.jdinstitute.com")
        self.assertEqual(kind, "msg91")
        self.assertIsNone(cfg)

    def test_edu_in_uses_default_smtp(self):
        kind, cfg = transport_for("jdinstitute.edu.in")
        self.assertEqual(kind, "smtp")
        self.assertIsNone(cfg)


class DedicatedSmtpTests(TestCase):
    """A per-domain SMTP config opens its own connection + From-address."""

    SMTP = {
        "host": "smtp.jdindia.example",
        "port": 587,
        "username": "noreply@jdindia.com",
        "password": "secret",
        "use_tls": True,
        "use_ssl": False,
        "from_email": "noreply@jdindia.com",
    }

    @patch("apps.notifications.email.get_connection")
    def test_send_email_uses_dedicated_connection_and_from(self, mock_get_conn):
        sent = {}

        class FakeMsg:
            def __init__(self, **kw):
                sent.update(kw)

            def send(self, fail_silently=False):
                return 1

        with patch("apps.notifications.email.EmailMessage", FakeMsg):
            ok, _ = send_email(
                recipient="student@example.com", subject="Hi", body="x",
                smtp=self.SMTP,
            )

        self.assertTrue(ok)
        # Opened a connection with the domain's credentials.
        _, kw = mock_get_conn.call_args
        self.assertEqual(kw["host"], "smtp.jdindia.example")
        self.assertEqual(kw["username"], "noreply@jdindia.com")
        # From-address derives from the SMTP config (wrapped w/ display name).
        self.assertIn("noreply@jdindia.com", sent["from_email"])
        self.assertIs(sent["connection"], mock_get_conn.return_value)


class SmtpEgressDowngradeTests(TestCase):
    """When SMTP egress is off (PA free), SMTP-routed triggers with an
    MSG91 template downgrade to MSG91 instead of failing to connect."""

    POLICY = {"lead.fee_link.email": "COURSE"}

    @override_settings(
        EMAIL_SMTP_OUTBOUND_ENABLED=False,
        EMAIL_SENDER_DOMAIN_POLICY=POLICY,
        EMAIL_DOMAIN_DEGREE="jdindia.com",
        EMAIL_DOMAIN_DIPLOMA="jdinstitute.edu.in",
        EMAIL_SMTP_BY_DOMAIN={},
        MSG91_DOMAIN="mail.jdinstitute.com",
        MSG91_EMAIL_TEMPLATES={"lead.fee_link.email": "lead_fee_link"},
    )
    @patch("apps.notifications.msg91.send_msg91_template", return_value=(True, "ok"))
    def test_downgrades_to_msg91_with_default_sender(self, mock_msg91):
        from apps.notifications.services import _send_email

        class T:  # minimal stand-in for a NotificationTemplate row
            key = "lead.fee_link.email"

        ok, _ = _send_email(T(), "lead@example.com", "", "Subj", "Body", {})
        self.assertTrue(ok)
        mock_msg91.assert_called_once()
        # Downgraded send must NOT spoof a course domain as the MSG91
        # From — it uses MSG91's configured default sender.
        _, kw = mock_msg91.call_args
        self.assertNotIn("domain", kw)
        self.assertEqual(kw["template_name"], "lead_fee_link")

    @override_settings(
        EMAIL_SMTP_OUTBOUND_ENABLED=True,
        EMAIL_SENDER_DOMAIN_POLICY=POLICY,
        EMAIL_DOMAIN_DEGREE="jdindia.com",
        EMAIL_DOMAIN_DIPLOMA="jdinstitute.edu.in",
        EMAIL_SMTP_BY_DOMAIN={},
        MSG91_DOMAIN="mail.jdinstitute.com",
        MSG91_EMAIL_TEMPLATES={"lead.fee_link.email": "lead_fee_link"},
    )
    @patch("apps.notifications.msg91.send_msg91_template", return_value=(True, "ok"))
    @patch("apps.notifications.email.send_email", return_value=(True, "sent=1"))
    def test_smtp_enabled_uses_smtp_not_msg91(self, mock_smtp, mock_msg91):
        from apps.notifications.services import _send_email

        class T:
            key = "lead.fee_link.email"

        ok, _ = _send_email(T(), "lead@example.com", "", "Subj", "Body", {})
        self.assertTrue(ok)
        mock_smtp.assert_called_once()
        mock_msg91.assert_not_called()
