"""Overdue tasks: the assignee can record them as Incomplete or Overdue
(client bug report 2026-11-21); both stay open and still completable."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.tasks.models import Task

User = get_user_model()


class TaskLateStatusTests(TestCase):
    def setUp(self):
        self.creator = User.objects.create_user("boss", "boss@e.com", "x")
        self.assignee = User.objects.create_user("me", "me@e.com", "x")
        self.other = User.objects.create_user("other", "other@e.com", "x")
        today = timezone.localdate()
        self.late = Task.objects.create(
            name="Late", end_date=today - timedelta(days=1),
            assignee=self.assignee, created_by=self.creator,
        )
        self.due_today = Task.objects.create(
            name="Today", end_date=today,
            assignee=self.assignee, created_by=self.creator,
        )
        self.c = APIClient()
        self.c.force_authenticate(self.assignee)

    def _set(self, task, status, remarks="Blocked on vendor", client=None):
        return (client or self.c).post(
            f"/api/tasks/{task.id}/status/",
            {"status": status, "assignee_remarks": remarks}, format="json",
        )

    def test_assignee_sets_incomplete_then_overdue(self):
        r = self._set(self.late, Task.Status.INCOMPLETE)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], Task.Status.INCOMPLETE)
        self.assertEqual(r.data["assignee_remarks"], "Blocked on vendor")
        r = self._set(self.late, Task.Status.OVERDUE, remarks="Still waiting")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], Task.Status.OVERDUE)

    def test_only_after_end_date(self):
        r = self._set(self.due_today, Task.Status.OVERDUE)
        self.assertEqual(r.status_code, 400)
        self.assertIn("end date", r.data["detail"])

    def test_only_assignee(self):
        c = APIClient()
        c.force_authenticate(self.other)
        self.assertEqual(self._set(self.late, Task.Status.OVERDUE, client=c).status_code, 403)
        c.force_authenticate(self.creator)
        self.assertEqual(self._set(self.late, Task.Status.OVERDUE, client=c).status_code, 403)

    def test_remarks_required_and_only_late_statuses(self):
        r = self._set(self.late, Task.Status.OVERDUE, remarks="")
        self.assertEqual(r.status_code, 400)
        r = self._set(self.late, Task.Status.COMPLETED)
        self.assertEqual(r.status_code, 400)
        r = self._set(self.late, Task.Status.PENDING)
        self.assertEqual(r.status_code, 400)

    def test_completed_task_is_final(self):
        self.late.status = Task.Status.COMPLETED
        self.late.save(update_fields=["status"])
        self.assertEqual(self._set(self.late, Task.Status.OVERDUE).status_code, 400)

    def test_late_task_can_still_be_completed_and_edited(self):
        self._set(self.late, Task.Status.INCOMPLETE)
        r = self.c.patch(f"/api/tasks/{self.late.id}/",
                         {"assignee_remarks": "Nearly there"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.c.post(f"/api/tasks/{self.late.id}/complete/",
                        {"assignee_remarks": "Done late"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], Task.Status.COMPLETED)

    def test_pending_filter_includes_late_statuses(self):
        self._set(self.late, Task.Status.OVERDUE)
        ids = {t["id"] for t in self.c.get("/api/tasks/?status=pending").data}
        self.assertEqual(ids, {self.late.id, self.due_today.id})
        ids = {t["id"] for t in self.c.get("/api/tasks/?status=overdue").data}
        self.assertEqual(ids, {self.late.id})
        self.assertEqual(self.c.get("/api/tasks/?status=completed").data, [])

    def test_creator_gets_a_bell(self):
        from apps.notifications.models import InAppNotification

        self._set(self.late, Task.Status.INCOMPLETE)
        n = InAppNotification.objects.filter(recipient=self.creator).latest("id")
        self.assertIn("incomplete", n.title.lower())
