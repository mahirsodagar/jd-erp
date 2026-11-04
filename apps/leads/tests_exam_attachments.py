"""Candidate attachments on the public entrance-exam link."""

import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.leads.exam_models import (
    EntranceExam, EntranceExamAttachment, EntranceExamAttempt,
    EntranceExamQuestion,
)
from apps.leads.models import Lead
from apps.master.models import Campus, Institute, LeadSource, Program

MEDIA = tempfile.mkdtemp(prefix="jd-exam-att-")

# A real PNG header so any magic-byte sniffing accepts it.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@override_settings(MEDIA_ROOT=MEDIA)
class PublicExamAttachmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(
            name="Diploma in Fashion", code="DFD",
            institute=institute, degree_type="Diploma",
        )
        source = LeadSource.objects.create(name="Web", slug="web")
        cls.exam = EntranceExam.objects.create(
            name="Design Aptitude", duration_min=45,
            status=EntranceExam.Status.PUBLISHED,
        )
        cls.q = EntranceExamQuestion.objects.create(
            exam=cls.exam, description="Sketch a dress", type="SHORT", marks=5,
        )
        other_exam = EntranceExam.objects.create(
            name="Other", duration_min=10, status=EntranceExam.Status.PUBLISHED,
        )
        cls.foreign_q = EntranceExamQuestion.objects.create(
            exam=other_exam, description="x", type="SHORT", marks=1,
        )
        lead = Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="a@example.com",
            campus=campus, program=program, source=source,
        )
        now = timezone.now()
        cls.attempt = EntranceExamAttempt.objects.create(
            exam=cls.exam, lead=lead,
            start_dt=now - timedelta(hours=1), end_dt=now + timedelta(days=2),
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.base = f"/api/public/exam/{self.attempt.access_token}/"

    def _png(self, name="sketch.png"):
        return SimpleUploadedFile(name, PNG, content_type="image/png")

    def _start(self):
        self.client.post(self.base + "start/")
        self.attempt.refresh_from_db()

    def test_requires_started_attempt(self):
        r = self.client.post(self.base + "attachments/",
                             {"file": self._png()}, format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Start the exam", r.data["detail"])

    def test_upload_lists_and_deletes(self):
        self._start()
        r = self.client.post(
            self.base + "attachments/",
            {"file": self._png(), "question": self.q.id, "note": "page 1"},
            format="multipart",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["question"], self.q.id)
        self.assertEqual(r.data["original_name"], "sketch.png")
        self.assertEqual(r.data["note"], "page 1")
        self.assertTrue(r.data["file_url"].startswith("http"))

        state = self.client.get(self.base).data
        self.assertEqual(len(state["attachments"]), 1)
        self.assertEqual(state["attachment_limits"]["max_files"],
                         EntranceExamAttachment.MAX_PER_ATTEMPT)

        d = self.client.delete(self.base + f"attachments/{r.data['id']}/")
        self.assertEqual(d.status_code, 204)
        self.assertEqual(self.attempt.attachments.count(), 0)

    def test_rejects_bad_extension_and_foreign_question(self):
        self._start()
        bad = SimpleUploadedFile("notes.exe", b"MZ" * 10,
                                 content_type="application/octet-stream")
        r = self.client.post(self.base + "attachments/", {"file": bad},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("file", r.data)

        r = self.client.post(
            self.base + "attachments/",
            {"file": self._png(), "question": self.foreign_q.id},
            format="multipart",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("question", r.data)

    def test_locked_after_submit(self):
        self._start()
        r = self.client.post(self.base + "attachments/", {"file": self._png()},
                             format="multipart")
        self.assertEqual(r.status_code, 201)
        att_id = r.data["id"]

        s = self.client.post(self.base + "submit/",
                             {"answers": [{"question": self.q.id, "answer": "see file"}]},
                             format="json")
        self.assertEqual(s.status_code, 200, s.data)

        r = self.client.post(self.base + "attachments/", {"file": self._png("b.png")},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
        d = self.client.delete(self.base + f"attachments/{att_id}/")
        self.assertEqual(d.status_code, 400)
        # Still visible to the candidate on the result screen.
        self.assertEqual(len(self.client.get(self.base).data["attachments"]), 1)

    def test_per_attempt_cap(self):
        self._start()
        for i in range(EntranceExamAttachment.MAX_PER_ATTEMPT):
            EntranceExamAttachment.objects.create(
                attempt=self.attempt, file=self._png(f"f{i}.png"),
                original_name=f"f{i}.png", size=len(PNG),
            )
        r = self.client.post(self.base + "attachments/", {"file": self._png()},
                             format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("at most", r.data["detail"])
