from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class NotificationTemplate(models.Model):
    """Reusable email / WhatsApp / SMS / in-CRM templates. Body uses
    Python str.format() with named placeholders from the context dict
    passed at queue-time."""

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        SMS = "SMS", "SMS"
        IN_CRM = "IN_CRM", "In-CRM"

    key = models.CharField(
        max_length=80, unique=True,
        help_text="Stable id, e.g. 'lead_welcome', 'hot_why_join_jd'.",
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    subject_template = models.CharField(max_length=200, blank=True)
    body_template = models.TextField()
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key", "channel")

    def __str__(self):
        return f"{self.key} [{self.channel}]"


class ScheduledNotification(models.Model):
    """Future-dated notification waiting to be processed by the
    `process_notifications` management command.

    On PA free we have no Celery / cron — this table acts as the queue.
    Run the command on whatever schedule the host supports (manual,
    PythonAnywhere Tasks, OS cron once you upgrade).
    """

    template_key = models.CharField(max_length=80, db_index=True)
    channel = models.CharField(max_length=10, choices=NotificationTemplate.Channel.choices)
    recipient = models.CharField(max_length=200)
    cc = models.CharField(max_length=400, blank=True)
    context = models.JSONField(default=dict, blank=True)

    fire_at = models.DateTimeField(db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # Generic relation to whatever object triggered this notification
    # (a Lead, a LeadFollowup, an Enrollment, etc.).
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
    )
    object_id = models.CharField(max_length=64, blank=True, default="")
    related_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("fire_at",)
        indexes = [
            models.Index(fields=["fire_at", "processed_at"]),
        ]

    def __str__(self):
        return f"{self.template_key} → {self.recipient} @ {self.fire_at:%Y-%m-%d %H:%M}"


class NotificationDispatchLog(models.Model):
    """One row per intended dispatch. On PA free no real provider call is
    made — the row stays at status='QUEUED' forever and a future
    drainer (when SMTP / MSG91 hostname is reachable) will flip them to
    'SENT' or 'FAILED'."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    channel = models.CharField(max_length=10, choices=NotificationTemplate.Channel.choices)
    template_key = models.CharField(max_length=80, db_index=True)
    recipient = models.CharField(max_length=200)
    cc = models.CharField(max_length=400, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True,
    )
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
    )
    object_id = models.CharField(max_length=64, blank=True, default="")
    related_object = GenericForeignKey("content_type", "object_id")

    scheduled = models.ForeignKey(
        ScheduledNotification, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dispatches",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]
