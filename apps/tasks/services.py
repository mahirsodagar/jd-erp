"""Side-effects for the tasks module — currently just email notifications.

Kept out of views so the same hooks can fire from admin or future bulk
operations without duplicating the recipient/template logic.
"""

import logging

from django.utils import timezone

from apps.notifications.email import send_email

from .models import Task

logger = logging.getLogger(__name__)


def notify_task_assigned(*, task: Task) -> None:
    """Best-effort email to the assignee when a new task is created."""
    recipient = (task.assignee.email or "").strip()
    if not recipient:
        return
    assignee_name = (
        task.assignee.full_name or task.assignee.username
    )
    creator_name = (
        task.created_by.full_name or task.created_by.username
    )
    subject = f"New task assigned: {task.name}"
    body = (
        f"Hi {assignee_name},\n\n"
        f"{creator_name} has assigned a task to you.\n\n"
        f"Task: {task.name}\n"
        f"Due:  {task.end_date.strftime('%d-%b-%Y')}\n"
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
    """Best-effort email to the creator when the assignee completes it."""
    recipient = (task.created_by.email or "").strip()
    if not recipient:
        return
    creator_name = (
        task.created_by.full_name or task.created_by.username
    )
    assignee_name = (
        task.assignee.full_name or task.assignee.username
    )
    completed_on = (task.completed_at or timezone.now()).strftime(
        "%d-%b-%Y %H:%M",
    )
    subject = f"Task completed: {task.name}"
    body = (
        f"Hi {creator_name},\n\n"
        f"{assignee_name} has marked the following task as completed.\n\n"
        f"Task:          {task.name}\n"
        f"Completed on:  {completed_on}\n"
        f"Assigned on:   {task.created_at.strftime('%d-%b-%Y %H:%M')}\n"
        f"\nAssignee remarks:\n{task.assignee_remarks or '(none)'}\n\n"
        "— JD ERP"
    )
    ok, msg = send_email(recipient=recipient, subject=subject, body=body)
    if not ok:
        logger.warning(
            "Task #%s complete email to %s failed: %s",
            task.id, recipient, msg,
        )
