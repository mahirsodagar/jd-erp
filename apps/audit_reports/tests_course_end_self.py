"""Module End Report filing is self-only for plain faculty.

Client, 2026-11-25: a faculty login must not pick (or be able to post)
another instructor's name; the report is filed under their own employee
record. HOD / admin — anyone holding `audit.course_end.view_all` — may
still file on a colleague's behalf.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.tests_electives import make_faculty
from apps.audit_reports.models import CourseEndReport
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject,
)
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions


def _role(name, *keys):
    r = Role.objects.create(name=f"T-{name}")
    r.permissions.add(*Permission.objects.filter(key__in=keys))
    return r


class CourseEndSelfOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        cls.batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year)
        cls.subject = Subject.objects.create(
            name="Drawing", code="DRAW", program=program)
        cls.me = make_faculty(code="E1", name="Ann", campus=campus, institute=inst)
        cls.other = make_faculty(code="E2", name="Bob", campus=campus, institute=inst)

        User = get_user_model()
        cls.fac_user = User.objects.create_user(
            username="ann", password="x", email="ann@example.com")
        cls.me.user_account = cls.fac_user
        cls.me.save(update_fields=["user_account"])
        cls.fac_user.roles.add(_role("Faculty", "audit.course_end.submit"))

        cls.hod_user = User.objects.create_user(
            username="hod", password="x", email="hod@example.com")
        cls.hod_user.roles.add(_role(
            "HOD", "audit.course_end.submit", "audit.course_end.view_all"))

    def _payload(self, instructor):
        return {
            "instructor": instructor.pk, "subject": self.subject.pk,
            "batch": self.batch.pk, "completed_on": "2026-11-20",
            "summary": "Module wrapped up",
        }

    def test_faculty_posting_another_name_is_filed_under_their_own(self):
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-list-create"),
                   self._payload(self.other), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["instructor"], self.me.pk)
        self.assertEqual(
            CourseEndReport.objects.get(pk=r.data["id"]).instructor_id, self.me.pk)

    def test_faculty_posting_own_name_still_works(self):
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-list-create"),
                   self._payload(self.me), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["instructor"], self.me.pk)
        self.assertEqual(r.data["report_type"], "END_MODULE")  # default

    def test_mid_and_end_module_reports_may_coexist(self):
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-list-create"),
                   {**self._payload(self.me), "report_type": "MID_MODULE"},
                   format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["report_type_label"], "Mid Module")
        r = c.post(reverse("course-end-list-create"),
                   {**self._payload(self.me), "report_type": "END_MODULE"},
                   format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # Same type twice is still one-per-(instructor, subject, batch).
        r = c.post(reverse("course-end-list-create"),
                   {**self._payload(self.me), "report_type": "END_MODULE"},
                   format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_view_all_holder_may_file_for_a_colleague(self):
        c = APIClient()
        c.force_authenticate(self.hod_user)
        r = c.post(reverse("course-end-list-create"),
                   self._payload(self.other), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["instructor"], self.other.pk)

    # --- Edit & resend a RETURNED report ------------------------------

    def _returned(self, instructor):
        return CourseEndReport.objects.create(
            instructor=instructor, subject=self.subject, batch=self.batch,
            completed_on=date(2026, 11, 20), summary="v1",
            hod_status="RETURNED", hod_remarks="Add outcomes",
            hod_reviewed_by=self.hod_user,
        )

    def test_author_resends_returned_report_and_it_goes_pending(self):
        rep = self._returned(self.me)
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-resubmit", args=[rep.pk]),
                   {"summary": "v2", "learning_outcomes": "Sketching",
                    "instructor": self.other.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        rep.refresh_from_db()
        self.assertEqual(rep.hod_status, "PENDING")
        self.assertEqual(rep.summary, "v2")
        self.assertEqual(rep.learning_outcomes, "Sketching")
        self.assertEqual(rep.instructor_id, self.me.pk)   # not re-pointable
        self.assertEqual(rep.hod_remarks, "Add outcomes")  # history kept
        self.assertIsNone(rep.hod_reviewed_at)
        self.assertIsNone(rep.hod_reviewed_by)

    def test_resend_refused_unless_returned(self):
        rep = self._returned(self.me)
        rep.hod_status = "PENDING"
        rep.save(update_fields=["hod_status"])
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-resubmit", args=[rep.pk]),
                   {"summary": "v2"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_resend_refused_for_someone_elses_report(self):
        rep = self._returned(self.other)
        c = APIClient()
        c.force_authenticate(self.fac_user)
        r = c.post(reverse("course-end-resubmit", args=[rep.pk]),
                   {"summary": "v2"}, format="json")
        self.assertEqual(r.status_code, 403, r.content)
