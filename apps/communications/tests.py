"""Communication → Bulk Email: audience building, campaign lifecycle,
permission gating, templates and suppression. No sending happens."""

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.leads.models import Lead
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, LeadSource, Program, Semester,
)
from apps.relieving.tests_notifications import make_employee
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

from .audience import build_audience
from .models import EmailCampaign, EmailCampaignRecipient, EmailTemplate, Suppression

User = get_user_model()


def _user_with(username, *keys):
    u = User.objects.create_user(username, f"{username}@x.in", "x")
    if keys:
        role = Role.objects.create(name=f"role-{username}")
        role.permissions.set(Permission.objects.filter(key__in=keys))
        u.roles.add(role)
    return u


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        cls.inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.other_campus = Campus.objects.create(name="Goa", code="GOA")
        cls.program = Program.objects.create(
            name="Diploma in Fashion", code="DFD", institute=cls.inst,
        )
        cls.source = LeadSource.objects.create(name="Web", slug="web")
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(
            name="DFD-2026-A", program=cls.program, campus=cls.campus,
            academic_year=cls.year,
        )

        cls.sender = _user_with("sender", "comms.bulk_email.send")
        cls.viewer = _user_with("viewer", "comms.bulk_email.view")
        cls.manager = _user_with("manager", "comms.bulk_email.manage")
        cls.nobody = _user_with("nobody")

    def setUp(self):
        self.client = APIClient()

    def _lead(self, name, email, **extra):
        return Lead.objects.create(
            name=name, email=email, phone="9999999999",
            campus=extra.pop("campus", self.campus), program=self.program,
            source=self.source, **extra,
        )

    def _student(self, name, email, **extra):
        n = Student.objects.count() + 1
        s = Student.objects.create(
            application_form_id=f"JDIFT-2026-{n:04d}", student_name=name,
            gender="F", dob=date(2004, 1, 1), nationality="IN",
            institute=self.inst, campus=self.campus, program=self.program,
            academic_year=self.year, student_email=email, **extra,
        )
        Enrollment.objects.create(
            student=s, program=self.program, semester=self.sem,
            campus=self.campus, batch=self.batch, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )
        return s

    def _create_campaign(self, user, **overrides):
        payload = {
            "subject": "Hello {{first_name}}",
            "audience": {"source": "leads", "filters": {}},
            "filter_labels": {},
            "excluded_keys": [],
            "reply_to": "",
            "body_html": "<p>Hi there</p>",
            "include_unsubscribe": True,
            "template_id": None,
            "scheduled_at": None,
        }
        payload.update(overrides)
        self.client.force_authenticate(user)
        return self.client.post(
            "/api/comms/campaigns/", {"payload": json.dumps(payload)},
            format="multipart",
        )


class AudienceTests(_Base):
    def test_leads_blank_duplicate_and_suppressed(self):
        self._lead("A", "a@x.in")
        self._lead("B", "A@X.IN")          # duplicate, case-insensitive
        self._lead("C", "")                # no email
        self._lead("D", "d@x.in")
        Suppression.objects.create(email="d@x.in", reason="manual")

        aud = build_audience("leads", {})
        self.assertEqual([r["email"] for r in aud.recipients], ["a@x.in", "d@x.in"])
        self.assertEqual(aud.skipped_duplicate, 1)
        self.assertEqual(aud.skipped_blank, 1)
        self.assertEqual(aud.suppressed, 1)
        self.assertTrue(aud.recipients[1]["suppressed"])

    def test_lead_filters(self):
        self._lead("A", "a@x.in", status="interested")
        self._lead("B", "b@x.in", status="enrolled", campus=self.other_campus)
        aud = build_audience("leads", {"campus": self.campus.id, "status": ["interested"]})
        self.assertEqual([r["name"] for r in aud.recipients], ["A"])
        aud = build_audience("leads", {"status": ["interested", "enrolled"]})
        self.assertEqual(len(aud.recipients), 2)

    def test_students_address_kinds(self):
        self._student("Asha Rao", "asha@x.in", father_email="dad@x.in",
                      father_name="Ravi Rao", mother_email="")
        aud = build_audience(
            "students",
            {"batch": self.batch.id, "recipients": ["student", "father", "mother"]},
        )
        self.assertEqual(
            [(r["kind"], r["email"]) for r in aud.recipients],
            [("student", "asha@x.in"), ("father", "dad@x.in")],
        )
        self.assertEqual(aud.recipients[1]["name"], "Ravi Rao (father)")
        self.assertEqual(aud.skipped_blank, 1)
        self.assertIn("DFD-2026-A", aud.recipients[0]["context"])

    def test_employees(self):
        make_employee("EMP1", institute=self.inst, campus=self.campus)
        make_employee("EMP2", institute=self.inst, campus=self.other_campus, status=1)
        aud = build_audience("employees", {"status": 0})
        self.assertEqual([r["email"] for r in aud.recipients], ["emp1@jdinstitute.edu.in"])
        aud = build_audience("employees", {"campus": self.other_campus.id, "status": ""})
        self.assertEqual(len(aud.recipients), 1)

    def test_preview_endpoint_needs_send(self):
        self.client.force_authenticate(self.viewer)
        r = self.client.post("/api/comms/audience/preview/",
                             {"source": "leads", "filters": {}}, format="json")
        self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(self.sender)
        r = self.client.post("/api/comms/audience/preview/",
                             {"source": "students", "filters": {"recipients": []}},
                             format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/comms/audience/preview/",
                             {"source": "leads", "filters": {}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["recipients"], [])


class CampaignTests(_Base):
    def test_create_snapshots_recipients_and_queues(self):
        a = self._lead("A", "a@x.in")
        self._lead("B", "b@x.in")
        self._lead("S", "s@x.in")
        Suppression.objects.create(email="s@x.in", reason="unsubscribed")

        r = self._create_campaign(
            self.sender, excluded_keys=[f"lead:{a.id}"],
            filter_labels={"Campus": "Bengaluru"},
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["status"], "queued")
        self.assertEqual(r.data["counts"], {
            "total": 1, "sent": 0, "failed": 0, "pending": 1,
            "unsubscribed": 0, "skipped": 0,
        })
        self.assertEqual(r.data["audience_summary"], "Leads · Bengaluru")
        c = EmailCampaign.objects.get()
        self.assertEqual(list(c.recipients.values_list("email", flat=True)), ["b@x.in"])
        self.assertEqual(c.created_by, self.sender)

    def test_create_rejects_empty_and_bad_payload(self):
        r = self._create_campaign(self.sender)
        self.assertEqual(r.status_code, 400)
        self.assertIn("No recipients", r.data["detail"])
        self._lead("A", "a@x.in")
        r = self._create_campaign(self.sender, subject="   ")
        self.assertEqual(r.status_code, 400)
        r = self._create_campaign(self.sender, body_html="<p> </p>")
        self.assertEqual(r.status_code, 400)
        r = self._create_campaign(self.sender, reply_to="not-an-email")
        self.assertEqual(r.status_code, 400)
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        r = self._create_campaign(self.sender, scheduled_at=past)
        self.assertEqual(r.status_code, 400)

    def test_schedule_future(self):
        self._lead("A", "a@x.in")
        later = (timezone.now() + timedelta(hours=2)).isoformat()
        r = self._create_campaign(self.sender, scheduled_at=later)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["status"], "scheduled")

    def test_viewer_cannot_create(self):
        self._lead("A", "a@x.in")
        r = self._create_campaign(self.viewer)
        self.assertEqual(r.status_code, 403)
        r = self._create_campaign(self.nobody)
        self.assertEqual(r.status_code, 403)

    def test_list_scoping(self):
        self._lead("A", "a@x.in")
        self._create_campaign(self.sender)
        self._create_campaign(self.manager)

        self.client.force_authenticate(self.sender)
        r = self.client.get("/api/comms/campaigns/")
        self.assertEqual(len(r.data), 1)
        self.assertNotIn("body_html", r.data[0])

        self.client.force_authenticate(self.manager)
        self.assertEqual(len(self.client.get("/api/comms/campaigns/").data), 2)
        self.assertEqual(len(self.client.get("/api/comms/campaigns/?mine=1").data), 1)

        self.client.force_authenticate(self.nobody)
        self.assertEqual(self.client.get("/api/comms/campaigns/").status_code, 403)

    def test_detail_and_recipients_visibility(self):
        self._lead("A", "a@x.in")
        cid = self._create_campaign(self.sender).data["id"]

        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(f"/api/comms/campaigns/{cid}/").status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(f"/api/comms/campaigns/{cid}/").status_code, 200)
        rows = self.client.get(f"/api/comms/campaigns/{cid}/recipients/").data
        self.assertEqual(rows[0]["email"], "a@x.in")
        self.assertEqual(rows[0]["status"], "pending")
        rows = self.client.get(f"/api/comms/campaigns/{cid}/recipients/?status=sent").data
        self.assertEqual(rows, [])

    def test_lifecycle_actions(self):
        self._lead("A", "a@x.in")
        self._lead("B", "b@x.in")
        cid = self._create_campaign(self.sender).data["id"]
        url = f"/api/comms/campaigns/{cid}"
        self.client.force_authenticate(self.sender)

        self.assertEqual(self.client.post(f"{url}/resume/").status_code, 400)
        self.assertEqual(self.client.post(f"{url}/pause/").data["status"], "paused")
        self.assertEqual(self.client.post(f"{url}/pause/").status_code, 400)
        self.assertEqual(self.client.post(f"{url}/resume/").data["status"], "queued")

        # Simulate one failure (the worker would do this).
        EmailCampaignRecipient.objects.filter(email="a@x.in").update(
            status="failed", error="550",
        )
        r = self.client.post(f"{url}/retry-failed/")
        self.assertEqual(r.data["counts"]["failed"], 0)
        self.assertEqual(r.data["counts"]["pending"], 2)
        self.assertEqual(self.client.post(f"{url}/retry-failed/").status_code, 400)

        r = self.client.post(f"{url}/cancel/")
        self.assertEqual(r.data["status"], "cancelled")
        self.assertEqual(r.data["counts"]["skipped"], 2)
        self.assertEqual(self.client.post(f"{url}/cancel/").status_code, 400)
        self.assertEqual(self.client.post(f"{url}/retry-failed/").status_code, 400)
        self.assertEqual(self.client.post(f"{url}/bogus/").status_code, 404)

    def test_actions_need_ownership_or_manage(self):
        self._lead("A", "a@x.in")
        cid = self._create_campaign(self.sender).data["id"]
        other = _user_with("other-sender", "comms.bulk_email.send")
        self.client.force_authenticate(other)
        self.assertEqual(self.client.post(f"/api/comms/campaigns/{cid}/pause/").status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(f"/api/comms/campaigns/{cid}/pause/").status_code, 200)

    def test_test_send_is_honest(self):
        self.client.force_authenticate(self.sender)
        r = self.client.post("/api/comms/campaigns/test-send/",
                             {"to": "me@x.in", "subject": "s", "body_html": "<p>x</p>"},
                             format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("not connected", r.data["detail"])


class TemplateTests(_Base):
    def test_crud_and_permissions(self):
        self.client.force_authenticate(self.sender)   # may read, not write
        r = self.client.post("/api/comms/templates/", {"name": "T1", "subject": "s"}, format="json")
        self.assertEqual(r.status_code, 403)

        editor = _user_with("editor", "comms.template.manage")
        self.client.force_authenticate(editor)
        r = self.client.post("/api/comms/templates/",
                             {"name": "  T1 ", "subject": "Hi {{name}}", "body_html": "<p>x</p>"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["name"], "T1")
        self.assertEqual(r.data["updated_by_name"], "editor")
        tid = r.data["id"]

        r = self.client.post("/api/comms/templates/", {"name": "t1"}, format="json")
        self.assertEqual(r.status_code, 400)

        r = self.client.patch(f"/api/comms/templates/{tid}/", {"subject": "New"}, format="json")
        self.assertEqual(r.data["subject"], "New")

        self.client.force_authenticate(self.sender)
        self.assertEqual(len(self.client.get("/api/comms/templates/").data), 1)
        self.assertEqual(self.client.delete(f"/api/comms/templates/{tid}/").status_code, 403)
        self.client.force_authenticate(self.nobody)
        self.assertEqual(self.client.get("/api/comms/templates/").status_code, 403)

        self.client.force_authenticate(editor)
        self.assertEqual(self.client.delete(f"/api/comms/templates/{tid}/").status_code, 204)
        self.assertFalse(EmailTemplate.objects.exists())

    def test_campaign_remembers_template_name(self):
        t = EmailTemplate.objects.create(name="Promo", subject="s", body_html="<p>b</p>")
        self._lead("A", "a@x.in")
        r = self._create_campaign(self.sender, template_id=t.id)
        self.assertEqual(r.data["template_name"], "Promo")
        t.delete()
        self.assertEqual(EmailCampaign.objects.get().template_name, "Promo")


class SuppressionTests(_Base):
    def test_add_list_remove(self):
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.get("/api/comms/suppression/").status_code, 200)
        r = self.client.post("/api/comms/suppression/", {"emails": ["x@x.in"]}, format="json")
        self.assertEqual(r.status_code, 403)

        self.client.force_authenticate(self.manager)
        r = self.client.post(
            "/api/comms/suppression/",
            {"emails": [" A@X.in ", "a@x.in", "junk", "b@x.in"]}, format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(sorted(e["email"] for e in r.data), ["a@x.in", "b@x.in"])
        self.assertEqual(r.data[0]["reason"], "manual")
        self.assertIn("Added by manager", r.data[0]["source"])

        r = self.client.post("/api/comms/suppression/", {"emails": ["a@x.in"]}, format="json")
        self.assertEqual(r.status_code, 400)

        rows = self.client.get("/api/comms/suppression/?q=b@").data
        self.assertEqual([e["email"] for e in rows], ["b@x.in"])

        sid = rows[0]["id"]
        self.assertEqual(self.client.delete(f"/api/comms/suppression/{sid}/").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/comms/suppression/{sid}/").status_code, 404)
        self.assertEqual(Suppression.objects.count(), 1)
