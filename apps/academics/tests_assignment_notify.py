"""New-assignment e-mail: MSG91 `assignmentassigned`, one per reached
student, fired on publish (create or unpublished → published)."""

from datetime import date, datetime, timezone as dt_tz
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.academics import assignment_notify as an
from apps.academics.models import Assignment
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
)

MSG91_OK = (True, '{"status": "success"}')


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

    @mock.patch("apps.notifications.msg91.send_msg91_template",
                return_value=MSG91_OK)
    def test_sends_msg91_template_with_vars(self, msg91):
        n = an.send_assignment_assigned(self._assignment())
        self.assertEqual(n, 2)
        k = msg91.call_args_list[0].kwargs
        self.assertEqual(k["template_name"], "assignmentassigned")
        self.assertEqual(k["domain"], "mail.jdinstitute.com")
        v = k["variables"]
        self.assertEqual(v["VAR2"], "Pattern Making")
        self.assertEqual(v["VAR3"], "Bodice block")
        self.assertEqual(v["VAR4"], "20-11-2026 06:00 PM")  # 12:30 UTC → IST
        self.assertEqual(v["VAR5"], an.SUBMISSION_MODE)

    def _post(self, published):
        c = APIClient()
        c.force_authenticate(self.admin)
        return c.post("/api/academics/assignments/", {
            "subject": self.subject.pk, "program": self.program.pk,
            "batch": self.b1.pk, "title": "T", "max_marks": "10",
            "due_date": "2026-11-20T12:30:00Z", "is_published": published,
        }, format="json")

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
    """Student submits → faculty (assignment.created_by) gets MSG91
    `assignment_submitted`."""

    def _sub(self, created_by):
        from apps.academics.models import AssignmentSubmission
        a = self._assignment(created_by=created_by)
        s = Student.objects.get(application_form_id="AF-1")
        return AssignmentSubmission.objects.create(assignment=a, student=s)

    @mock.patch("apps.notifications.msg91.send_msg91_template",
                return_value=MSG91_OK)
    def test_mails_creator_with_vars(self, msg91):
        faculty = get_user_model().objects.create_user(
            username="fac", password="x", email="fac@example.com",
            full_name="Ann Rao")
        an.send_assignment_submitted(self._sub(faculty))
        k = msg91.call_args.kwargs
        self.assertEqual(k["template_name"], "assignment_submitted")
        self.assertEqual(k["recipient_email"], "fac@example.com")
        self.assertEqual(k["variables"], {
            "Faculty_Name": "Ann Rao", "Student_Name": "Student 1",
            "Subject_Name": "Pattern Making", "Assignment_Title": "Bodice block",
        })

    @mock.patch("apps.notifications.msg91.send_msg91_template",
                return_value=MSG91_OK)
    def test_no_creator_is_silent(self, msg91):
        self.assertIsNone(an.send_assignment_submitted(self._sub(None)))
        msg91.assert_not_called()
