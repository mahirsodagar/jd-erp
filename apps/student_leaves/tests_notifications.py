"""Student leave mail copies the campus leave inbox (client list
2026-11-20): applied → mentor with the inbox in CC, approved → student
with the inbox in CC. Duplicates with To / existing CCs are dropped."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.student_leaves.notifications import (
    send_leave_accepted, send_leave_applied,
)


def _app(campus_code="GOA", **extra):
    student = SimpleNamespace(
        student_name="Asha", student_email="asha@example.com",
        campus=SimpleNamespace(code=campus_code),
    )
    fields = dict(
        pk=1, student=student,
        leave_date=date(2026, 11, 20), leave_edate=date(2026, 11, 21),
        days=2, student_remarks="fever",
        batch_mentor_email="mentor@jdinstitute.edu.in",
        module_mentor_email="module@jdinstitute.edu.in",
        cc_emails=[],
    )
    fields.update(extra)
    return SimpleNamespace(**fields)


@override_settings(
    LEAVES_HR_INBOX="leave@jdinstitute.edu.in",
    LEAVE_CAMPUS_INBOXES={"GOA": "leave.goa@jdinstitute.edu.in", "COK": ""},
)
class StudentLeaveCampusCcTests(SimpleTestCase):
    def _sent(self, fn, app):
        with patch("apps.student_leaves.notifications.queue_notification") as q:
            fn(app)
        return q.call_args.kwargs

    def test_applied_copies_the_campus_leave_inbox(self):
        kw = self._sent(send_leave_applied, _app())
        self.assertEqual(kw["recipient"], "mentor@jdinstitute.edu.in")
        self.assertEqual(
            kw["cc"].split(","),
            ["module@jdinstitute.edu.in", "asha@example.com",
             "leave.goa@jdinstitute.edu.in"],
        )

    def test_accepted_copies_the_campus_leave_inbox(self):
        kw = self._sent(send_leave_accepted, _app())
        self.assertEqual(kw["recipient"], "asha@example.com")
        self.assertEqual(kw["cc"], "leave.goa@jdinstitute.edu.in")

    def test_unlisted_campus_falls_back_to_hr_inbox(self):
        kw = self._sent(send_leave_accepted, _app(campus_code="COK"))
        self.assertEqual(kw["cc"], "leave@jdinstitute.edu.in")

    def test_inbox_already_in_cc_is_not_duplicated(self):
        kw = self._sent(send_leave_applied,
                        _app(cc_emails=["Leave.GOA@jdinstitute.edu.in"]))
        self.assertEqual(kw["cc"].lower().count("leave.goa@"), 1)
