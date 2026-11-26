"""Timetable list (2026-11-26): staff holding only `academics.schedule.view`
see their OWN classes; `academics.schedule.view_all` opens everyone's."""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Subject, TimeSlot,
)
from apps.roles.models import Permission, Role

User = get_user_model()


def _perm(key):
    perm, _ = Permission.objects.get_or_create(
        key=key, defaults={"module": "academics", "label": key})
    return perm


def _user_with(username, *keys, employee=None):
    user = User.objects.create_user(username=username, password="x",
                                    email=f"{username}@example.com")
    role = Role.objects.create(name=f"role-{username}")
    role.permissions.add(*[_perm(k) for k in keys])
    role.users.add(user)
    if employee is not None:
        employee.user_account = user
        employee.save(update_fields=["user_account"])
    return user


class ScheduleOwnOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(name="B.Des", code="BDES",
                                         institute=institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))
        batch = Batch.objects.create(name="BD-1", program=program,
                                     campus=campus, academic_year=year)
        s1 = TimeSlot.objects.create(label="S1", start_time=time(9, 0), end_time=time(10, 0))
        s2 = TimeSlot.objects.create(label="S2", start_time=time(10, 0), end_time=time(11, 0))
        subject = Subject.objects.create(name="Core", code="CORE")
        ann = make_faculty(code="E1", name="Ann", campus=campus, institute=institute)
        bob = make_faculty(code="E2", name="Bob", campus=campus, institute=institute)
        cls.mine, _ = create_slot(batch=batch, subject=subject, instructor=ann,
                                  classroom=None, time_slot=s1, date=date(2026, 7, 1))
        cls.theirs, _ = create_slot(batch=batch, subject=subject, instructor=bob,
                                    classroom=None, time_slot=s2, date=date(2026, 7, 1))
        cls.ann = _user_with("ann", "academics.schedule.view", employee=ann)
        cls.ann.campuses.add(campus)
        cls.hod = _user_with("hod", "academics.schedule.view",
                             "academics.schedule.view_all")
        cls.no_employee = _user_with("clerk", "academics.schedule.view")

    def _ids(self, user):
        c = APIClient()
        c.force_authenticate(user)
        r = c.get(reverse("schedule-list-create"), {"from": "2026-07-01", "to": "2026-07-01"})
        self.assertEqual(r.status_code, 200, r.content)
        return sorted(s["id"] for s in r.json())

    def test_plain_view_key_lists_only_the_callers_own_classes(self):
        self.assertEqual(self._ids(self.ann), [self.mine.pk])

    def test_view_all_lists_everyone(self):
        self.assertEqual(self._ids(self.hod), sorted([self.mine.pk, self.theirs.pk]))

    def test_staff_login_without_an_employee_row_sees_nothing(self):
        self.assertEqual(self._ids(self.no_employee), [])

    def test_instructor_filter_cannot_widen_own_scope(self):
        c = APIClient()
        c.force_authenticate(self.ann)
        r = c.get(reverse("schedule-list-create"),
                  {"instructor": self.theirs.instructor_id})
        self.assertEqual(r.json(), [])
