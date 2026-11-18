"""New-assignment e-mail (template `academics.assignment_assigned.email`),
one per reached student, fired on publish (create or unpublished →
published). Sent over the single SMTP transport; Reply-To = faculty."""

from datetime import date, datetime, timezone as dt_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.academics import assignment_notify as an
from apps.academics.models import Assignment
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
)

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@dkul.in",
    EMAIL_DEFAULT_REPLY_TO="admin.a@jdinstitute.edu.in",
)
class AssignmentNotifyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(name="B.Des", code="BDES",
                                             institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        cls.sem1 = Semester.objects.create(name="Sem 1", number=1)
        cls.sem2 = Semester.objects.create(name="Sem 2", number=2)
        cls.b1 = Batch.objects.create(name="BD-1", program=cls.program,
                                      campus=campus, academic_year=year)
        cls.b2 = Batch.objects.create(name="BD-2", program=cls.program,
                                      campus=campus, academic_year=year)
        cls.subject = Subject.objects.create(name="Pattern Making", code="PM")

        def student(i, batch, sem, status=Enrollment.Status.ACTIVE, email=True):
            s = Student.objects.create(
                application_form_id=f"AF-{i}", student_name=f"Student {i}",
                student_email=f"s{i}@example.com" if email else "",
                gender="M", dob="2000-01-01", nationality="INDIAN",
                category="GENERAL", institute=inst, campus=campus,
                program=cls.program, academic_year=year,
            )
            Enrollment.objects.create(
                student=s, program=cls.program, semester=sem, campus=campus,
                batch=batch, academic_year=year, status=status)
            return s

        student(1, cls.b1, cls.sem1)
        student(2, cls.b1, cls.sem1)
        student(3, cls.b2, cls.sem2)
        student(4, cls.b1, cls.sem1, status=Enrollment.Status.DROPPED)
        student(5, cls.b1, cls.sem1, email=False)
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com")

    def _assignment(self, **kw):
        return Assignment.objects.create(**{
            "subject": self.subject, "program": self.program, "batch": self.b1,
            "title": "Bodice block", "max_marks": 10,
            "due_date": datetime(2026, 11, 20, 12, 30, tzinfo=dt_tz.utc),
            **kw,
        })

    def _emails(self, a):
        return sorted(s.student_email for s in an.recipients_for(a))

    def test_batch_reach_is_active_students_with_email(self):
        self.assertEqual(self._emails(self._assignment()),
                         ["s1@example.com", "s2@example.com"])

    def test_program_wide_reach_and_semester_narrowing(self):
        a = self._assignment(batch=None)
        self.assertEqual(self._emails(a),
                         ["s1@example.com", "s2@example.com", "s3@example.com"])
        a.semester = self.sem2
        self.assertEqual(self._emails(a), ["s3@example.com"])

    def test_sends_one_mail_per_student_with_vars(self):
        faculty = get_user_model().objects.create_user(
            username="fac0", password="x", email="fac0@example.com")
        n = an.send_assignment_assigned(self._assignment(created_by=faculty))
        self.assertEqual(n, 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox),
                         ["s1@example.com", "s2@example.com"])
        m = mail.outbox[0]
        self.assertIn("no-reply@dkul.in", m.from_email)
        self.assertEqual(m.reply_to, ["fac0@example.com"])  # faculty answers
        self.assertIn("Pattern Making", m.body)
        self.assertIn("Bodice block", m.body)
        self.assertIn("20-11-2026 06:00 PM", m.body)  # 12:30 UTC → IST
        self.assertIn(an.SUBMISSION_MODE, m.body)

    def test_no_faculty_falls_back_to_default_reply_to(self):
        an.send_assignment_assigned(self._assignment())
        self.assertEqual(mail.outbox[0].reply_to, ["admin.a@jdinstitute.edu.in"])

    def _post(self, published):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c.post("/api/academics/assignments/", {
            "subject": self.subject.pk, "program": self.program.pk,
            "campus": self.b1.campus_id,
            "batch": self.b1.pk, "title": "T", "max_marks": "10",
            "due_date": "2026-11-20T12:30:00Z", "is_published": published,
        }, format="json")

    def test_create_requires_campus_and_batch_must_match_it(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        body = {"subject": self.subject.pk, "program": self.program.pk,
                "title": "T", "max_marks": "10",
                "due_date": "2026-11-20T12:30:00Z"}
        r = c.post("/api/academics/assignments/", body, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("campus", r.json())
        other = Campus.objects.create(name="Other", code="OTH")
        r = c.post("/api/academics/assignments/",
                   {**body, "campus": other.pk, "batch": self.b1.pk},
                   format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("batch", r.json())

    def test_program_wide_reach_is_limited_to_the_campus(self):
        other = Campus.objects.create(name="Other", code="OTH")
        b3 = Batch.objects.create(name="BD-3", program=self.program,
                                  campus=other, academic_year=self.b1.academic_year)
        s = Student.objects.create(
            application_form_id="AF-9", student_name="Student 9",
            student_email="s9@example.com", gender="M", dob="2000-01-01",
            nationality="INDIAN", category="GENERAL",
            institute=self.program.institute, campus=other,
            program=self.program, academic_year=self.b1.academic_year,
        )
        Enrollment.objects.create(
            student=s, program=self.program, semester=self.sem1, campus=other,
            batch=b3, academic_year=self.b1.academic_year,
            status=Enrollment.Status.ACTIVE)
        # Campus-less (legacy) rows still reach every campus.
        a = self._assignment(batch=None)
        self.assertIn("s9@example.com", self._emails(a))
        a.campus = self.b1.campus
        self.assertEqual(self._emails(a),
                         ["s1@example.com", "s2@example.com", "s3@example.com"])

    @mock.patch.object(an, "schedule_assignment_assigned")
    def test_create_published_schedules_mail(self, sched):
        r = self._post(True)
        self.assertEqual(r.status_code, 201, r.content)
        sched.assert_called_once()

    @mock.patch.object(an, "schedule_assignment_assigned")
    def test_create_unpublished_is_silent_until_published(self, sched):
        r = self._post(False)
        self.assertEqual(r.status_code, 201, r.content)
        sched.assert_not_called()
        c = APIClient()
        c.force_authenticate(self.admin)
        pk = r.json()["id"]
        c.patch(f"/api/academics/assignments/{pk}/", {"title": "T2"}, format="json")
        sched.assert_not_called()
        c.patch(f"/api/academics/assignments/{pk}/", {"is_published": True},
                format="json")
        sched.assert_called_once()
        c.patch(f"/api/academics/assignments/{pk}/", {"title": "T3"}, format="json")
        sched.assert_called_once()  # already published → no re-send


class AssignmentSubmittedNotifyTests(AssignmentNotifyTests):
    """Student submits → faculty (assignment.created_by) gets the
    `academics.assignment_submitted.email` mail, Reply-To the student."""

    def _sub(self, created_by):
        from apps.academics.models import AssignmentSubmission
        a = self._assignment(created_by=created_by)
        s = Student.objects.get(application_form_id="AF-1")
        return AssignmentSubmission.objects.create(assignment=a, student=s)

    def test_mails_creator_with_vars(self):
        faculty = get_user_model().objects.create_user(
            username="fac", password="x", email="fac@example.com",
            full_name="Ann Rao")
        an.send_assignment_submitted(self._sub(faculty))
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ["fac@example.com"])
        self.assertEqual(m.reply_to, ["s1@example.com"])  # student answers
        for needle in ("Ann Rao", "Student 1", "Pattern Making", "Bodice block"):
            self.assertIn(needle, m.body)

    def test_no_creator_is_silent(self):
        self.assertIsNone(an.send_assignment_submitted(self._sub(None)))
        self.assertEqual(mail.outbox, [])
