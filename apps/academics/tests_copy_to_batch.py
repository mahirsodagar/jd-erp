"""Copy an assignment / courseware topic to another batch of the same
program (the legacy "map to another batch" ported as a duplicate)."""

from datetime import date, datetime, timezone as dt_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Assignment, AssignmentSubmission
from apps.admissions.models import Enrollment, Student
from apps.courseware.models import (
    CoursewareAttachment, CoursewareMapping, CoursewareTopic,
)
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
)


class CopyToBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.campus2 = Campus.objects.create(name="Other", code="OTH")
        cls.program = Program.objects.create(name="B.Des", code="BDES",
                                             institute=inst)
        other_program = Program.objects.create(name="M.Des", code="MDES",
                                               institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31))
        cls.sem1 = Semester.objects.create(name="Sem 1", number=1)
        cls.b1 = Batch.objects.create(name="BD-1", program=cls.program,
                                      campus=cls.campus, academic_year=year)
        cls.b2 = Batch.objects.create(name="BD-2", program=cls.program,
                                      campus=cls.campus2, academic_year=year)
        cls.inactive = Batch.objects.create(
            name="BD-0", program=cls.program, campus=cls.campus,
            academic_year=year, is_active=False)
        cls.foreign = Batch.objects.create(
            name="MD-1", program=other_program, campus=cls.campus,
            academic_year=year)
        cls.subject = Subject.objects.create(name="Pattern Making", code="PM")

        def student(i, batch, status=Enrollment.Status.ACTIVE):
            s = Student.objects.create(
                application_form_id=f"AF-{i}", student_name=f"Student {i}",
                student_email=f"s{i}@example.com",
                gender="M", dob="2000-01-01", nationality="INDIAN",
                category="GENERAL", institute=inst, campus=cls.campus,
                program=cls.program, academic_year=year,
            )
            Enrollment.objects.create(
                student=s, program=cls.program, semester=cls.sem1,
                campus=batch.campus, batch=batch, academic_year=year,
                status=status)
            return s

        cls.s1 = student(1, cls.b1)
        cls.s2 = student(2, cls.b2)
        cls.s3 = student(3, cls.b2)
        cls.s4 = student(4, cls.b2, status=Enrollment.Status.DROPPED)

        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com")
        cls.nobody = User.objects.create_user(
            username="nobody", email="n@example.com", password="x")

        cls.assignment = Assignment.objects.create(
            subject=cls.subject, program=cls.program, campus=cls.campus,
            batch=cls.b1, semester=cls.sem1, title="Bodice block",
            description="Draft a bodice block", max_marks=10,
            due_date=datetime(2026, 11, 20, 12, 30, tzinfo=dt_tz.utc),
            attachment=SimpleUploadedFile("brief.pdf", b"%PDF-1.4 x"),
        )
        AssignmentSubmission.objects.create(
            assignment=cls.assignment, student=cls.s1, text_response="done")

        cls.topic = CoursewareTopic.objects.create(
            subject=cls.subject, batch=cls.b1, name="Darts",
            description="Dart manipulation")
        CoursewareAttachment.objects.create(
            topic=cls.topic, name="Slides",
            file=SimpleUploadedFile("darts.pdf", b"%PDF-1.4 y"))
        CoursewareMapping.objects.create(topic=cls.topic, student=cls.s1)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    # --- assignments --------------------------------------------------

    def _copy_assignment(self, **body):
        with mock.patch("apps.academics.assignment_notify"
                        ".schedule_assignment_assigned") as sched:
            r = self.client.post(
                reverse("assignment-copy", args=[self.assignment.pk]),
                body, format="json")
        return r, sched

    def test_assignment_copy_keeps_original_and_shares_files(self):
        r, sched = self._copy_assignment(batch=self.b2.pk)
        self.assertEqual(r.status_code, 201, r.data)
        copy = Assignment.objects.get(pk=r.data["id"])
        self.assertNotEqual(copy.pk, self.assignment.pk)
        self.assertEqual(copy.batch_id, self.b2.pk)
        self.assertEqual(copy.campus_id, self.campus2.pk)
        self.assertEqual(copy.program_id, self.program.pk)
        self.assertEqual(copy.title, "Bodice block")
        self.assertEqual(copy.semester_id, self.sem1.pk)
        self.assertEqual(copy.attachment.name, self.assignment.attachment.name)
        self.assertEqual(copy.created_by_id, self.admin.pk)
        # Original untouched, submissions stay with it.
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.batch_id, self.b1.pk)
        self.assertEqual(self.assignment.submissions.count(), 1)
        self.assertEqual(copy.submissions.count(), 0)
        sched.assert_called_once_with(copy)

    def test_assignment_copy_due_date_override(self):
        r, _ = self._copy_assignment(batch=self.b2.pk,
                                     due_date="2026-12-01T10:00:00Z")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["due_date"].startswith("2026-12-01"))

    def test_assignment_copy_rejections(self):
        for batch, key in ((self.b1, "batch"), (self.inactive, "batch"),
                           (self.foreign, "batch"), (999999, "batch")):
            pk = batch if isinstance(batch, int) else batch.pk
            r, _ = self._copy_assignment(batch=pk)
            self.assertEqual(r.status_code, 400, r.data)
            self.assertIn(key, r.data)
        # Duplicate title on the target batch.
        self._copy_assignment(batch=self.b2.pk)
        r, _ = self._copy_assignment(batch=self.b2.pk)
        self.assertEqual(r.status_code, 400)

    def test_assignment_copy_needs_create_perm(self):
        c = APIClient()
        c.force_authenticate(self.nobody)
        r = c.post(reverse("assignment-copy", args=[self.assignment.pk]),
                   {"batch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 403)

    # --- courseware ---------------------------------------------------

    def test_topic_copy_maps_target_batch_and_shares_attachments(self):
        r = self.client.post(
            reverse("courseware-topic-copy", args=[self.topic.pk]),
            {"batch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        copy = CoursewareTopic.objects.get(pk=r.data["id"])
        self.assertEqual(copy.batch_id, self.b2.pk)
        self.assertEqual(copy.name, "Darts")
        self.assertEqual(copy.subject_id, self.subject.pk)
        atts = list(copy.attachments.all())
        self.assertEqual(len(atts), 1)
        self.assertEqual(atts[0].file.name,
                         self.topic.attachments.first().file.name)
        # Active students of b2 are mapped; dropped one isn't.
        self.assertEqual(
            set(copy.mappings.values_list("student_id", flat=True)),
            {self.s2.pk, self.s3.pk})
        # Original keeps its own mappings.
        self.assertEqual(
            list(self.topic.mappings.values_list("student_id", flat=True)),
            [self.s1.pk])

    def test_topic_copy_rejections(self):
        for pk in (self.b1.pk, self.inactive.pk, self.foreign.pk, 999999):
            r = self.client.post(
                reverse("courseware-topic-copy", args=[self.topic.pk]),
                {"batch": pk}, format="json")
            self.assertEqual(r.status_code, 400, r.data)
        self.client.post(reverse("courseware-topic-copy", args=[self.topic.pk]),
                         {"batch": self.b2.pk}, format="json")
        r = self.client.post(
            reverse("courseware-topic-copy", args=[self.topic.pk]),
            {"batch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_topic_copy_needs_add_perm(self):
        c = APIClient()
        c.force_authenticate(self.nobody)
        r = c.post(reverse("courseware-topic-copy", args=[self.topic.pk]),
                   {"batch": self.b2.pk}, format="json")
        self.assertEqual(r.status_code, 403)
