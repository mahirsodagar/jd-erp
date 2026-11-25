"""System e-mail templates: registry defaults, resolution (institute →
global → default), strict lint, layout wrapping, dispatch through the
template, and the Communication → System Emails API."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.master.models import Campus, Institute
from apps.roles.models import Permission, Role

from . import registry, templating
from .context import institute_vars, lead_vars
from .models import (
    EmailLayout, NotificationDispatchLog, SystemEmailTemplate,
    SystemEmailTemplateVersion,
)
from .services import queue_notification, send_system_email

MAIL = dict(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    EMAIL_DEFAULT_REPLY_TO="webmaster@dkul.in",
)


class RegistryTests(TestCase):
    def test_every_default_lints_clean(self):
        for key, trig in registry.TRIGGERS.items():
            self.assertTrue(trig.body(), key)
            self.assertEqual(templating.lint(trig, trig.default_subject, trig.body()), [], key)

    def test_client_html_aliases_cover_their_placeholders(self):
        # The shipped HTML uses old names; every one must map to a canonical var.
        for key, trig in registry.TRIGGERS.items():
            used = templating.placeholders(trig.body()) | templating.placeholders(trig.default_subject)
            for name in used:
                self.assertIn(name, trig.allowed_names(), f"{key}: {name}")

    def test_lint_flags_unknown_names_only(self):
        trig = registry.get("tasks.assigned.email")
        self.assertEqual(
            templating.lint(trig, "Hi {{Assignee_Name}}", "<p>{{Nope}} {{Institute_Name}} {Also_Bad}</p>"),
            ["Also_Bad", "Nope"],
        )

    def test_example_context_fills_aliases(self):
        trig = registry.get("student.portal_credentials.email")
        ctx = registry.example_context(trig)
        self.assertEqual(ctx["name"], ctx["Student_Name"])
        self.assertEqual(ctx["login_url"], ctx["Login_Url"])


@override_settings(**MAIL)
class ResolutionAndRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jdift = Institute.objects.create(name="JD Institute of Fashion Technology", code="JDIFT",
                                             address="Line 1\nLine 2", phone="080-1", email="info@jd.test")
        cls.jdsd = Institute.objects.create(name="JD School of Design", code="JDSD")
        cls.user = get_user_model().objects.create_superuser(username="root", email="root@jd.test", password="x")

    def test_default_then_global_then_institute(self):
        key = "tasks.assigned.email"
        res = templating.resolve(key, self.jdift)
        self.assertEqual(res.source, "default")
        self.assertEqual(res.subject, registry.get(key).default_subject)

        templating.save_template(key=key, institute=None, subject="G {{Task_Name}}",
                                 body_html="<p>global</p>", user=self.user)
        self.assertEqual(templating.resolve(key, self.jdift).source, "global")
        self.assertEqual(templating.resolve(key, None).subject, "G {{Task_Name}}")

        templating.save_template(key=key, institute=self.jdift, subject="I {{Task_Name}}",
                                 body_html="<p>jdift</p>", user=self.user)
        self.assertEqual(templating.resolve(key, self.jdift).source, "institute")
        self.assertEqual(templating.resolve(key, self.jdsd).source, "global")
        # By routing code too.
        self.assertEqual(templating.resolve(key, institute_code="jdift").subject, "I {{Task_Name}}")

    def test_save_refuses_unknown_variables(self):
        with self.assertRaises(templating.TemplateLintError) as cm:
            templating.save_template(key="tasks.assigned.email", institute=None, subject="x",
                                     body_html="<p>{{Student_Name}}</p>", user=self.user)
        self.assertEqual(cm.exception.unknown, ["Student_Name"])
        self.assertFalse(SystemEmailTemplate.objects.exists())

    def test_every_save_appends_a_version_and_revert_copies_forward(self):
        key = "tasks.completed.email"
        row = templating.save_template(key=key, institute=None, subject="v1", body_html="<p>1</p>",
                                       note="first", user=self.user)
        templating.save_template(key=key, institute=None, subject="v2", body_html="<p>2</p>", user=self.user)
        self.assertEqual(list(row.versions.values_list("number", flat=True)), [2, 1])
        v1 = row.versions.get(number=1)
        templating.revert_template(row, v1, user=self.user)
        row.refresh_from_db()
        self.assertEqual(row.subject, "v1")
        self.assertEqual(row.versions.count(), 3)
        self.assertEqual(row.versions.first().note, "Reverted to v1")

    def test_reset_returns_to_default_and_keeps_history(self):
        key = "tasks.completed.email"
        row = templating.save_template(key=key, institute=None, subject="custom", body_html="<p>c</p>",
                                       reply_to="x@jd.test", user=self.user)
        self.assertTrue(templating.is_customised(row, registry.get(key)))
        templating.reset_template(key=key, institute=None, user=self.user)
        row.refresh_from_db()
        self.assertFalse(templating.is_customised(row, registry.get(key)))
        self.assertEqual(row.reply_to, "")
        self.assertEqual(row.versions.count(), 2)

    def test_layout_wraps_fragment_and_full_document(self):
        templating.save_layout(institute=None, header_html="<div id='h'>{{Institute_Name}}</div>",
                               footer_html="<div id='f'>{{Institute_Address}}</div>", user=self.user)
        ctx = {**institute_vars(self.jdift), "Task_Name": "T", "Assignee_Name": "A",
               "Creator_Name": "C", "Due_Date": "d", "Task_Description": "x"}
        built = templating.build("tasks.assigned.email", ctx)
        self.assertIn("<div id='h'>JD Institute of Fashion Technology</div>", built.html)
        self.assertIn("Line 1<br>Line 2", built.html)
        self.assertTrue(built.html.startswith("<!DOCTYPE html>"))
        # Full client document: only the <body> inner is kept, styles survive.
        doc = "<!DOCTYPE html><html><head><style>body{font-size:14px;}</style></head><body><p>X {{Task_Name}}</p></body></html>"
        templating.save_template(key="tasks.assigned.email", institute=None, subject="s",
                                 body_html=doc, user=self.user)
        built = templating.build("tasks.assigned.email", ctx)
        self.assertEqual(built.html.count("<body"), 1)
        self.assertIn("<style>body{font-size:14px;}</style>", built.html)
        self.assertIn("<p>X T</p>", built.html)
        self.assertIn("<div id='f'>", built.html)

    def test_institute_layout_beats_global_and_use_layout_false_skips_it(self):
        templating.save_layout(institute=None, header_html="GLOBAL-H", footer_html="", user=self.user)
        templating.save_layout(institute=self.jdift, header_html="JDIFT-H", footer_html="", user=self.user)
        ctx = {**institute_vars(self.jdift), "Task_Name": "T"}
        self.assertIn("JDIFT-H", templating.build("tasks.assigned.email", ctx).html)
        ctx2 = {**institute_vars(self.jdsd), "Task_Name": "T"}
        self.assertIn("GLOBAL-H", templating.build("tasks.assigned.email", ctx2).html)
        templating.save_template(key="tasks.assigned.email", institute=None, subject="s",
                                 body_html="<p>{{Task_Name}}</p>", use_layout=False, user=self.user)
        self.assertNotIn("JDIFT-H", templating.build("tasks.assigned.email", ctx).html)

    def test_full_context_fills_common_vars_from_routing_codes(self):
        Campus.objects.create(name="Goa", code="GOA", address="Panaji", phone="0832")
        trig = registry.get("tasks.assigned.email")
        ctx = templating.full_context(trig, {"institute_code": "JDIFT", "campus_code": "GOA"})
        self.assertEqual(ctx["Institute_Name"], "JD Institute of Fashion Technology")
        self.assertEqual(ctx["Campus_Name"], "Goa")
        self.assertEqual(ctx["Campus_Phone"], "0832")
        self.assertTrue(ctx["Today"])


@override_settings(**MAIL)
class DispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jdift = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.user = get_user_model().objects.create_superuser(username="root", email="root@jd.test", password="x")

    def _ctx(self):
        return {"Assignee_Name": "Asha", "Creator_Name": "Rahul", "Task_Name": "Deck",
                "Due_Date": "01-12-2026", "Task_Description": "Slides", "institute_code": "JDIFT"}

    def test_send_uses_template_reply_to_and_extra_cc_and_attachments(self):
        row = templating.save_template(
            key="tasks.assigned.email", institute=self.jdift, subject="[{{Institute_Short_Name}}] {{Task_Name}}",
            body_html="<p>Hello {{Assignee_Name}}</p>", reply_to="pm@jd.test",
            cc_extra="ops@jd.test, asha@jd.test", user=self.user,
        )
        row.attachments.create(file=SimpleUploadedFile("policy.txt", b"rules"), filename="policy.txt",
                               content_type="text/plain", size=5)
        log = send_system_email("tasks.assigned.email", recipient="asha@jd.test", context=self._ctx(),
                                attachments=[("extra.txt", b"x", "text/plain")])
        self.assertEqual(log.status, NotificationDispatchLog.Status.SENT)
        self.assertEqual(log.template_version, row.versions.first())
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.subject, "[JDIFT] Deck")
        self.assertEqual(m.reply_to, ["pm@jd.test"])
        self.assertEqual(m.cc, ["ops@jd.test"])  # recipient never CC'd to itself
        self.assertEqual(sorted(a[0] for a in m.attachments), ["extra.txt", "policy.txt"])
        html = m.alternatives[0][0]
        self.assertIn("Hello Asha", html)
        self.assertIn("Hello Asha", m.body)  # text fallback

    def test_default_reply_to_when_template_has_none(self):
        send_system_email("tasks.assigned.email", recipient="asha@jd.test", context=self._ctx())
        self.assertEqual(mail.outbox[0].reply_to, ["webmaster@dkul.in"])

    def test_queue_notification_routes_registry_keys_without_a_notification_template_row(self):
        log = queue_notification(template_key="tasks.assigned.email", recipient="asha@jd.test",
                                 context=self._ctx())
        self.assertEqual(log.status, NotificationDispatchLog.Status.SENT)
        self.assertIsNone(log.template_version)  # code default
        self.assertEqual(len(mail.outbox), 1)

    def test_scheduled_system_email_is_delivered_by_process_due(self):
        from datetime import timedelta

        from django.utils import timezone

        from .services import process_due

        sn = queue_notification(template_key="cold_drip_30", recipient="lead@jd.test",
                                context={"Student_Name": "Asha", "Program_Name": "B.Des"},
                                fire_at=timezone.now() + timedelta(hours=1))
        self.assertEqual(mail.outbox, [])
        sn.fire_at = timezone.now() - timedelta(minutes=1)
        sn.save(update_fields=["fire_at"])
        out = process_due()
        self.assertEqual(out["dispatched"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Still considering B.Des?", mail.outbox[0].subject)

    def test_lead_vars_carry_counsellor_reply_to(self):
        from apps.leads.models import Lead
        from apps.master.models import LeadSource, Program

        counsellor = get_user_model().objects.create_user(username="meera", email="meera@jd.test", password="x")
        campus = Campus.objects.create(name="Bengaluru", code="BLR")
        program = Program.objects.create(name="B.Des Fashion", code="BDF", institute=self.jdift, duration_months=36)
        source = LeadSource.objects.create(name="Website")
        lead = Lead.objects.create(name="Asha Rao", email="asha@jd.test", phone="9999999999",
                                   campus=campus, program=program, source=source, assign_to=counsellor)
        v = lead_vars(lead)
        self.assertEqual(v["First_Name"], "Asha")
        self.assertEqual(v["Program_Duration"], "3 years")
        self.assertEqual(v["Counsellor_Name"], "meera")
        self.assertEqual(v["reply_to"], "meera@jd.test")
        self.assertEqual(v["institute_code"], "JDIFT")
        self.assertEqual(v["campus_code"], "BLR")


@override_settings(**MAIL)
class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.jdift = Institute.objects.create(name="JDIFT", code="JDIFT")
        User = get_user_model()
        cls.admin = User.objects.create_superuser(username="root", email="root@jd.test", password="x")
        cls.viewer = User.objects.create_user(username="viewer", email="v@jd.test", password="x")
        cls.nobody = User.objects.create_user(username="nobody", email="n@jd.test", password="x")
        role = Role.objects.create(name="Comms viewer")
        perm, _ = Permission.objects.get_or_create(key="comms.system_email.view",
                                                   defaults={"module": "comms", "label": "view"})
        role.permissions.add(perm)
        cls.viewer.roles.add(role)

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_list_and_permissions(self):
        self.assertEqual(self._client(self.nobody).get("/api/comms/system-emails/").status_code, 403)
        r = self._client(self.viewer).get("/api/comms/system-emails/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["items"]), len(registry.TRIGGERS))
        self.assertTrue(all(not i["is_customised"] for i in r.data["items"]))
        # view-only cannot save
        r = self._client(self.viewer).put("/api/comms/system-emails/tasks.assigned.email/",
                                          {"subject": "x", "body_html": "<p>y</p>"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_save_lint_preview_history_and_reset(self):
        c = self._client(self.admin)
        url = "/api/comms/system-emails/tasks.assigned.email/"
        r = c.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["current"]["source"], "default")
        self.assertIn({"name": "Task_Name", "label": "Task title", "example": "Prepare orientation deck", "required": True},
                      r.data["variables"])

        # Unknown variable → 400 with the names.
        r = c.put(url, {"subject": "Hi {{Whoever}}", "body_html": "<p>{{Task_Name}}</p>"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["unknown_variables"], ["Whoever"])

        r = c.put(url, {"subject": "New: {{Task_Name}}", "body_html": "<p>{{Assignee_Name}}</p>",
                        "reply_to": "pm@jd.test", "cc_extra": "ops@jd.test", "note": "tone"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["current"]["is_customised"])
        self.assertEqual(r.data["current"]["source"], "global")
        self.assertEqual(r.data["versions"][0]["note"], "tone")

        # Preview renders unsaved text with example values through the layout.
        r = c.post(url + "preview/", {"subject": "P {{Task_Name}}", "body_html": "<p>{{Creator_Name}} {{Bad}}</p>",
                                      "use_layout": True}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["subject"], "P Prepare orientation deck")
        self.assertIn("Sunita Rao", r.data["html"])
        self.assertEqual(r.data["unknown_variables"], ["Bad"])

        # Institute scope inherits the global row until saved.
        r = c.get(url, {"institute": self.jdift.id})
        self.assertEqual(r.data["current"]["source"], "global")
        self.assertFalse(r.data["has_own_row"])
        r = c.put(url + f"?institute={self.jdift.id}", {"subject": "JDIFT: {{Task_Name}}",
                                                        "body_html": "<p>i</p>"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["current"]["source"], "institute")
        listing = c.get("/api/comms/system-emails/").data["items"]
        item = next(i for i in listing if i["key"] == "tasks.assigned.email")
        self.assertEqual(item["overrides"][0]["institute_code"], "JDIFT")

        # Revert to v1 at global scope, then reset to default.
        row = SystemEmailTemplate.objects.get(trigger_key="tasks.assigned.email", institute__isnull=True)
        c.put(url, {"subject": "Second", "body_html": "<p>2</p>"}, format="json")
        v1 = row.versions.get(number=1)
        r = c.post(url + f"revert/{v1.id}/", {}, format="json")
        self.assertEqual(r.data["current"]["subject"], "New: {{Task_Name}}")
        r = c.delete(url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["current"]["is_customised"])
        self.assertEqual(r.data["current"]["subject"], registry.get("tasks.assigned.email").default_subject)
        # Institute: DELETE disables the override → back to global.
        r = c.delete(url + f"?institute={self.jdift.id}")
        self.assertEqual(r.data["current"]["source"], "global")

    def test_attachments_and_test_send(self):
        c = self._client(self.admin)
        url = "/api/comms/system-emails/tasks.assigned.email/attachments/"
        r = c.post(url, {"file": SimpleUploadedFile("b.pdf", b"%PDF-1.4", content_type="application/pdf")},
                   format="multipart")
        self.assertEqual(r.status_code, 201, r.data)
        att_id = r.data["id"]
        self.assertTrue(SystemEmailTemplate.objects.filter(trigger_key="tasks.assigned.email").exists())
        r = c.post(url, {"file": SimpleUploadedFile("x.exe", b"MZ", content_type="application/x-msdownload")},
                   format="multipart")
        self.assertEqual(r.status_code, 400)

        r = c.post("/api/comms/system-emails/tasks.assigned.email/test-send/",
                   {"subject": "T {{Task_Name}}", "body_html": "<p>t</p>", "use_layout": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["sent_to"], "root@jd.test")
        self.assertEqual(mail.outbox[-1].subject, "[TEST] T Prepare orientation deck")

        r = c.delete(url + f"{att_id}/")
        self.assertEqual(r.status_code, 204)

    def test_layout_endpoints(self):
        c = self._client(self.admin)
        r = c.get("/api/comms/system-emails/layout/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["header_html"])
        r = c.put("/api/comms/system-emails/layout/", {"header_html": "<p>{{Nope}}</p>", "footer_html": ""},
                  format="json")
        self.assertEqual(r.status_code, 400)
        r = c.put("/api/comms/system-emails/layout/", {"header_html": "<p>{{Institute_Name}}</p>",
                                                       "footer_html": "<p>f</p>", "note": "v1"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["versions"][0]["number"], 1)
        self.assertEqual(EmailLayout.objects.filter(institute__isnull=True).count(), 1)
        r = c.post("/api/comms/system-emails/layout/preview/",
                   {"header_html": "<p>HEAD {{Institute_Name}}</p>", "footer_html": "<p>FOOT</p>"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("HEAD JD Institute of Fashion Technology", r.data["html"])
        self.assertIn("FOOT", r.data["html"])
