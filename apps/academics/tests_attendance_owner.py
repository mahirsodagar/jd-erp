"""Only the faculty member assigned to a slot may mark its attendance,
and "my timetable" only ever returns the caller's own classes.

Client rule 2026-11-21. `academics.attendance.mark` stays as the admin
override and is stripped from the Faculty / HOD roles (roles.0005).
"""

from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import ScheduleSlot
from apps.academics.services import create_slot
from apps.academics.tests_electives import make_faculty
from apps.admissions.models import Enrollment, Student
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, Subject,
    TimeSlot,
)
from apps.roles.models import Permission, Role

User = get_user_model()


def _user_for(employee, username):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.com")
    employee.user_account = user
    employee.save(update_fields=["user_account"])
    return user


class AttendanceOwnerTests(TestCase):
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
        batch = Batch.objects.create(
            name="BD-1", program=program, campus=campus, academic_year=year,
        )
        ts1 = TimeSlot.objects.create(
            label="Slot 1", start_time=time(9, 0), end_time=time(10, 0),
        )
        ts2 = TimeSlot.objects.create(
            label="Slot 2", start_time=time(10, 0), end_time=time(11, 0),
        )
        subject = Subject.objects.create(name="Core", code="CORE")
        cls.owner = make_faculty(
            code="E1", name="Ann", campus=campus, institute=institute,
        )
        cls.other = make_faculty(
            code="E2", name="Bob", campus=campus, institute=institute,
        )
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=institute, campus=campus, program=program,
            academic_year=year,
        )
        Enrollment.objects.create(
            student=cls.student, program=program, semester=sem,
            campus=campus, batch=batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )
        cls.slot, _ = create_slot(
            batch=batch, subject=subject, instructor=cls.owner,
            classroom=None, time_slot=ts1, date=date(2026, 7, 1),
        )
        cls.other_slot, _ = create_slot(
            batch=batch, subject=subject, instructor=cls.other,
            classroom=None, time_slot=ts2, date=date(2026, 7, 1),
        )
        # The slot's date is in the past, so the 15-minute marking window
        # is closed; an admin re-open keeps it markable for these tests
        # (ownership is what is under test here, not the window).
        ScheduleSlot.objects.filter(pk=cls.slot.pk).update(
            attendance_unlocked=True,
        )
        cls.owner_user = _user_for(cls.owner, "ann")
        cls.other_user = _user_for(cls.other, "bob")
        # A plain Faculty-role user: no academics.* keys at all.
        faculty_role, _ = Role.objects.get_or_create(
            name="Faculty", defaults={"is_system": True},
        )
        faculty_role.permissions.clear()
        faculty_role.users.add(cls.owner_user, cls.other_user)
        # An admin role holding the override key.
        perm, _ = Permission.objects.get_or_create(
            key="academics.attendance.mark",
            defaults={"module": "academics", "label": "Mark any"},
        )
        admin_role = Role.objects.create(name="Academic Admin")
        admin_role.permissions.add(perm)
        cls.admin_user = User.objects.create_user(username="adm", password="x", email="adm@example.com")
        admin_role.users.add(cls.admin_user)

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("attendance-roster", args=[self.slot.pk])

    def _mark(self):
        return self.client.post(self.url, {
            "marks": [{"student": self.student.id, "status": "PRESENT"}],
            "remarks": "Unit 1",
        }, format="json")

    def test_assigned_faculty_can_read_and_mark(self):
        self.client.force_authenticate(self.owner_user)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["can_mark"])
        self.assertEqual(self._mark().status_code, 200)

    def test_other_faculty_is_refused(self):
        self.client.force_authenticate(self.other_user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self._mark().status_code, 403)

    def test_admin_override_still_marks_any_slot(self):
        self.client.force_authenticate(self.admin_user)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["can_mark"])
        self.assertEqual(self._mark().status_code, 200)

    def test_view_roster_only_reads_with_can_mark_false(self):
        perm, _ = Permission.objects.get_or_create(
            key="academics.attendance.view_roster",
            defaults={"module": "academics", "label": "Roster"},
        )
        role = Role.objects.create(name="Reader")
        role.permissions.add(perm)
        role.users.add(self.other_user)
        self.client.force_authenticate(self.other_user)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["can_mark"])
        self.assertEqual(self._mark().status_code, 403)

    def test_my_timetable_returns_only_own_classes(self):
        self.client.force_authenticate(self.owner_user)
        res = self.client.get(reverse("timetable-me"),
                              {"from": "2026-07-01", "to": "2026-07-01"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([s["id"] for s in res.data], [self.slot.id])

    def test_my_timetable_status_filter(self):
        self.slot.status = ScheduleSlot.Status.CANCELLED
        self.slot.save(update_fields=["status"])
        self.client.force_authenticate(self.owner_user)
        url = reverse("timetable-me")
        self.assertEqual(self.client.get(url).data, [])
        self.assertEqual(
            [s["id"] for s in self.client.get(url, {"status": "any"}).data],
            [self.slot.id],
        )
        self.assertEqual(
            [s["id"] for s in self.client.get(url, {"status": "cancelled"}).data],
            [self.slot.id],
        )


class DropMarkAnyFromFacultyRolesTests(TestCase):
    def test_migration_logic_removes_key_from_faculty_and_hod_only(self):
        from importlib import import_module
        from django.apps import apps as global_apps

        mod = import_module(
            "apps.roles.migrations.0005_faculty_hod_drop_mark_any_attendance",
        )
        perm, _ = Permission.objects.get_or_create(
            key="academics.attendance.mark",
            defaults={"module": "academics", "label": "x"},
        )
        roles = {}
        for name in ("Faculty", "HOD", "Admin"):
            role, _ = Role.objects.get_or_create(name__iexact=name,
                                                 defaults={"name": name})
            role.permissions.add(perm)
            roles[name] = role

        def holds(name):
            return roles[name].permissions.filter(pk=perm.pk).exists()

        mod.drop(global_apps, None)
        self.assertFalse(holds("Faculty"))
        self.assertFalse(holds("HOD"))
        self.assertTrue(holds("Admin"))
        mod.restore(global_apps, None)
        self.assertTrue(holds("Faculty"))
        self.assertTrue(holds("HOD"))
