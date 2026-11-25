"""Side-effects for the tasks module — bell + e-mail notifications.

Kept out of views so the same hooks can fire from admin or future bulk
operations without duplicating the recipient/template logic. The mail
wording is the system e-mails `tasks.assigned.email` and
`tasks.completed.email` (Communication → System Emails).
"""

import logging

from django.utils import timezone

from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification, NotificationDispatchLog
from apps.notifications.services import send_system_email

from .models import Task

logger = logging.getLogger(__name__)

ASSIGNED_KEY = "tasks.assigned.email"
COMPLETED_KEY = "tasks.completed.email"


def _display(user) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "username", "") or "")


def _send(key: str, *, recipient: str, context: dict, task: Task) -> None:
    log = send_system_email(key, recipient=recipient, context=context, related=task)
    if getattr(log, "status", "") != NotificationDispatchLog.Status.SENT:
        logger.warning(
            "Task #%s %s email to %s failed: %s",
            task.id, key, recipient, getattr(log, "error", ""),
        )


def notify_task_assigned(*, task: Task) -> None:
    """Best-effort bell + email to the assignee when a task is created
    or reassigned to them."""
    creator_name = _display(task.created_by)
    notify(
        [task.assignee], kind=InAppNotification.Kind.TASK,
        title=f"New task: {task.name}",
        body=f"Assigned by {creator_name}. Due {task.end_date.strftime('%d-%m-%Y')}.",
        link="/tasks", exclude_user=task.created_by,
    )
    recipient = (task.assignee.email or "").strip()
    if not recipient:
        return
    _send(ASSIGNED_KEY, recipient=recipient, task=task, context={
        "Assignee_Name": _display(task.assignee),
        "Creator_Name": creator_name,
        "Task_Name": task.name,
        "Due_Date": task.end_date.strftime("%d-%m-%Y"),
        "Task_Description": task.description or "(none)",
    })


def notify_task_late_status(*, task: Task) -> None:
    """Bell only, to the creator: the assignee flagged an overdue task as
    Incomplete / Overdue. No email — it is a progress note, not closure."""
    assignee_name = _display(task.assignee)
    label = Task.Status(task.status).label
    notify(
        [task.created_by], kind=InAppNotification.Kind.TASK,
        title=f"Task {label.lower()}: {task.name}",
        body=f"{assignee_name} marked it {label.lower()}. "
             f"{task.assignee_remarks}".strip(),
        link="/tasks", exclude_user=task.assignee,
    )


def notify_task_completed(*, task: Task) -> None:
    """Best-effort bell + email to the creator when the assignee completes it."""
    assignee_name = _display(task.assignee)
    notify(
        [task.created_by], kind=InAppNotification.Kind.TASK,
        title=f"Task completed: {task.name}",
        body=f"{assignee_name} marked it done.",
        link="/tasks", exclude_user=task.assignee,
    )
    recipient = (task.created_by.email or "").strip()
    if not recipient:
        return
    completed_on = timezone.localtime(task.completed_at or timezone.now())
    _send(COMPLETED_KEY, recipient=recipient, task=task, context={
        "Creator_Name": _display(task.created_by),
        "Assignee_Name": assignee_name,
        "Task_Name": task.name,
        "Completed_On": completed_on.strftime("%d-%m-%Y %H:%M"),
        "Assigned_On": timezone.localtime(task.created_at).strftime("%d-%m-%Y %H:%M"),
        "Assignee_Remarks": task.assignee_remarks or "(none)",
    })
