"""A task can carry one attachment, uploaded with the create form."""

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.tasks.models import Task

User = get_user_model()

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TaskAttachmentTests(TestCase):

    def setUp(self):
        self.me = User.objects.create_user("me", "me@e.com", "x")
        self.other = User.objects.create_user("other", "other@e.com", "x")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def _post(self, **extra):
        body = {"name": "Collect forms", "end_date": "2026-12-01",
                "assignee": self.other.id, **extra}
        return self.c.post("/api/tasks/", body, format="multipart")

    def test_pdf_attachment_is_stored_and_linked(self):
        r = self._post(attachment=SimpleUploadedFile("brief.pdf", PDF, "application/pdf"))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(r.data["attachment_url"].startswith("http://testserver/media/"))
        self.assertTrue(r.data["attachment_name"].startswith("brief"))
        self.assertTrue(Task.objects.get().attachment.name.startswith("tasks/attachments/"))

    def test_no_attachment_is_fine(self):
        r = self._post()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(r.data["attachment_url"])
        self.assertEqual(r.data["attachment_name"], "")

    def test_executable_disguised_as_pdf_is_rejected(self):
        r = self._post(attachment=SimpleUploadedFile(
            "x.pdf", b"MZ\x90\x00" + b"\x00" * 64, "application/pdf"))
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("attachment", r.data)
        self.assertEqual(Task.objects.count(), 0)
