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
