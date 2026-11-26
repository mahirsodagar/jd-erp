"""Send box (2026-11-26): the institute the fee / application link is
sent for follows the lead's program — the body no longer carries one."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.leads.models import Lead
from apps.master.models import Campus, Institute, LeadSource, Program

User = get_user_model()


class SendInstituteFollowsProgramTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@e.com")
        jdsd = Institute.objects.create(name="JD School of Design", code="JDSD")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(name="B.Des", code="BDES", institute=jdsd)
        cls.source = LeadSource.objects.create(name="Web", slug="web")
        # Legacy row with no owning institute (Program.institute is nullable).
        cls.orphan = Program.objects.create(name="Old", code="OLD", institute=None)

    def _lead(self, program):
        return Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="asha@example.com",
            campus=self.campus, program=program, source=self.source)

    def _client(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c

    def test_fee_link_uses_the_programs_institute_and_ignores_the_body(self):
        lead = self._lead(self.program)
        with patch("apps.leads.send_links.send_fee_link",
                   return_value={"ok": True}) as send:
            r = self._client().post(
                reverse("lead-send-fee-link", args=[lead.pk]),
                {"institute": "JDIFT"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(send.call_args.kwargs["institute_key"], "JDSD")

    def test_application_link_uses_the_programs_institute(self):
        lead = self._lead(self.program)
        with patch("apps.leads.send_links.send_application_link",
                   return_value={"ok": True}) as send:
            r = self._client().post(
                reverse("lead-send-application-link", args=[lead.pk]))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(send.call_args.kwargs["institute_key"], "JDSD")

    def test_program_without_an_institute_is_refused(self):
        lead = self._lead(self.orphan)
        with patch("apps.leads.send_links.send_fee_link") as send:
            r = self._client().post(
                reverse("lead-send-fee-link", args=[lead.pk]))
        self.assertEqual(r.status_code, 400)
        self.assertIn("institute", r.json()["detail"].lower())
        send.assert_not_called()

    def test_detail_exposes_the_institute_for_the_send_box(self):
        lead = self._lead(self.program)
        r = self._client().get(reverse("lead-detail", args=[lead.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["institute_code"], "JDSD")
        self.assertEqual(r.json()["institute_name"], "JD School of Design")
        bare = self._client().get(
            reverse("lead-detail", args=[self._lead(self.orphan).pk]))
        self.assertEqual(bare.json()["institute_code"], "")
