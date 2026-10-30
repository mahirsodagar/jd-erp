"""The bell: tasks, leaves and timetable changes write a row for the
people concerned; the API shows each user only their own."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.leaves.models import LeaveApplication, LeaveType
from apps.master.models import Campus, Institute
from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification
from apps.relieving.tests_notifications import make_employee
from apps.tasks.models import Task

User = get_user_model()


class BellApiTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="a", email="a@e.com", password="x")
        self.b = User.objects.create_user(username="b", email="b@e.com", password="x")
        self.client = APIClient()
        self.client.force_authenticate(self.a)

    def test_only_own_rows_and_unread_count(self):
        notify([self.a, self.b], title="Hello", link="/tasks")
        notify([self.b], title="Only b")
        r = self.client.get("/api/notifications/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["unread_count"], 1)
        self.assertEqual([n["title"] for n in r.json()["results"]], ["Hello"])

    def test_mark_read_and_read_all_are_scoped(self):
        notify([self.a, self.b], title="One")
        notify([self.a], title="Two")
        mine = InAppNotification.objects.filter(recipient=self.a).order_by("id")
        theirs = InAppNotification.objects.get(recipient=self.b)

        r = self.client.post(f"/api/notifications/{theirs.id}/read/")
        self.assertEqual(r.status_code, 404)  # not mine

        r = self.client.post(f"/api/notifications/{mine[0].id}/read/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.client.get("/api/notifications/").json()["unread_count"], 1)

        self.client.post("/api/notifications/read-all/")
        self.assertEqual(self.client.get("/api/notifications/").json()["unread_count"], 0)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)

    def test_helper_skips_none_inactive_and_actor(self):
        off = User.objects.create_user(username="off", email="o@e.com", password="x",
                                       is_active=False)
        n = notify([None, self.a, self.a, off, self.b], title="T", exclude_user=self.b)
        self.assertEqual(n, 1)
        self.assertEqual(InAppNotification.objects.get().recipient, self.a)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BellHooksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        cls.boss = User.objects.create_user(
            username="boss", email="boss@e.com", password="x", full_name="Boss",
        )
        cls.emp_user = User.objects.create_user(
            username="asha", email="asha@e.com", password="x", full_name="Asha",
        )
        cls.emp = make_employee("ASHA", institute=institute, campus=campus,
                                user_account=cls.emp_user)
        cls.lt = LeaveType.objects.create(
            code="CASUAL", name="Casual Leave", category="LEAVE",
            half_day_allowed=True, enforce_balance=False,
        )

    def _bell(self, user):
        return list(InAppNotification.objects.filter(recipient=user)
                    .order_by("id").values_list("title", flat=True))

    def test_task_assigned_notifies_assignee_not_creator(self):
        c = APIClient()
        c.force_authenticate(self.boss)
        r = c.post("/api/tasks/", {
            "name": "Prepare report", "description": "", "end_date": "2026-11-05",
            "assignee": self.emp_user.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._bell(self.emp_user), ["New task: Prepare report"])
        self.assertEqual(self._bell(self.boss), [])

        task = Task.objects.get()
        c2 = APIClient()
        c2.force_authenticate(self.emp_user)
        r = c2.post(f"/api/tasks/{task.id}/complete/",
                    {"assignee_remarks": "done"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._bell(self.boss), ["Task completed: Prepare report"])

    def test_leave_applied_notifies_manager_and_decision_notifies_employee(self):
        c = APIClient()
        c.force_authenticate(self.emp_user)
        r = c.post("/api/leaves/applications/", {
            "leave_type": self.lt.id, "from_date": "2026-11-10",
            "to_date": "2026-11-10", "from_session": 2,
            "reason": "Personal work", "manager_email": "boss@e.com",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self._bell(self.boss), ["Leave request from Asha"])
        self.assertEqual(self._bell(self.emp_user), [])

        app = LeaveApplication.objects.get()
        c2 = APIClient()
        c2.force_authenticate(self.boss)
        r = c2.patch(f"/api/leaves/applications/{app.id}/decision/",
                     {"status": 2, "remarks": "Enjoy"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._bell(self.emp_user), ["Leave approved"])
        n = InAppNotification.objects.get(recipient=self.emp_user)
        self.assertEqual(n.link, "/leaves/my")
        self.assertIn("Enjoy", n.body)

    def test_timetable_slot_notifies_instructor_and_students(self):
        from datetime import time

        from apps.academics.models import ScheduleSlot
        from apps.academics.timetable_notify import notify_batch_published, notify_slot
        from apps.admissions.models import Enrollment, Student
        from apps.master.models import AcademicYear, Batch, Program, Semester, Subject, TimeSlot

        program = Program.objects.create(name="B.Des", code="BDES",
                                         institute=self.emp.institute)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        sem = Semester.objects.create(name="Sem 1", number=1)
        batch = Batch.objects.create(name="BD-1", program=program,
                                     campus=self.emp.campus, academic_year=year)
        ts = TimeSlot.objects.create(label="Slot 1", start_time=time(9, 0),
                                     end_time=time(10, 0), academic_year=year)
        subject = Subject.objects.create(name="Core Studio", code="CORE")
        stu_user = User.objects.create_user(username="stu", email="s@e.com", password="x")
        student = Student.objects.create(
            application_form_id="AF-STU", student_name="Stu", gender="M",
            dob="2000-01-01", nationality="INDIAN", category="GENERAL",
            institute=self.emp.institute, campus=self.emp.campus,
            program=program, academic_year=year, user_account=stu_user,
        )
        Enrollment.objects.create(
            student=student, program=program, semester=sem,
            campus=self.emp.campus, batch=batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

        slot = ScheduleSlot.objects.create(
            batch=batch, subject=subject, instructor=self.emp,
            time_slot=ts, date=date(2026, 11, 12),
        )
        notify_slot(slot, verb="updated", actor=self.boss)
        self.assertEqual(self._bell(self.emp_user), ["Class updated"])
        self.assertEqual(self._bell(stu_user), ["Class updated"])
        self.assertEqual(InAppNotification.objects.get(recipient=stu_user).link,
                         "/portal/timetable")
        self.assertEqual(InAppNotification.objects.get(recipient=self.emp_user).link,
                         "/schedule/me")

        notify_batch_published(batch, instructors=[self.emp],
                               start_date=date(2026, 11, 1), end_date=date(2026, 11, 30),
                               created=12, actor=self.boss)
        self.assertEqual(self._bell(stu_user)[-1], "Timetable published")
        self.assertEqual(self._bell(self.boss), [])
