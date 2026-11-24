"""Dashboard "Total Classes" tile: /api/academics/timetable/me/summary/
counts the caller's own classes and nobody else's."""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import ScheduleSlot
from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject, TimeSlot,
)

User = get_user_model()


def _user_for(employee, username):
    user = User.objects.create_user(username=username, password="x",
                                    email=f"{username}@example.com")
    employee.user_account = user
    employee.save(update_fields=["user_account"])
    return user


class TimetableSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES",
                                         institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        batch = Batch.objects.create(name="BD-1", program=program,
                                     campus=campus, academic_year=year)
        cls.slots = [
            TimeSlot.objects.create(label=f"Slot {i}", start_time=time(8 + i, 0),
                                    end_time=time(9 + i, 0))
            for i in range(4)
        ]
        subject = Subject.objects.create(name="Core", code="CORE")
        cls.me = make_faculty(code="E1", name="Ann", campus=campus,
                              institute=institute)
        cls.other = make_faculty(code="E2", name="Bob", campus=campus,
                                 institute=institute)
        today = timezone.localdate()
        # Mine: two scheduled (one today), one completed, one cancelled.
        cls.today_slot, _ = create_slot(batch=batch, subject=subject,
                                        instructor=cls.me, classroom=None,
                                        time_slot=cls.slots[0], date=today)
        create_slot(batch=batch, subject=subject, instructor=cls.me,
                    classroom=None, time_slot=cls.slots[1],
                    date=date(2026, 7, 1))
        done, _ = create_slot(batch=batch, subject=subject, instructor=cls.me,
                              classroom=None, time_slot=cls.slots[2],
                              date=date(2026, 7, 2))
        ScheduleSlot.objects.filter(pk=done.pk).update(
            status=ScheduleSlot.Status.COMPLETED)
        gone, _ = create_slot(batch=batch, subject=subject, instructor=cls.me,
                              classroom=None, time_slot=cls.slots[3],
                              date=date(2026, 7, 3))
        ScheduleSlot.objects.filter(pk=gone.pk).update(
            status=ScheduleSlot.Status.CANCELLED)
        # Someone else's class must never be counted.
        create_slot(batch=batch, subject=subject, instructor=cls.other,
                    classroom=None, time_slot=cls.slots[1], date=today)
        cls.me_user = _user_for(cls.me, "ann")
        cls.plain_user = User.objects.create_user(
            username="nobody", password="x", email="nobody@example.com")

    def _get(self, user, **params):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(reverse("timetable-me-summary"), params)

    def test_counts_only_my_classes_and_excludes_cancelled_from_total(self):
        data = self._get(self.me_user).json()
        self.assertEqual(data, {"total": 3, "scheduled": 2, "completed": 1,
                                "cancelled": 1, "today": 1})

    def test_date_range_narrows_the_counts(self):
        data = self._get(self.me_user, **{"from": "2026-07-01",
                                          "to": "2026-07-02"}).json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["cancelled"], 0)

    def test_user_without_employee_gets_zeros(self):
        data = self._get(self.plain_user).json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["today"], 0)

    def test_requires_login(self):
        resp = APIClient().get(reverse("timetable-me-summary"))
        self.assertEqual(resp.status_code, 401)
