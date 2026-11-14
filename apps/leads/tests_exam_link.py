from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone

from apps.leads.exam_models import EntranceExam, EntranceExamAttempt
from apps.leads.models import Lead, LeadCommunication
from apps.leads.send_links import send_entrance_exam_link
from apps.master.models import Campus, Institute, LeadSource, Program

User = get_user_model()


class SendEntranceExamLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="staff", password="x", email="s@e.com",
        )
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="Diploma in Fashion", code="DFD",
            institute=cls.institute, degree_type="Diploma",
        )
        cls.source = LeadSource.objects.create(name="Web", slug="web")
        cls.exam = EntranceExam.objects.create(
            name="Design Aptitude", duration_min=45,
            status=EntranceExam.Status.PUBLISHED,
        )

    def setUp(self):
        # The API is JWT-authenticated; session login does not apply.
        self.client = APIClient()

    def _attempt(self, *, email="cand@example.com"):
        lead = Lead.objects.create(
            name="Asha Rao", phone="9999999999", email=email,
            campus=self.campus, program=self.program, source=self.source,
        )
        now = timezone.now()
        return EntranceExamAttempt.objects.create(
            exam=self.exam, lead=lead,
            start_dt=now, end_dt=now + timedelta(days=2),
        )

    def test_sends_and_logs(self):
        a = self._attempt()
        result = send_entrance_exam_link(attempt=a, actor=self.user)
        self.assertIn(str(a.access_token), result["url"])
        self.assertIn("/#/exam/", result["url"])
        comm = LeadCommunication.objects.get(pk=result["communication_id"])
        self.assertEqual(comm.type, LeadCommunication.Type.EMAIL)
        self.assertEqual(comm.logged_by, self.user)
        self.assertIn("Design Aptitude", comm.subject)

    def test_token_is_stable_across_resends(self):
        """Re-sending must not rotate the token — a candidate who already
        has the link would be locked out."""
        a = self._attempt()
        first = send_entrance_exam_link(attempt=a, actor=self.user)["url"]
        second = send_entrance_exam_link(attempt=a, actor=self.user)["url"]
        self.assertEqual(first, second)

    def test_requires_email(self):
        a = self._attempt(email="")
        with self.assertRaisesMessage(ValueError, "no email"):
            send_entrance_exam_link(attempt=a, actor=self.user)

    def test_requires_published_exam(self):
        a = self._attempt()
        self.exam.status = EntranceExam.Status.DRAFT
        self.exam.save(update_fields=["status"])
        with self.assertRaisesMessage(ValueError, "publish it"):
            send_entrance_exam_link(attempt=a, actor=self.user)
        self.exam.status = EntranceExam.Status.PUBLISHED
        self.exam.save(update_fields=["status"])

    def test_endpoint_requires_permission(self):
        a = self._attempt()
        self.client.force_authenticate(user=self.user)
        r = self.client.post(f"/api/leads/exam-attempts/{a.id}/send-link/")
        self.assertEqual(r.status_code, 403)

    def test_endpoint_sends_for_exam_owner(self):
        self.exam.created_by = self.user
        self.exam.save(update_fields=["created_by"])
        a = self._attempt()
        self.client.force_authenticate(user=self.user)
        r = self.client.post(f"/api/leads/exam-attempts/{a.id}/send-link/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(str(a.access_token), r.json()["url"])

    # --- Bulk send to SELECTED attempts -------------------------------

    def _own_exam(self):
        self.exam.created_by = self.user
        self.exam.save(update_fields=["created_by"])
        self.client.force_authenticate(user=self.user)

    def test_bulk_sends_only_selected(self):
        self._own_exam()
        a1 = self._attempt(email="one@example.com")
        a2 = self._attempt(email="two@example.com")
        self._attempt(email="three@example.com")  # mapped, NOT selected
        r = self.client.post(
            f"/api/leads/exams/{self.exam.id}/send-links/",
            {"attempt_ids": [a1.id, a2.id]}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["requested"], 2)
        self.assertEqual({x["attempt_id"] for x in body["results"]},
                         {a1.id, a2.id})
        # Only the two selected leads got a timeline entry.
        self.assertEqual(LeadCommunication.objects.count(), 2)
        self.assertEqual(
            set(LeadCommunication.objects.values_list("lead_id", flat=True)),
            {a1.lead_id, a2.lead_id},
        )

    def test_bulk_empty_selection_is_rejected(self):
        """Empty must never mean 'everyone'."""
        self._own_exam()
        self._attempt()
        r = self.client.post(
            f"/api/leads/exams/{self.exam.id}/send-links/",
            {"attempt_ids": []}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(LeadCommunication.objects.count(), 0)

    def test_bulk_rejects_attempts_of_other_exam(self):
        self._own_exam()
        other = EntranceExam.objects.create(
            name="Other", duration_min=10,
            status=EntranceExam.Status.PUBLISHED, created_by=self.user,
        )
        lead = Lead.objects.create(
            name="X", phone="8888888888", email="x@example.com",
            campus=self.campus, program=self.program, source=self.source,
        )
        now = timezone.now()
        foreign = EntranceExamAttempt.objects.create(
            exam=other, lead=lead, start_dt=now, end_dt=now + timedelta(days=1),
        )
        r = self.client.post(
            f"/api/leads/exams/{self.exam.id}/send-links/",
            {"attempt_ids": [foreign.id]}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(LeadCommunication.objects.count(), 0)

    def test_bulk_reports_no_email_per_row(self):
        self._own_exam()
        ok = self._attempt(email="ok@example.com")
        bad = self._attempt(email="")
        r = self.client.post(
            f"/api/leads/exams/{self.exam.id}/send-links/",
            {"attempt_ids": [ok.id, bad.id]}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        rows = {x["attempt_id"]: x for x in r.json()["results"]}
        self.assertFalse(rows[bad.id]["email_sent"])
        self.assertIn("no email", rows[bad.id]["email_error"])
        # The good row went through the dispatcher (whatever the template
        # state in this environment) — it must not carry the no-email error.
        self.assertNotIn("no email", rows[ok.id]["email_error"])
        self.assertEqual(r.json()["requested"], 2)
        # Only the lead with an address got a timeline entry.
        self.assertEqual(LeadCommunication.objects.count(), 1)

    def test_bulk_requires_permission(self):
        a = self._attempt()
        self.client.force_authenticate(user=self.user)
        r = self.client.post(
            f"/api/leads/exams/{self.exam.id}/send-links/",
            {"attempt_ids": [a.id]}, format="json",
        )
        self.assertEqual(r.status_code, 403)
