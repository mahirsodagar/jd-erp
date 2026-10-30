"""Side-effects for the tasks module — currently just email notifications.

Kept out of views so the same hooks can fire from admin or future bulk
operations without duplicating the recipient/template logic.
"""

import logging

from django.utils import timezone

from apps.notifications.email import send_email
from apps.notifications.inapp import notify
from apps.notifications.models import InAppNotification

from .models import Task

logger = logging.getLogger(__name__)


def notify_task_assigned(*, task: Task) -> None:
    """Best-effort bell + email to the assignee when a task is created
    or reassigned to them."""
    creator_name = (
        task.created_by.full_name or task.created_by.username
    )
    notify(
        [task.assignee], kind=InAppNotification.Kind.TASK,
        title=f"New task: {task.name}",
        body=f"Assigned by {creator_name}. Due {task.end_date.strftime('%d-%m-%Y')}.",
        link="/tasks", exclude_user=task.created_by,
    )
    recipient = (task.assignee.email or "").strip()
    if not recipient:
        return
    assignee_name = (
        task.assignee.full_name or task.assignee.username
    )
    subject = f"New task assigned: {task.name}"
    body = (
        f"Hi {assignee_name},\n\n"
        f"{creator_name} has assigned a task to you.\n\n"
        f"Task: {task.name}\n"
        f"Due:  {task.end_date.strftime('%d-%m-%y')}\n"
        f"\nDetails:\n{task.description or '(none)'}\n\n"
        "Open the ERP to update progress or mark it complete.\n\n"
        "— JD ERP"
    )
    ok, msg = send_email(recipient=recipient, subject=subject, body=body)
    if not ok:
        logger.warning(
            "Task #%s assign email to %s failed: %s",
            task.id, recipient, msg,
        )


def notify_task_completed(*, task: Task) -> None:
    """Best-effort bell + email to the creator when the assignee completes it."""
    assignee_name = (
        task.assignee.full_name or task.assignee.username
    )
    notify(
        [task.created_by], kind=InAppNotification.Kind.TASK,
        title=f"Task completed: {task.name}",
        body=f"{assignee_name} marked it done.",
        link="/tasks", exclude_user=task.assignee,
    )
    recipient = (task.created_by.email or "").strip()
    if not recipient:
        return
    creator_name = (
        task.created_by.full_name or task.created_by.username
    )
    completed_on = (task.completed_at or timezone.now()).strftime(
        "%d-%m-%y %H:%M",
    )
    subject = f"Task completed: {task.name}"
    body = (
        f"Hi {creator_name},\n\n"
        f"{assignee_name} has marked the following task as completed.\n\n"
        f"Task:          {task.name}\n"
        f"Completed on:  {completed_on}\n"
        f"Assigned on:   {task.created_at.strftime('%d-%m-%y %H:%M')}\n"
        f"\nAssignee remarks:\n{task.assignee_remarks or '(none)'}\n\n"
        "— JD ERP"
    )
    ok, msg = send_email(recipient=recipient, subject=subject, body=body)
    if not ok:
        logger.warning(
            "Task #%s complete email to %s failed: %s",
            task.id, recipient, msg,
        )
