"""Courseware attachments (client, 2026-11-26): only PDF, image or video
files may be uploaded — on Publish and on the per-topic Upload button."""

import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.courseware.models import CoursewareAttachment, CoursewareTopic
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject,
)

_MEDIA = tempfile.mkdtemp()


# Leading bytes that really are of the declared type — uploads are
# content-sniffed since 2026-11-27, so a bare "x" * 16 is refused for
# every family. Unknown types keep the junk body on purpose.
_MAGIC = {
    "application/pdf": b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n" + b"x" * 16,
    "image/png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
    "video/mp4": b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16,
    "video/quicktime": b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 16,
}


def _file(name, ctype, body=None):
    if body is None:
        body = _MAGIC.get(ctype, b"x" * 16)
    return SimpleUploadedFile(name, body, content_type=ctype)


@override_settings(MEDIA_ROOT=_MEDIA)
class AttachmentTypeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        cls.batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year)
        cls.subject = Subject.objects.create(name="Core", code="CORE", program=program)
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com")
        cls.topic = CoursewareTopic.objects.create(
            subject=cls.subject, batch=cls.batch, name="Week 1")

    def _client(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c

    def _add(self, f):
        return self._client().post(
            reverse("courseware-attachment-add", args=[self.topic.pk]),
            {"file": f}, format="multipart")

    def test_pdf_image_and_video_are_accepted(self):
        for f in (_file("notes.pdf", "application/pdf"),
                  _file("slide.PNG", "image/png"),
                  _file("demo.mp4", "video/mp4")):
            self.assertEqual(self._add(f).status_code, 201, f.name)
        self.assertEqual(self.topic.attachments.count(), 3)

    def test_other_types_are_refused(self):
        for f in (_file("notes.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                  _file("sheet.xlsx", "application/octet-stream"),
                  _file("run.exe", "application/x-msdownload"),
                  _file("song.mp3", "audio/mpeg"),
                  _file("noext", "application/pdf")):
            r = self._add(f)
            self.assertEqual(r.status_code, 400, f.name)
            self.assertIn("Only PDF, image", str(r.json()["file"]))
        self.assertEqual(CoursewareAttachment.objects.count(), 0)

    def test_renamed_file_with_mismatched_content_type_is_refused(self):
        r = self._add(_file("notes.pdf", "application/msword"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("does not look like a pdf", str(r.json()["file"]))

    def test_publish_rejects_a_bad_attachment_and_creates_nothing(self):
        r = self._client().post(
            reverse("courseware-topic-list-create"),
            {"subject": self.subject.pk, "batch": self.batch.pk, "name": "Week 2",
             "attachments": [_file("ok.pdf", "application/pdf"),
                             _file("bad.zip", "application/zip")]},
            format="multipart")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("attachments", r.json())
        self.assertFalse(CoursewareTopic.objects.filter(name="Week 2").exists())

    def test_publish_accepts_allowed_attachments(self):
        r = self._client().post(
            reverse("courseware-topic-list-create"),
            {"subject": self.subject.pk, "batch": self.batch.pk, "name": "Week 3",
             "attachments": [_file("ok.pdf", "application/pdf"),
                             _file("clip.mov", "video/quicktime")]},
            format="multipart")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(len(r.json()["attachments"]), 2)
