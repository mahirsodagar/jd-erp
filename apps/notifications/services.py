"""Queue + dispatch helpers for the notifications app.

`queue_notification(...)` writes a row to either `ScheduledNotification`
(if a `fire_at` is given) or directly to `NotificationDispatchLog`
(immediate). `process_due()` drains the schedule queue.

On PythonAnywhere free we cannot reach external SMTP / MSG91 hostnames,
so the dispatcher just creates a `NotificationDispatchLog` row at
status=QUEUED. Replace `_send` once outbound is reachable.
"""

from datetime import datetime
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    NotificationDispatchLog, NotificationTemplate, ScheduledNotification,
)


def _render(template_text: str, context: dict) -> str:
    if not template_text:
        return ""
    try:
        return template_text.format(**(context or {}))
    except (KeyError, IndexError, ValueError):
        # Missing placeholder = fall back to literal template; we'd
        # rather queue an imperfect message than drop it silently.
        return template_text


def _gfk_for(obj) -> tuple[ContentType | None, str]:
    if obj is None:
        return None, ""
    return ContentType.objects.get_for_model(obj.__class__), str(obj.pk)


def queue_notification(
    *, template_key: str, recipient: str, context: dict | None = None,
    cc: str = "", fire_at: datetime | None = None, related=None,
) -> NotificationDispatchLog | ScheduledNotification:
    """Queue a notification for dispatch.

    - If `fire_at` is in the future, creates a `ScheduledNotification`
      row that `process_due()` will handle.
    - Otherwise creates a `NotificationDispatchLog` directly at
      status=QUEUED.
    """
    try:
        tmpl = NotificationTemplate.objects.get(key=template_key, is_active=True)
    except NotificationTemplate.DoesNotExist:
        # Templates can be added later; we still want to queue the intent
        # so the row shows up in the dispatch log for diagnosis.
        ct, oid = _gfk_for(related)
        return NotificationDispatchLog.objects.create(
            channel="EMAIL",
            template_key=template_key,
            recipient=recipient, cc=cc,
            subject="(template missing)",
            body=f"Template '{template_key}' not registered.",
            status=NotificationDispatchLog.Status.FAILED,
            error=f"Template '{template_key}' not registered.",
            content_type=ct, object_id=oid,
        )

    now = timezone.now()
    ct, oid = _gfk_for(related)
    if fire_at and fire_at > now:
        return ScheduledNotification.objects.create(
            template_key=template_key, channel=tmpl.channel,
            recipient=recipient, cc=cc, context=context or {},
            fire_at=fire_at, content_type=ct, object_id=oid,
        )

    return _dispatch_now(tmpl, recipient, cc, context or {}, ct, oid)


def _dispatch_now(tmpl, recipient, cc, context, ct, oid,
                  scheduled=None) -> NotificationDispatchLog:
    subject = _render(tmpl.subject_template, context)
    body = _render(tmpl.body_template, context)
    return NotificationDispatchLog.objects.create(
        channel=tmpl.channel, template_key=tmpl.key,
        recipient=recipient, cc=cc,
        subject=subject, body=body,
        status=NotificationDispatchLog.Status.QUEUED,
        content_type=ct, object_id=oid, scheduled=scheduled,
    )


def process_due(*, batch_size: int = 200) -> dict:
    """Move due `ScheduledNotification` rows into the dispatch log.

    Returns counts: {processed, dispatched, missing_template, errors}.
    """
    now = timezone.now()
    qs = ScheduledNotification.objects.filter(
        fire_at__lte=now, processed_at__isnull=True,
    ).order_by("fire_at")[:batch_size]

    processed = dispatched = missing = errors = 0
    for sn in qs:
        processed += 1
        try:
            tmpl = NotificationTemplate.objects.get(
                key=sn.template_key, is_active=True,
            )
        except NotificationTemplate.DoesNotExist:
            missing += 1
            sn.processed_at = now
            sn.save(update_fields=["processed_at"])
            NotificationDispatchLog.objects.create(
                channel=sn.channel, template_key=sn.template_key,
                recipient=sn.recipient, cc=sn.cc,
                body=f"Template '{sn.template_key}' not registered.",
                status=NotificationDispatchLog.Status.FAILED,
                error=f"Template '{sn.template_key}' not registered.",
                content_type=sn.content_type, object_id=sn.object_id,
                scheduled=sn,
            )
            continue
        try:
            _dispatch_now(
                tmpl, sn.recipient, sn.cc, sn.context,
                sn.content_type, sn.object_id, scheduled=sn,
            )
            dispatched += 1
        except Exception as e:  # pragma: no cover — defensive
            errors += 1
            sn.save(update_fields=["processed_at"])
            continue
        sn.processed_at = now
        sn.save(update_fields=["processed_at"])

    return {
        "processed": processed,
        "dispatched": dispatched,
        "missing_template": missing,
        "errors": errors,
    }
