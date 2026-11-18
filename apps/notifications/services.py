"""Queue + dispatch helpers for the notifications app.

`queue_notification(...)` writes a row to either `ScheduledNotification`
(if a `fire_at` is given) or directly to `NotificationDispatchLog`
(immediate). `process_due()` drains the schedule queue.

Email leaves through the one ZeptoMail SMTP transport
(`apps.notifications.email.send_email`) From `no-reply@dkul.in`, with
the Reply-To resolved per trigger (`apps.notifications.reply_to`).
Template bodies live in `NotificationTemplate` rows; an HTML body (one
that starts with a tag) is sent as HTML with a text fallback.
"""

import re
from datetime import datetime
from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    NotificationDispatchLog, NotificationTemplate, ScheduledNotification,
)


# `{name}` (our seeded bodies) and `{{name}}` (the client's HTML
# templates, which were written for MSG91's double-brace syntax).
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _render(template_text: str, context: dict) -> str:
    """Substitute `{var}` / `{{var}}` placeholders from `context`.

    Unlike `str.format`, braces that are not a placeholder (CSS blocks
    in an HTML template, literal `{`) pass through untouched, and an
    unknown placeholder is left as-is rather than failing the whole
    render — we would rather send an imperfect message than drop it.
    """
    if not template_text:
        return ""
    context = context or {}

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in context:
            v = context[name]
            return "" if v is None else str(v)
        return m.group(0)

    return _PLACEHOLDER_RE.sub(sub, template_text)


def _looks_html(text: str) -> bool:
    return (text or "").lstrip()[:1] == "<"


def _gfk_for(obj) -> tuple[ContentType | None, str]:
    if obj is None:
        return None, ""
    return ContentType.objects.get_for_model(obj.__class__), str(obj.pk)


def _guess_channel(template_key: str) -> str:
    """Best-effort channel inference from a template_key suffix.
    Used only when no NotificationTemplate row exists — so the
    "missing template" log row at least picks the right column.
    Accepts both dot- and underscore-namespacing."""
    k = template_key.lower()
    if k.endswith(".sms") or k.endswith("_sms"):
        return "SMS"
    if k.endswith(".wa") or k.endswith("_wa") or k.endswith(".whatsapp"):
        return "WHATSAPP"
    if k.endswith(".in_crm") or k.endswith("_in_crm"):
        return "IN_CRM"
    return "EMAIL"


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
        # so the row shows up in the dispatch log for diagnosis. The
        # `channel` value is a best-effort guess from the key suffix so
        # the log row is filterable; the actual send didn't happen.
        ct, oid = _gfk_for(related)
        return NotificationDispatchLog.objects.create(
            channel=_guess_channel(template_key),
            template_key=template_key,
            recipient=recipient, cc=cc,
            subject="(template missing)",
            body=f"Template '{template_key}' not registered.",
            status=NotificationDispatchLog.Status.FAILED,
            error=f"Template '{template_key}' not registered. "
                  f"Run `python manage.py seed_notification_templates` "
                  f"or add it via Django admin.",
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


def _send_email(tmpl, recipient, cc, subject, body, context) -> tuple[bool, str]:
    """Deliver one email over the ZeptoMail transport.

    From is fixed (no-reply@dkul.in); the Reply-To comes from the
    per-trigger policy / the caller's context (see reply_to.py). A body
    that is HTML goes out as HTML with a text alternative.
    """
    from .email import send_email
    from .reply_to import resolve_reply_to

    return send_email(
        recipient=recipient, cc=cc, subject=subject, body=body,
        is_html=_looks_html(tmpl.body_template),
        reply_to=resolve_reply_to(tmpl.key, context),
    )


def _dispatch_now(tmpl, recipient, cc, context, ct, oid,
                  scheduled=None) -> NotificationDispatchLog:
    subject = _render(tmpl.subject_template, context)
    body = _render(tmpl.body_template, context)

    log = NotificationDispatchLog.objects.create(
        channel=tmpl.channel, template_key=tmpl.key,
        recipient=recipient, cc=cc,
        subject=subject, body=body,
        status=NotificationDispatchLog.Status.QUEUED,
        content_type=ct, object_id=oid, scheduled=scheduled,
    )

    # Real outbound: SMS / EMAIL / WhatsApp. In-CRM stays queued (no
    # transport — it's read in the CRM UI).
    Channel = NotificationTemplate.Channel
    if tmpl.channel == Channel.SMS:
        from .sms import send_sms
        # MSG91 SMS uses positional vars (var1/var2/...) from the raw
        # context dict — it ignores `body`. BulkSMS uses the rendered
        # body. We pass both so the facade can route correctly.
        ok, payload = send_sms(
            recipient=recipient, body=body, template_key=tmpl.key,
            context=context,
        )
        log.status = (NotificationDispatchLog.Status.SENT if ok
                      else NotificationDispatchLog.Status.FAILED)
        log.error = "" if ok else payload
        log.save(update_fields=["status", "error"])
    elif tmpl.channel == Channel.WHATSAPP:
        # XIRCLS is trigger+parameter based (it stores the approved body
        # on their side), so it ignores `body` and uses the raw context.
        # While WHATSAPP_ENABLED is off the row stays QUEUED — same as
        # before this driver landed — so turning the feature on is the only
        # thing that starts real sends.
        from django.conf import settings as _settings
        if getattr(_settings, "WHATSAPP_ENABLED", False):
            from .whatsapp import send_whatsapp
            ok, payload = send_whatsapp(
                recipient=recipient, template_key=tmpl.key, context=context,
            )
            log.status = (NotificationDispatchLog.Status.SENT if ok
                          else NotificationDispatchLog.Status.FAILED)
            log.error = "" if ok else payload
            log.save(update_fields=["status", "error"])
    elif tmpl.channel == Channel.EMAIL:
        ok, payload = _send_email(tmpl, recipient, cc, subject, body, context)
        log.status = (NotificationDispatchLog.Status.SENT if ok
                      else NotificationDispatchLog.Status.FAILED)
        log.error = "" if ok else payload
        log.save(update_fields=["status", "error"])

    return log


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
