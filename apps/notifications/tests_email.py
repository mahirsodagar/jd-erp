"""The single ZeptoMail transport: fixed From, per-trigger Reply-To,
placeholder rendering that survives HTML templates."""

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from apps.notifications.email import html_to_text, resolve_from_email, send_email
from apps.notifications.reply_to import resolve_reply_to
from apps.notifications.services import _looks_html, _render


@override_settings(
    EMAIL_DEFAULT_REPLY_TO="admin.a@jdinstitute.edu.in",
    LEAVES_HR_INBOX="leave@jdinstitute.edu.in",
    PRINCIPAL_INBOX="principal@jdinstitute.edu.in",
    FEE_RECEIPT_CAMPUS_INBOXES={"BLR": "dkul.receipts@jdinstitute.edu.in", "HYD": ""},
    APPLICATION_ACK_CAMPUS_INBOXES={"BLR": "acknowledgement.bengaluru@jdinstitute.edu.in"},
    EMAIL_REPLY_TO_POLICY={
        "leaves.application_employee.email": "HR_LEAVE",
        "fees.receipt.email": "CAMPUS_RECEIPTS",
        "lead.application_link.email": "CAMPUS_ADMISSIONS",
        "hr.relieving.letter.email": "PRINCIPAL",
        "student_leaves.applied.email": "CONTEXT",
        "some.literal.email": "desk@example.com",
    },
)
class ResolveReplyToTests(SimpleTestCase):
    def test_explicit_context_wins(self):
        self.assertEqual(
            resolve_reply_to("fees.receipt.email",
                             {"reply_to": "counsellor@example.com", "campus_code": "BLR"}),
            "counsellor@example.com",
        )

    def test_department_token(self):
        self.assertEqual(resolve_reply_to("leaves.application_employee.email"),
                         "leave@jdinstitute.edu.in")
        self.assertEqual(resolve_reply_to("hr.relieving.letter.email"),
                         "principal@jdinstitute.edu.in")

    def test_campus_tokens_read_the_campus_code(self):
        self.assertEqual(resolve_reply_to("fees.receipt.email", {"campus_code": "blr"}),
                         "dkul.receipts@jdinstitute.edu.in")
        self.assertEqual(resolve_reply_to("lead.application_link.email", {"campus_code": "BLR"}),
                         "acknowledgement.bengaluru@jdinstitute.edu.in")
        # Campus with no inbox → default.
        self.assertEqual(resolve_reply_to("fees.receipt.email", {"campus_code": "HYD"}),
                         "admin.a@jdinstitute.edu.in")

    def test_literal_address_and_fallbacks(self):
        self.assertEqual(resolve_reply_to("some.literal.email"), "desk@example.com")
        self.assertEqual(resolve_reply_to("student_leaves.applied.email"),
                         "admin.a@jdinstitute.edu.in")
        self.assertEqual(resolve_reply_to("unknown.key"), "admin.a@jdinstitute.edu.in")
        self.assertEqual(resolve_reply_to(""), "admin.a@jdinstitute.edu.in")


class RenderTests(SimpleTestCase):
    def test_single_and_double_braces(self):
        out = _render("Hi {name}, {{ Course_Name }} / {{Course_Name}}",
                      {"name": "Asha", "Course_Name": "B.Des"})
        self.assertEqual(out, "Hi Asha, B.Des / B.Des")

    def test_css_braces_and_unknown_placeholders_survive(self):
        tpl = "<style>.x{color:red} p { margin:0 }</style><p>{name} {missing}</p>"
        self.assertEqual(_render(tpl, {"name": "A"}),
                         "<style>.x{color:red} p { margin:0 }</style><p>A {missing}</p>")

    def test_none_renders_blank(self):
        self.assertEqual(_render("[{x}]", {"x": None}), "[]")

    def test_html_detection(self):
        self.assertTrue(_looks_html("  <!doctype html><html>"))
        self.assertTrue(_looks_html("<p>Hi</p>"))
        self.assertFalse(_looks_html("Dear {name},"))

    def test_html_to_text_keeps_link_urls(self):
        text = html_to_text(
            '<p><a href="https://x.test/apply?a=1&amp;b=2" style="x">Apply\n  now</a></p>'
            '<p><a href="https://x.test/">https://x.test/</a></p>'
            '<p><a href="#top">skip</a></p>'
        )
        self.assertEqual(
            text.split("\n\n"),
            ["Apply now (https://x.test/apply?a=1&b=2)", "https://x.test/", "skip"],
        )

    def test_html_to_text(self):
        text = html_to_text("<html><head><style>p{}</style></head><body>"
                            "<p>Dear&nbsp;Asha,</p><p>Pay <b>now</b></p></body></html>")
        self.assertEqual(text, "Dear Asha,\n\nPay now")


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    DEFAULT_FROM_NAME="JD Institute",
    EMAIL_DEFAULT_REPLY_TO="admin.a@jdinstitute.edu.in",
)
class SendEmailTests(TestCase):
    def test_from_is_always_the_noreply_sender(self):
        self.assertEqual(resolve_from_email(), "JD Institute <no-reply@dkul.in>")
        ok, detail = send_email(recipient="a@example.com", subject="S", body="B")
        self.assertTrue(ok, detail)
        m = mail.outbox[0]
        self.assertEqual(m.from_email, "JD Institute <no-reply@dkul.in>")
        self.assertEqual(m.reply_to, ["admin.a@jdinstitute.edu.in"])

    @override_settings(DEFAULT_FROM_EMAIL="JD Communications <no-reply@dkul.in>")
    def test_display_name_in_setting_is_kept(self):
        self.assertEqual(resolve_from_email(), "JD Communications <no-reply@dkul.in>")

    def test_explicit_reply_to_cc_and_attachments(self):
        ok, _ = send_email(
            recipient="a@example.com, b@example.com", cc="c@example.com,a@example.com",
            subject="S", body="B", reply_to="hr@example.com",
            attachments=[("x.pdf", b"%PDF-1", "application/pdf")],
        )
        self.assertTrue(ok)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["a@example.com", "b@example.com"])
        self.assertEqual(m.cc, ["c@example.com", "a@example.com"])
        self.assertEqual(m.reply_to, ["hr@example.com"])
        self.assertEqual(m.attachments[0][0], "x.pdf")

    def test_html_body_gets_a_text_alternative(self):
        ok, _ = send_email(recipient="a@example.com", subject="S",
                           body="<p>Hello <b>there</b></p>", is_html=True)
        self.assertTrue(ok)
        m = mail.outbox[0]
        self.assertEqual(m.body, "Hello there")
        self.assertEqual(m.alternatives[0][1], "text/html")
        self.assertIn("<b>there</b>", m.alternatives[0][0])

    def test_no_recipient(self):
        ok, detail = send_email(recipient="", subject="S", body="B")
        self.assertFalse(ok)
        self.assertIn("recipient", detail)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    EMAIL_DEFAULT_REPLY_TO="admin.a@jdinstitute.edu.in",
)
class ClientHtmlTemplateTests(TestCase):
    """The client's ex-MSG91 HTML (apps/notifications/email_html/) is the
    body of the template row and renders through the dispatcher."""

    def test_application_link_html_renders_as_multipart(self):
        from apps.notifications.email_html import load_html
        from apps.notifications.models import (
            NotificationDispatchLog, NotificationTemplate,
        )
        from apps.notifications.services import queue_notification

        key = "lead.application_link.email"
        row = NotificationTemplate.objects.get(key=key)   # from migration 0013
        self.assertEqual(row.body_template, load_html(key))
        self.assertTrue(_looks_html(row.body_template))

        log = queue_notification(
            template_key=key, recipient="asha@example.com",
            context={"Student_Name": "Asha", "Course_Name": "B.Des Fashion",
                     "Application_Form_Link": "https://x.test/#/apply/tok",
                     "reply_to": "counsellor@jdinstitute.edu.in"},
        )
        self.assertEqual(log.status, NotificationDispatchLog.Status.SENT, log.error)
        m = mail.outbox[-1]
        self.assertEqual(m.subject, "JD Institute Application Form Link")
        self.assertEqual(m.reply_to, ["counsellor@jdinstitute.edu.in"])
        html, mime = m.alternatives[0]
        self.assertEqual(mime, "text/html")
        self.assertIn("<strong>Asha</strong>", html)
        self.assertIn("<strong>B.Des Fashion</strong>", html)
        self.assertIn('href="https://x.test/#/apply/tok"', html)
        self.assertNotIn("{{", html)
        # Plain-text part carries the same facts for text-only clients.
        self.assertIn("Dear Asha,", m.body)
        self.assertIn("Apply", m.body)

    def test_every_html_file_is_loaded_and_renders(self):
        """Each file in email_html/ must back its row (a migration loaded
        it) and render through the dispatcher with no placeholder left."""
        from apps.notifications import email_html
        from apps.notifications.email_html import load_html
        from apps.notifications.models import (
            NotificationDispatchLog, NotificationTemplate,
        )
        from apps.notifications.services import (
            _PLACEHOLDER_RE, queue_notification,
        )

        files = sorted(email_html._DIR.glob("*.html"))
        self.assertTrue(files)
        for path in files:
            key = path.name[:-len(".html")]
            with self.subTest(key=key):
                row = NotificationTemplate.objects.get(key=key)
                self.assertEqual(row.body_template, load_html(key))
                names = {(m.group(1) or m.group(2))
                         for m in _PLACEHOLDER_RE.finditer(
                             row.subject_template + row.body_template)}
                ctx = {n: f"V_{n}" for n in names}
                log = queue_notification(template_key=key,
                                         recipient="t@example.com", context=ctx)
                self.assertEqual(log.status, NotificationDispatchLog.Status.SENT,
                                 log.error)
                m = mail.outbox[-1]
                html, mime = m.alternatives[0]
                self.assertEqual(mime, "text/html")
                self.assertNotIn("{{", html)
                for n in names:
                    self.assertIn(f"V_{n}", html)
                    self.assertIn(f"V_{n}", m.body)   # text fallback too
