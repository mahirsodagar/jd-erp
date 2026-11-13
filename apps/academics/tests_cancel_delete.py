"""Cancelled slots cannot take attendance; slots can be hard-deleted.

- Cancelling (DELETE /schedule/<pk>/) keeps the row but the roster
  endpoint must refuse to mark it — even for a superuser.
- DELETE /schedule/<pk>/delete/ erases the row; refused with 409 when
  attendance exists unless ?force=1.
- POST /schedule/bulk-delete/ wipes a batch's range, skipping marked
  slots unless force.
"""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Attendance, ScheduleSlot
from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)


class CancelDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(
            name="B.Des", code="BDES", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1)
        cls.batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year,
        )
        cls.ts = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
            academic_year=year,
        )
        cls.subject = Subject.objects.create(name="Core", code="CORE")
        cls.faculty = make_faculty(
            code="E1", name="Ann", campus=campus, institute=institute,
        )
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=sem,
            campus=campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )
        cls.admin = get_user_model().objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _slot(self, day: date):
        slot, _ = create_slot(
            batch=self.batch, subject=self.subject, instructor=self.faculty,
            classroom=None, time_slot=self.ts, date=day,
        )
        return slot

    def _mark(self, slot):
        return self.client.post(
            reverse("attendance-roster", args=[slot.pk]),
            {"marks": [{"student": self.student.id, "status": "PRESENT"}],
             "remarks": "done"},
            format="json",
        )

    def test_cancelled_slot_rejects_marking(self):
        slot = self._slot(date(2026, 7, 1))
        res = self.client.delete(reverse("schedule-detail", args=[slot.pk]))
        self.assertEqual(res.status_code, 204)
        slot.refresh_from_db()
        self.assertEqual(slot.status, ScheduleSlot.Status.CANCELLED)

        res = self._mark(slot)
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("cancelled", res.data["detail"].lower())
        self.assertFalse(Attendance.objects.filter(schedule_slot=slot).exists())

        roster = self.client.get(reverse("attendance-roster", args=[slot.pk]))
        self.assertEqual(roster.data["slot_status"], "CANCELLED")

    def test_purge_deletes_unmarked_slot(self):
        slot = self._slot(date(2026, 7, 1))
        res = self.client.delete(reverse("schedule-purge", args=[slot.pk]))
        self.assertEqual(res.status_code, 204)
        self.assertFalse(ScheduleSlot.objects.filter(pk=slot.pk).exists())

    def test_purge_refuses_marked_slot_unless_forced(self):
        slot = self._slot(date(2026, 7, 1))
        self.assertEqual(self._mark(slot).status_code, 200)
        url = reverse("schedule-purge", args=[slot.pk])
        res = self.client.delete(url)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data["attendance_count"], 1)
        self.assertTrue(ScheduleSlot.objects.filter(pk=slot.pk).exists())

        res = self.client.delete(url + "?force=1")
        self.assertEqual(res.status_code, 204)
        self.assertFalse(ScheduleSlot.objects.filter(pk=slot.pk).exists())
        self.assertFalse(Attendance.objects.filter(student=self.student).exists())

    def test_bulk_delete_skips_marked_unless_forced(self):
        s1 = self._slot(date(2026, 7, 1))
        s2 = self._slot(date(2026, 7, 2))
        self._slot(date(2026, 7, 20))  # outside range → untouched
        self.assertEqual(self._mark(s1).status_code, 200)

        url = reverse("schedule-bulk-delete")
        payload = {"batch": self.batch.id, "from": "2026-07-01",
                   "to": "2026-07-07"}
        res = self.client.post(url, payload, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data, {"deleted": 1, "skipped_with_attendance": 1})
        self.assertTrue(ScheduleSlot.objects.filter(pk=s1.pk).exists())
        self.assertFalse(ScheduleSlot.objects.filter(pk=s2.pk).exists())

        res = self.client.post(url, {**payload, "force": True}, format="json")
        self.assertEqual(res.data, {"deleted": 1, "skipped_with_attendance": 0})
        self.assertEqual(ScheduleSlot.objects.count(), 1)

    def test_absent_alerts_auto_sent_once(self):
        from apps.notifications.models import NotificationDispatchLog

        slot = self._slot(date(2026, 7, 1))
        url = reverse("attendance-roster", args=[slot.pk])
        body = {"marks": [{"student": self.student.id, "status": "ABSENT"}],
                "remarks": "x"}
        # No notify flag sent — alerts go out anyway (student mobile/email
        # are blank in this fixture, so only the log count matters).
        self.student.student_mobile = "9999999999"
        self.student.save(update_fields=["student_mobile"])
        res = self.client.post(url, body, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertGreater(res.data["notified_absent"], 0)
        first = NotificationDispatchLog.objects.count()
        self.assertGreater(first, 0)

        # Re-saving the same register must not alert the same student again.
        res = self.client.post(url, body, format="json")
        self.assertEqual(res.data["notified_absent"], 0)
        self.assertEqual(NotificationDispatchLog.objects.count(), first)

    def test_bulk_delete_needs_permission(self):
        user = get_user_model().objects.create_user(
            username="plain", password="x", email="p@example.com",
        )
        self.client.force_authenticate(user)
        res = self.client.post(
            reverse("schedule-bulk-delete"),
            {"batch": self.batch.id, "from": "2026-07-01", "to": "2026-07-07"},
            format="json",
        )
        self.assertEqual(res.status_code, 403)
