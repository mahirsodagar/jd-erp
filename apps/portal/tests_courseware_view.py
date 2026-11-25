"""Courseware in the student portal is view-only (client, 2026-11-25).

The list never carries the raw /media/ link; each attachment points at
an authenticated inline-view endpoint that streams the file only to a
student it is mapped to, served `inline` and `no-store`.
"""

import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Student
from apps.courseware.models import (
    CoursewareAttachment, CoursewareMapping, CoursewareTopic,
)
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject,
)

_MEDIA = tempfile.mkdtemp(prefix="jd-erp-test-media-")


@override_settings(MEDIA_ROOT=_MEDIA)
class CoursewareViewOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year)
        subject = Subject.objects.create(name="Core", code="CORE", program=program)

        User = get_user_model()

        def student(username):
            u = User.objects.create_user(
                username=username, password="x", email=f"{username}@example.com")
            s = Student.objects.create(
                application_form_id=f"AF-{username}", student_name=username,
                gender="F", dob="2006-01-01", nationality="INDIAN",
                category="GENERAL", institute=inst, campus=campus,
                program=program, academic_year=year, user_account=u,
            )
            return u, s

        cls.mapped_user, cls.mapped = student("asha")
        cls.other_user, _ = student("riya")
        cls.parent_user = User.objects.create_user(
            username="dad", password="x", email="dad@example.com")
        cls.mapped.parent_user_account = cls.parent_user
        cls.mapped.save(update_fields=["parent_user_account"])

        cls.topic = CoursewareTopic.objects.create(
            subject=subject, batch=batch, name="Week 1", is_published=True)
        CoursewareMapping.objects.create(topic=cls.topic, student=cls.mapped)
        cls.att = CoursewareAttachment.objects.create(
            topic=cls.topic, name="Notes",
            file=ContentFile(b"%PDF-1.4 fake", name="notes.pdf"),
        )

    def _client(self, user=None):
        c = APIClient()
        if user is not None:
            c.force_authenticate(user)
        return c

    def test_list_carries_view_url_and_kind_but_no_media_link(self):
        r = self._client(self.mapped_user).get(reverse("portal-courseware-list"))
        self.assertEqual(r.status_code, 200, r.content)
        att = r.data[0]["attachments"][0]
        self.assertEqual(att["kind"], "pdf")
        self.assertEqual(att["content_type"], "application/pdf")
        self.assertIn(f"/api/portal/courseware/attachments/{self.att.id}/view/",
                      att["view_url"])
        self.assertNotIn("url", att)
        self.assertNotIn("/media/", str(r.data))

    def test_mapped_student_streams_inline(self):
        url = reverse("portal-courseware-attachment-view", args=[self.att.id])
        r = self._client(self.mapped_user).get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertEqual(r["Content-Disposition"], "inline")
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-1.4 fake")

    def test_unmapped_student_parent_and_anonymous_are_refused(self):
        url = reverse("portal-courseware-attachment-view", args=[self.att.id])
        self.assertEqual(self._client(self.other_user).get(url).status_code, 404)
        self.assertEqual(self._client(self.parent_user).get(url).status_code, 403)
        self.assertIn(self._client().get(url).status_code, (401, 403))

    def test_unpublished_topic_is_hidden(self):
        self.topic.is_published = False
        self.topic.save(update_fields=["is_published"])
        url = reverse("portal-courseware-attachment-view", args=[self.att.id])
        self.assertEqual(self._client(self.mapped_user).get(url).status_code, 404)
