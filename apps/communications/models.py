"""Communication → Bulk Email.

Campaigns, their per-recipient rows, reusable templates and the
suppression list. This app owns *what* is sent to *whom*; it does not
send. Delivery (SMTP / provider API, pacing, bounce feed) is a separate
piece of work — until it lands a campaign is queued and stays queued.

Status flow for a campaign:

    scheduled ──(scheduled_at passes)──▶ queued ──▶ sending ──▶ completed
        │                                  │           │
        └──────────── paused ◀─────────────┴───────────┘
                        │
                        ▼
                    cancelled   (pending recipients → skipped)

Recipient rows are snapshotted at create time (name, email, context) so
a later edit to the lead / student / employee never rewrites history.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class EmailTemplate(models.Model):
    """A reusable subject + HTML body. Loading one into Compose copies
    the text; the campaign keeps its own copy, so editing a template
    never changes an email already sent."""

    name = models.CharField(max_length=120, unique=True)
    subject = models.CharField(max_length=200, blank=True)
    body_html = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="email_templates_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="email_templates_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Suppression(models.Model):
    """An address every campaign skips. Filled by unsubscribe clicks and
    hard bounces (once delivery exists) and by hand from the
    Unsubscribes page. Removing a row means the person is emailed again."""

    class Reason(models.TextChoices):
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        BOUNCED = "bounced", "Bounced"
        MANUAL = "manual", "Added manually"

    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    # Campaign subject that triggered it, or "Added by <name>".
    source = models.CharField(max_length=200, blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="suppressions_added",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-added_at",)

    def __str__(self):
        return f"{self.email} ({self.reason})"

    @staticmethod
    def normalise(email: str) -> str:
        return (email or "").strip().lower()


def _attachment_path(instance, filename):
    return f"communications/attachments/{instance.pk or 'new'}/{filename}"


class EmailCampaign(models.Model):
    class Source(models.TextChoices):
        LEADS = "leads", "Leads"
        STUDENTS = "students", "Students"
        EMPLOYEES = "employees", "Employees"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    LIVE_STATUSES = (Status.SCHEDULED, Status.QUEUED, Status.SENDING)
    TERMINAL_STATUSES = (Status.COMPLETED, Status.CANCELLED)

    subject = models.CharField(max_length=200)
    source = models.CharField(max_length=16, choices=Source.choices)
    # The filter dict exactly as the Compose step sent it, so the
    # audience can be re-run / audited later.
    filters = models.JSONField(default=dict, blank=True)
    # Human labels for those filters ("Campus": "Bengaluru"), captured
    # at send time so History never needs a second lookup.
    filter_labels = models.JSONField(default=dict, blank=True)
    audience_summary = models.CharField(max_length=300, blank=True)

    from_email = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    body_html = models.TextField()
    include_unsubscribe = models.BooleanField(default=True)

    attachment = models.FileField(
        upload_to=_attachment_path, blank=True, null=True,
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    attachment_size = models.PositiveIntegerField(default=0)

    template = models.ForeignKey(
        EmailTemplate, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="campaigns",
    )
    template_name = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED,
        db_index=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="email_campaigns",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"[{self.status}] {self.subject}"

    @property
    def is_live(self) -> bool:
        return self.status in self.LIVE_STATUSES


class EmailCampaignRecipient(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        UNSUBSCRIBED = "unsubscribed", "Unsubscribed"
        SKIPPED = "skipped", "Skipped"

    campaign = models.ForeignKey(
        EmailCampaign, on_delete=models.CASCADE, related_name="recipients",
    )
    # "lead:123", "student:45:father", "employee:7" — the audience key
    # the Compose preview used, kept for de-dup and per-record history.
    source_key = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField()
    context = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["email"]),
        ]

    def __str__(self):
        return f"{self.email} [{self.status}]"
